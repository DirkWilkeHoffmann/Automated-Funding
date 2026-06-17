"""IRS Exempt Organizations Business Master File (BMF) importer.

Downloads all 4 regional CSV files from irs.gov and upserts into the
discovery_funders table.

**Phase 0 change**: widened from `FOUNDATION='04'` only (~5,787 rows) to
all `SUBSECTION='03'` rows (~1M rows — every 501(c)(3) in the BMF).
Org-profile pre-filter (Phase 3) does the per-run narrowing.

Runs weekly via APScheduler (Phase 2). Can also be triggered manually via
POST /discovery/import/bmf, or from local files via run_bmf_import(local_dir=...).

IRS BMF docs:
  https://www.irs.gov/charities-non-profits/exempt-organizations-business-master-file-extract-eo-bmf

FOUNDATION codes:
  02 = private operating foundation
  03 = private non-operating foundation (must distribute 5%+/yr — exempt from excise tax)
  04 = private non-operating foundation (must distribute 5%+/yr — subject to excise tax)
  10 = public charity (variant determined by classification)
"""

from __future__ import annotations

import csv
import io
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BMF_URLS = [
    "https://www.irs.gov/pub/irs-soi/eo1.csv",
    "https://www.irs.gov/pub/irs-soi/eo2.csv",
    "https://www.irs.gov/pub/irs-soi/eo3.csv",
    "https://www.irs.gov/pub/irs-soi/eo4.csv",
]

# Ingest all 501(c)(3) public charities + private foundations.
# Skip non-501(c)(3)s (labor orgs, social clubs, etc.) — they rarely grant-make.
_TARGET_SUBSECTIONS = {"03"}

_HEADERS = {"User-Agent": "automated-funding-bot/1.0 (grant discovery; contact wilkehoffmann@gmail.com)"}
_BATCH_SIZE = 500


def _parse_int(val: Optional[str]) -> Optional[int]:
    try:
        return int(val) if val and val.strip() else None
    except (ValueError, TypeError):
        return None


def _parse_bigint(val: Optional[str]) -> Optional[int]:
    try:
        return int(float(val)) if val and val.strip() else None
    except (ValueError, TypeError):
        return None


def _s(val: Optional[str]) -> Optional[str]:
    """Strip-or-None helper."""
    if val is None:
        return None
    out = val.strip()
    return out or None


