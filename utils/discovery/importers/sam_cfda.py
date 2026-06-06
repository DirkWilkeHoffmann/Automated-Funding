"""SAM.gov Assistance Listings (CFDA catalog) importer.

Downloads the public CSV export of every federal grant program (~8,000 entries)
and upserts into the sam_cfda_listings table.

Used as an ENRICHMENT source for Grants.gov opportunities (Phase 3) — the
GrantsGovDBSource will look up by `cfda_number` and attach Objectives,
Applicant Eligibility, Funding Range, and Examples of Funded Projects as
extra LLM context.

Source CSV (~8.5 MB):
  https://sam.gov/api/prod/fal/v1/files/datagov/PUBLIC_CURRENT/AssistanceListings_DataGov_PUBLIC_CURRENT.csv

Encoding note: the CSV contains non-UTF-8 bytes (e.g. smart quotes encoded as
Windows-1252), so we parse with `encoding="latin-1"` which never raises and
correctly round-trips the byte values into Python strings.

Runs weekly via APScheduler (Phase 2). Can also be triggered manually via
POST /discovery/import/sam-cfda, or from a local file via
    python -m utils.discovery.importers.sam_cfda --local data/downloads/
"""

from __future__ import annotations

import csv
import glob
import io
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Public URL (no auth required). SAM.gov occasionally rotates these paths;
# if it 404s, the file can be downloaded manually from the data.gov page
# linked at https://sam.gov/data-services/Assistance%20Listings/datagov
_DOWNLOAD_URL = (
    "https://sam.gov/api/prod/fal/v1/files/datagov/"
    "PUBLIC_CURRENT/AssistanceListings_DataGov_PUBLIC_CURRENT.csv"
)
_HEADERS = {
    "User-Agent": "automated-funding-bot/1.0",
    "Accept": "text/csv,*/*",
}
_BATCH_SIZE = 200

# Map raw CSV header → DB column name. The CSV uses "(0NN)" suffixes that
# come from the federal Code of Federal Domestic Assistance numbering — we
# strip them in the DB columns since they're not informative for queries.
_COLUMN_MAP: Dict[str, str] = {
    "Program Title":                                    "program_title",
    "Program Number":                                   "program_number",
    "Popular Name (020)":                               "popular_name",
    "Federal Agency (030)":                             "federal_agency",
    "Parent Shortname":                                 "parent_shortname",
    "Authorization (040)":                              "authorization_text",
    "Objectives (050)":                                 "objectives",
    "Types of Assistance (060)":                        "types_of_assistance",
    "Uses and Use Restrictions (070)":                  "uses_and_restrictions",
    "Applicant Eligibility (081)":                      "applicant_eligibility",
    "Beneficiary Eligibility (082)":                    "beneficiary_eligibility",
    "Credentials/Documentation (083)":                  "credentials_documentation",
    "Preapplication Coordination (091)":                "preapplication_coordination",
    "Application Procedures (092)":                     "application_procedures",
    "Award Procedure (093)":                            "award_procedure",
    "Deadlines (094)":                                  "deadlines",
    "Range of Approval/Disapproval Time (095)":         "range_of_approval_time",
    "Appeals (096)":                                    "appeals",
    "Renewals (097)":                                   "renewals",
    "Formula and Matching Requirements (101)":          "formula_and_matching_requirements",
    "Length and Time Phasing of Assistance (102)":      "length_and_time_phasing",
    "Reports (111)":                                    "reports",
    "Audits (112)":                                     "audits",
    "Records (113)":                                    "records",
    "Account Identification (121)":                     "account_identification",
    "Obligations (122)":                                "obligations",
    "Range and Average of Financial Assistance (123)":  "range_and_average_assistance",
    "Program Accomplishments (130)":                    "program_accomplishments",
    "Regulations, Guidelines, and Literature (140)":    "regulations_guidelines_literature",
    "Regional or Local Office (151)":                   "regional_or_local_office",
    "Headquarters Office (152)":                        "headquarters_office",
    "Website Address (153)":                            "website_address",
    "Related Programs (160)":                           "related_programs",
    "Examples of Funded Projects (170)":                "examples_of_funded_projects",
    "Criteria for Selecting Proposals (180)":           "criteria_for_selecting_proposals",
    "Recovery":                                         "recovery",
    "URL":                                              "url",
    "Published Date":                                   "published_date",  # parsed to DATE
}


def _s(val: Optional[str]) -> Optional[str]:
    """Strip + treat empty/'null'/'Not Applicable' as NULL.

    SAM.gov uses literal "null" and "Not Applicable" strings for absent
    fields — storing those verbatim pollutes the data, so we coerce to NULL.
    """
    if val is None:
        return None
    out = val.strip()
    if not out:
        return None
    if out.lower() in ("null", "not applicable", "none", "none;"):
        return None
    return out


