"""Grants.gov XML extract importer.

Downloads today's GrantsDBExtract ZIP from the Grants.gov S3 bucket,
parses the XML, and upserts open grant opportunities into the
grant_opportunities table.

Runs daily via APScheduler. Can also be triggered manually via
POST /discovery/import/grants-gov.

Grants.gov XML extract docs:
  https://www.grants.gov/xml-extract.html
  File: GrantsDBExtract{YYYYMMDD}v2.zip (~77MB)
  Updated: ~4:40am EDT daily
"""

from __future__ import annotations

import glob
import io
import logging
import os
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

_S3_URL_TEMPLATE = (
    "https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/GrantsDBExtract{date}v2.zip"
)
_HEADERS = {"User-Agent": "automated-funding-bot/1.0"}
_BATCH_SIZE = 200


def _grants_gov_url(for_date: Optional[date] = None) -> str:
    d = for_date or datetime.now(timezone.utc).date()
    return _S3_URL_TEMPLATE.format(date=d.strftime("%Y%m%d"))


def _parse_int(val: Optional[str]) -> Optional[int]:
    try:
        return int(val) if val and val.strip() else None
    except (ValueError, TypeError):
        return None


def _parse_date(val: Optional[str]) -> Optional[str]:
    """Parse Grants.gov date strings → 'YYYY-MM-DD'.

    Handles: 'MM/DD/YYYY', 'YYYY-MM-DD', and the compact 'MMDDYYYY' format
    used in the XML extract (e.g. '09042014' → '2014-09-04').
    """
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m%d%Y"):
        try:
            return datetime.strptime(val, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _text(el: Optional[ET.Element], tag: str) -> Optional[str]:
    """Return the text of a child element, handling XML namespaces.

    Grants.gov XML uses a default namespace on the root, which propagates to
    every child element.  el.find("CloseDate") fails when the actual tag is
    '{http://...}CloseDate'.  We detect the namespace from the parent element
    and try the prefixed form as a fallback.
    """
    if el is None:
        return None
    child = el.find(tag)
    if child is None and "}" in el.tag:
        ns_prefix = el.tag.split("}")[0] + "}"
        child = el.find(f"{ns_prefix}{tag}")
    return child.text.strip() if child is not None and child.text else None


def _texts_all(el: Optional[ET.Element], tag: str) -> List[str]:
    """Return all text values for repeating child elements (e.g. EligibleApplicants,
    CategoryOfFundingActivity which can appear multiple times)."""
    if el is None:
        return []
    children = el.findall(tag)
    if not children and "}" in el.tag:
        ns_prefix = el.tag.split("}")[0] + "}"
        children = el.findall(f"{ns_prefix}{tag}")
    out: List[str] = []
    for c in children:
        if c.text and c.text.strip():
            out.append(c.text.strip())
    return out


def _parse_bool_yn(val: Optional[str]) -> Optional[bool]:
    """Grants.gov uses 'Yes' / 'No' strings for boolean-ish fields."""
    if not val:
        return None
    v = val.strip().lower()
    if v in ("yes", "y", "true", "1"):
        return True
    if v in ("no", "n", "false", "0"):
        return False
    return None


def _parse_opportunity(opp: ET.Element) -> Optional[Dict[str, Any]]:
    """Extract a grant_opportunities record from an <OpportunitySynopsisDetail_1_0> element."""
    opp_id = _text(opp, "OpportunityID")
    if not opp_id:
        return None

    # Build the canonical detail-page URL
    url = f"https://www.grants.gov/search-results-detail/{opp_id}"

    close_date = _parse_date(_text(opp, "CloseDate") or _text(opp, "ApplicationsDueDate"))
    posted_date = _parse_date(_text(opp, "PostDate"))

    # Description: try several element names used across XML versions.
    description = (
        _text(opp, "Description")
        or _text(opp, "Synopsis")
        or _text(opp, "SynopsisDesc")
        or _text(opp, "AgencyContactDescription")
    )

    # XML can repeat CategoryOfFundingActivity / EligibleApplicants — join the
    # category for the legacy single-value column, store the eligible_applicants
    # list as TEXT[].
    categories = _texts_all(opp, "CategoryOfFundingActivity")
    eligible_applicants = _texts_all(opp, "EligibleApplicants")

    return {
        "opportunity_id": opp_id,
        "opportunity_number": _text(opp, "OpportunityNumber"),
        "title": _text(opp, "OpportunityTitle"),
        "agency": _text(opp, "AgencyName"),
        "agency_code": _text(opp, "AgencyCode"),
        "posted_date": posted_date,
        "close_date": close_date,
        "archive_date": _parse_date(_text(opp, "ArchiveDate")),
        "last_updated_date": _parse_date(_text(opp, "LastUpdatedDate")),
        "award_ceiling": _parse_int(_text(opp, "AwardCeiling")),
        "award_floor": _parse_int(_text(opp, "AwardFloor")),
        "estimated_total_program_funding": _parse_int(_text(opp, "EstimatedTotalProgramFunding")),
        "expected_number_of_awards": _parse_int(_text(opp, "ExpectedNumberOfAwards")),
        "opportunity_category": _text(opp, "OpportunityCategory"),
        "funding_instrument_type": _text(opp, "FundingInstrumentType"),
        "category": " | ".join(categories) if categories else None,
        "category_explanation": _text(opp, "CategoryExplanation"),
        "eligible_applicants": eligible_applicants or None,
        "cfda_number": _text(opp, "CFDANumbers"),
        "eligibility_text": _text(opp, "AdditionalInformationOnEligibility"),
        "cost_sharing_or_matching_required": _parse_bool_yn(_text(opp, "CostSharingOrMatchingRequirement")),
        "version": _text(opp, "Version"),
        "grantor_contact_email": _text(opp, "GrantorContactEmail"),
        "grantor_contact_email_description": _text(opp, "GrantorContactEmailDescription"),
        "grantor_contact_text": _text(opp, "GrantorContactText"),
        "description": description,
        "url": url,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _upsert_batch(batch: List[Dict[str, Any]], sb) -> int:
    try:
        sb.table("grant_opportunities").upsert(
            batch,
            on_conflict="opportunity_id",
            ignore_duplicates=False,
        ).execute()
        return len(batch)
    except Exception as exc:
        logger.warning("Grants.gov batch upsert failed (%d rows): %s", len(batch), exc)
        return 0


def _download_grants_gov_zip(for_date: Optional[date] = None) -> Optional[bytes]:
    """Try today's extract, then yesterday's if today's isn't up yet (posted ~4:40am EDT)."""
    today = datetime.now(timezone.utc).date()
    candidates = [for_date] if for_date else [
        today,
        today - timedelta(days=1),
        today - timedelta(days=2),
    ]
    for d in candidates:
        url = _grants_gov_url(d)
        logger.info("Grants.gov import: trying %s", url)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=180)
            if resp.status_code == 404:
                logger.info("Grants.gov: %s not found (404), trying previous day", url)
                continue
            resp.raise_for_status()
            logger.info("Grants.gov: downloaded %s (%.1f MB)", url, len(resp.content) / 1e6)
            return resp.content
        except Exception as exc:
            logger.error("Grants.gov download failed for %s: %s", url, exc)
    return None


def _load_tree_from_local(local_path: str) -> Optional[ET.ElementTree]:
    """Load the Grants.gov XML tree from a local path.

    Accepts either:
      - a path to an already-extracted XML file (e.g. data/downloads/GrantsDBExtract20260526v2.xml)
      - a path to a directory containing such an XML file (we pick the most recent)
      - a path to a .zip file matching the upstream format
    """
    if os.path.isdir(local_path):
        candidates = sorted(glob.glob(os.path.join(local_path, "GrantsDBExtract*.xml")))
        if not candidates:
            candidates = sorted(glob.glob(os.path.join(local_path, "GrantsDBExtract*.zip")))
        if not candidates:
            logger.error("Grants.gov: no GrantsDBExtract* file found in %s", local_path)
            return None
        local_path = candidates[-1]
    if local_path.endswith(".zip"):
        try:
            with zipfile.ZipFile(local_path) as zf:
                xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
                if not xml_names:
                    raise ValueError("no XML in zip")
                with zf.open(xml_names[0]) as xf:
                    return ET.parse(xf)
        except Exception as exc:
            logger.error("Grants.gov local zip parse failed: %s", exc)
            return None
    try:
        return ET.parse(local_path)
    except Exception as exc:
        logger.error("Grants.gov local XML parse failed: %s", exc)
        return None


def run_grants_gov_import(
    for_date: Optional[date] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    *,
    local_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Download Grants.gov XML extract and upsert to grant_opportunities.

    Args:
        for_date:   target a specific date when downloading (default: today, with
                    fallback to yesterday/day-before).
        progress_cb: optional callback for status updates.
        local_path: when set, read a local .xml or .zip (or pick the most recent
                    from a directory) instead of downloading. Used by the backfill
                    script.

    Returns stats dict: { parsed, upserted, skipped_expired, errors, elapsed_seconds }
    """
    from supabase import create_client
    from utils.config import get_settings
    _s = get_settings()
    sb = create_client(_s.supabase_url, _s.supabase_service_key)

    started = time.time()
    parsed = upserted = skipped_expired = errors = 0
    today = datetime.now(timezone.utc).date()

    if local_path:
        if progress_cb:
            try:
                progress_cb({"message": f"loading Grants.gov XML from {local_path}"})
            except Exception:
                pass
        tree = _load_tree_from_local(local_path)
        if tree is None:
            return {"parsed": 0, "upserted": 0, "skipped_expired": 0, "errors": 1, "elapsed_seconds": 0}
    else:
        if progress_cb:
            try:
                progress_cb({"message": "downloading Grants.gov XML extract (up to 3 days back)"})
            except Exception:
                pass

        content = _download_grants_gov_zip(for_date)
        if content is None:
            logger.error("Grants.gov: could not download extract for any candidate date")
            return {"parsed": 0, "upserted": 0, "skipped_expired": 0, "errors": 1, "elapsed_seconds": 0}

        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
                logger.info("Grants.gov ZIP contents: %s", zf.namelist())
                if not xml_names:
                    raise ValueError("No XML file found in ZIP")
                xml_name = xml_names[0]
                logger.info("Grants.gov: parsing %s", xml_name)
                with zf.open(xml_name) as xf:
                    tree = ET.parse(xf)
        except Exception as exc:
            logger.error("Grants.gov ZIP/XML parse failed: %s", exc)
            return {"parsed": 0, "upserted": 0, "skipped_expired": 0, "errors": 1, "elapsed_seconds": 0}

    root = tree.getroot()
    logger.info("Grants.gov XML root tag: %s", root.tag)

    # Handle namespace-prefixed elements from Grants.gov XML
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    tag_prefix = f"{{{ns}}}" if ns else ""

    # Grants.gov XML uses OpportunitySynopsisDetail_1_0 at the top level or nested.
    # Try that first; if 0 found, log the actual child tags for debugging.
    target_tag = f"{tag_prefix}OpportunitySynopsisDetail_1_0"
    all_opps = list(root.iter(target_tag))
    logger.info("Grants.gov: found %d %s elements", len(all_opps), target_tag)
    if not all_opps:
        # Log what tags are actually present so we can fix the parser
        child_tags = {child.tag for child in root.iter()}
        logger.warning("Grants.gov: no opportunity elements found. Tags in XML: %s", list(child_tags)[:20])

    if progress_cb:
        try:
            progress_cb({"message": f"parsing {len(all_opps)} grant opportunities"})
        except Exception:
            pass

    batch: List[Dict[str, Any]] = []
    for opp in all_opps:
        rec = _parse_opportunity(opp)
        if rec is None:
            errors += 1
            continue
        parsed += 1

        # Skip already-expired opportunities
        if rec["close_date"] and rec["close_date"] < today.isoformat():
            skipped_expired += 1
            continue

        batch.append(rec)
        if len(batch) >= _BATCH_SIZE:
            upserted += _upsert_batch(batch, sb)
            batch = []

    if batch:
        upserted += _upsert_batch(batch, sb)

    elapsed = round(time.time() - started, 1)
    stats = {
        "parsed": parsed,
        "upserted": upserted,
        "skipped_expired": skipped_expired,
        "errors": errors,
        "elapsed_seconds": elapsed,
    }
    logger.info("Grants.gov import complete: %s", stats)

    if parsed > 0 or upserted > 0:
        try:
            from utils.discovery.config_store import update_import_timestamps
            update_import_timestamps(grants_gov_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            logger.warning("Could not update Grants.gov import timestamp: %s", exc)
    else:
        logger.warning("Grants.gov: 0 records parsed/upserted — NOT writing import timestamp")

    return stats


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Grants.gov XML importer")
    parser.add_argument("--local", dest="local_path",
                        help="Path to local .xml/.zip or a directory containing GrantsDBExtract*.xml")
    parser.add_argument("--date", dest="for_date",
                        help="Override target date as YYYY-MM-DD (only when not using --local)")
    args = parser.parse_args()
    for_date = date.fromisoformat(args.for_date) if args.for_date else None
    print(run_grants_gov_import(for_date=for_date, local_path=args.local_path))