def _row_to_funder(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Convert a BMF CSV row to a discovery_funders record.

    Captures all 28 BMF columns. Returns None when:
      - EIN missing
      - SUBSECTION not in _TARGET_SUBSECTIONS (non-501(c)(3) — labor unions, social clubs, etc.)
    """
    ein = (row.get("EIN") or "").strip()
    if not ein:
        return None
    subsection = (row.get("SUBSECTION") or "").strip()
    if subsection not in _TARGET_SUBSECTIONS:
        return None

    return {
        # core identity
        "ein": ein,
        "name": (row.get("NAME") or "").strip(),
        "ico": _s(row.get("ICO")),
        "street": _s(row.get("STREET")),
        "city": _s(row.get("CITY")),
        "state": _s(row.get("STATE")),
        "zip": _s(row.get("ZIP")),
        "sort_name": _s(row.get("SORT_NAME")),
        # IRS classification
        "group_code": _s(row.get("GROUP")),
        "subsection": subsection,
        "affiliation": _s(row.get("AFFILIATION")),
        "classification": _s(row.get("CLASSIFICATION")),
        "ruling": _s(row.get("RULING")),
        "deductibility": _s(row.get("DEDUCTIBILITY")),
        "foundation_type": _s(row.get("FOUNDATION")),
        "activity": _s(row.get("ACTIVITY")),
        "organization": _s(row.get("ORGANIZATION")),
        "status": _s(row.get("STATUS")),
        "ntee_code": _s(row.get("NTEE_CD")),
        # filing / financial
        "tax_period": _s(row.get("TAX_PERIOD")),
        "asset_code": _parse_int(row.get("ASSET_CD")),
        "income_cd": _parse_int(row.get("INCOME_CD")),
        "filing_req_cd": _s(row.get("FILING_REQ_CD")),
        "pf_filing_req_cd": _s(row.get("PF_FILING_REQ_CD")),
        "acct_pd": _s(row.get("ACCT_PD")),
        "asset_amount": _parse_bigint(row.get("ASSET_AMT")),
        "income_amount": _parse_bigint(row.get("INCOME_AMT")),
        "revenue_amount": _parse_bigint(row.get("REVENUE_AMT")),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _upsert_batch(batch: List[Dict[str, Any]], sb) -> int:
    try:
        sb.table("discovery_funders").upsert(
            batch,
            on_conflict="ein",
            ignore_duplicates=False,
        ).execute()
        return len(batch)
    except Exception as exc:
        logger.warning("BMF batch upsert failed (%d rows): %s", len(batch), exc)
        return 0


def _iter_bmf_rows(
    *,
    local_dir: Optional[str] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> "list[tuple[str, csv.DictReader]]":
    """Yield (region, csv.DictReader) tuples, sourcing from local files or remote URLs.

    When `local_dir` is set, reads files named `eo1.csv`, `eo2.csv`, `eo3.csv`, `eo4.csv`
    (or `irs_bmf_eo*.csv` as downloaded by our analysis script) from that directory.
    Otherwise downloads each URL.
    """
    if local_dir:
        for i in range(1, 5):
            # Accept either naming convention used during initial-load exploration
            candidates = [
                os.path.join(local_dir, f"eo{i}.csv"),
                os.path.join(local_dir, f"irs_bmf_eo{i}.csv"),
            ]
            path = next((p for p in candidates if os.path.isfile(p)), None)
            if not path:
                logger.warning("BMF local file not found for region eo%d in %s", i, local_dir)
                continue
            if progress_cb:
                try:
                    progress_cb({"message": f"reading local file {os.path.basename(path)}"})
                except Exception:
                    pass
            f = open(path, encoding="utf-8", errors="replace")
            yield (f"eo{i}", csv.DictReader(f))
        return

    for url in _BMF_URLS:
        region = url.split("/")[-1].replace(".csv", "")
        if progress_cb:
            try:
                progress_cb({"message": f"downloading {region}"})
            except Exception:
                pass
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=180)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("BMF download failed for %s: %s", url, exc)
            continue
        content = resp.content.decode("utf-8", errors="replace")
        yield (region, csv.DictReader(io.StringIO(content)))


def run_bmf_import(
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    *,
    local_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Download IRS BMF (or read from local files), filter to 501(c)(3)s, upsert.

    Args:
        progress_cb: optional callback invoked with status dicts during the run.
        local_dir:   if set, read eo1.csv..eo4.csv from this directory instead of
                     downloading from irs.gov. Used by the backfill script after
                     bulk download.

    Returns stats dict: { total_rows, target_rows, upserted, errors, elapsed_seconds }
    """
    from supabase import create_client
    from utils.config import get_settings
    _s = get_settings()
    sb = create_client(_s.supabase_url, _s.supabase_service_key)

    started = time.time()
    total_rows = 0
    target_rows = 0
    upserted = 0
    errors = 0

    def _cb(msg: str) -> None:
        logger.info("BMF import: %s", msg)
        if progress_cb:
            try:
                progress_cb({"message": msg, "upserted": upserted, "target_rows": target_rows})
            except Exception:
                pass

    for region, reader in _iter_bmf_rows(local_dir=local_dir, progress_cb=progress_cb):
        batch: List[Dict[str, Any]] = []
        for row in reader:
            total_rows += 1
            funder = _row_to_funder(row)
            if funder is None:
                continue
            target_rows += 1
            batch.append(funder)
            if len(batch) >= _BATCH_SIZE:
                upserted += _upsert_batch(batch, sb)
                batch = []
                if target_rows % 25000 == 0:
                    _cb(f"{region}: {target_rows} 501(c)(3)s processed so far")
        if batch:
            upserted += _upsert_batch(batch, sb)
        _cb(f"{region} done ({target_rows} 501(c)(3)s so far)")

    elapsed = round(time.time() - started, 1)
    stats = {
        "total_rows": total_rows,
        "target_rows": target_rows,
        "upserted": upserted,
        "errors": errors,
        "elapsed_seconds": elapsed,
    }
    logger.info("BMF import complete: %s", stats)

    try:
        from utils.discovery.config_store import update_import_timestamps
        update_import_timestamps(bmf_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.warning("Could not update BMF import timestamp: %s", exc)

    return stats


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="IRS BMF importer")
    parser.add_argument("--local", dest="local_dir", help="Directory holding eo1.csv..eo4.csv (skip download)")
    args = parser.parse_args()
    print(run_bmf_import(local_dir=args.local_dir))