def _parse_date(val: Optional[str]) -> Optional[str]:
    """Parse SAM.gov published-date strings to ISO YYYY-MM-DD."""
    raw = _s(val)
    if not raw:
        return None
    # Observed formats: "MM/DD/YYYY", "YYYY-MM-DD", short integers (year only)
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _row_to_record(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Convert a CSV row to a sam_cfda_listings record. Returns None when the
    program_number is missing or marked 'Not Applicable' (~placeholder rows)."""
    program_number = _s(row.get("Program Number"))
    if not program_number:
        return None

    record: Dict[str, Any] = {}
    for csv_key, db_col in _COLUMN_MAP.items():
        raw = row.get(csv_key)
        if db_col == "published_date":
            record[db_col] = _parse_date(raw)
        else:
            record[db_col] = _s(raw)
    # Guarantee the PK survives the nullification pass above
    record["program_number"] = program_number
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    return record


def _upsert_batch(batch: List[Dict[str, Any]], sb) -> int:
    try:
        sb.table("sam_cfda_listings").upsert(
            batch,
            on_conflict="program_number",
            ignore_duplicates=False,
        ).execute()
        return len(batch)
    except Exception as exc:
        logger.warning("SAM.gov CFDA batch upsert failed (%d rows): %s", len(batch), exc)
        return 0


def _resolve_local_path(local_dir: str) -> Optional[str]:
    """Find the CSV inside a local directory. Accepts the file path itself or
    a directory containing AssistanceListings_DataGov_*.csv."""
    if os.path.isfile(local_dir):
        return local_dir
    if os.path.isdir(local_dir):
        candidates = sorted(
            glob.glob(os.path.join(local_dir, "AssistanceListings_DataGov_*.csv"))
        )
        if candidates:
            # Prefer PUBLIC_CURRENT over dated weekly snapshots
            current = [c for c in candidates if "PUBLIC_CURRENT" in c]
            return current[-1] if current else candidates[-1]
    return None


def _open_csv_stream(*, local_dir: Optional[str] = None) -> Optional["csv.DictReader[str]"]:
    """Return a configured csv.DictReader, either from a local file or HTTP."""
    if local_dir:
        path = _resolve_local_path(local_dir)
        if not path:
            logger.error("SAM.gov CFDA: no local CSV found in %s", local_dir)
            return None
        logger.info("SAM.gov CFDA: reading local file %s", path)
        f = open(path, encoding="latin-1", newline="")
        return csv.DictReader(f)
    try:
        resp = requests.get(_DOWNLOAD_URL, headers=_HEADERS, timeout=120)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("SAM.gov CFDA download failed: %s", exc)
        return None
    # The body may be UTF-8 BOM or latin-1 — decode permissively
    text = resp.content.decode("latin-1", errors="replace")
    return csv.DictReader(io.StringIO(text))


def run_sam_cfda_import(
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    *,
    local_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Download (or read locally) SAM.gov CFDA listings and upsert.

    Args:
        progress_cb: optional callback for status updates.
        local_dir:   if set, read the CSV from this path or directory
                     (looks for AssistanceListings_DataGov_*.csv).

    Returns stats dict: { parsed, upserted, skipped, errors, elapsed_seconds }
    """
    from supabase import create_client
    from utils.config import get_settings
    _s_cfg = get_settings()
    sb = create_client(_s_cfg.supabase_url, _s_cfg.supabase_service_key)

    started = time.time()
    parsed = upserted = skipped = errors = 0

    def _cb(msg: str) -> None:
        logger.info("SAM.gov CFDA: %s", msg)
        if progress_cb:
            try:
                progress_cb({"message": msg, "parsed": parsed, "upserted": upserted})
            except Exception:
                pass

    _cb("starting import")
    reader = _open_csv_stream(local_dir=local_dir)
    if reader is None:
        return {"parsed": 0, "upserted": 0, "skipped": 0, "errors": 1, "elapsed_seconds": 0}

    batch: List[Dict[str, Any]] = []
    for row in reader:
        rec = _row_to_record(row)
        if rec is None:
            skipped += 1
            continue
        parsed += 1
        batch.append(rec)
        if len(batch) >= _BATCH_SIZE:
            upserted += _upsert_batch(batch, sb)
            batch = []
            if parsed % 1000 == 0:
                _cb(f"{parsed} listings processed")

    if batch:
        upserted += _upsert_batch(batch, sb)

    elapsed = round(time.time() - started, 1)
    stats = {
        "parsed": parsed,
        "upserted": upserted,
        "skipped": skipped,
        "errors": errors,
        "elapsed_seconds": elapsed,
    }
    logger.info("SAM.gov CFDA import complete: %s", stats)

    if parsed > 0 or upserted > 0:
        try:
            from utils.discovery.config_store import update_import_timestamps
            update_import_timestamps(sam_cfda_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            logger.warning("Could not update SAM.gov CFDA import timestamp: %s", exc)
    else:
        logger.warning("SAM.gov CFDA: 0 records parsed/upserted — NOT writing timestamp")

    return stats


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="SAM.gov CFDA importer")
    parser.add_argument(
        "--local", dest="local_dir",
        help="Path or directory containing AssistanceListings_DataGov_*.csv "
             "(skip download)",
    )
    args = parser.parse_args()
    print(run_sam_cfda_import(local_dir=args.local_dir))
