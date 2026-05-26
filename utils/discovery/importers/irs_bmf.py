"""IRS Exempt Organizations Business Master File (BMF) importer.

Downloads all 4 regional CSV files from irs.gov, filters to private
non-operating foundations (FOUNDATION='04'), and upserts into the
discovery_funders table.

Runs monthly via APScheduler. Can also be triggered manually via
POST /discovery/import/bmf.

IRS BMF docs:
  https://www.irs.gov/charities-non-profits/exempt-organizations-business-master-file-extract-eo-bmf

FOUNDATION code '04' = private non-operating foundation — these must
distribute at least 5% of assets annually as grants, making them the
primary target for grant-seeking nonprofits.
"""

from __future__ import annotations

import csv
import io
import logging
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

_PRIVATE_FOUNDATION_CODES = {"04"}  # non-operating private foundations (must distribute 5%+ annually)

_ASSET_CODE_FIELD = "ASSET_CD"
_INCOME_CODE_FIELD = "INCOME_CD"

_HEADERS = {"User-Agent": "automated-funding-bot/1.0 (grant discovery; contact wilkehoffmann@gmail.com)"}

_BATCH_SIZE = 500  # upsert rows in batches to avoid payload limits


def _parse_int(val: str) -> Optional[int]:
    try:
        return int(val) if val and val.strip() else None
    except (ValueError, TypeError):
        return None


def _parse_bigint(val: str) -> Optional[int]:
    try:
        return int(float(val)) if val and val.strip() else None
    except (ValueError, TypeError):
        return None


def _row_to_funder(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Convert a BMF CSV row to a discovery_funders record. Returns None if not a target foundation."""
    foundation_code = row.get("FOUNDATION", "").strip()
    if foundation_code not in _PRIVATE_FOUNDATION_CODES:
        return None

    ein = row.get("EIN", "").strip()
    if not ein:
        return None

    return {
        "ein": ein,
        "name": (row.get("NAME") or "").strip(),
        "city": (row.get("CITY") or "").strip() or None,
        "state": (row.get("STATE") or "").strip() or None,
        "zip": (row.get("ZIP") or "").strip() or None,
        "ntee_code": (row.get("NTEE_CD") or "").strip() or None,
        "foundation_type": foundation_code,
        "asset_code": _parse_int(row.get(_ASSET_CODE_FIELD, "")),
        "asset_amount": _parse_bigint(row.get("ASSET_AMT", "")),
        "income_amount": _parse_bigint(row.get("INCOME_AMT", "")),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _upsert_batch(batch: List[Dict[str, Any]], sb) -> int:
    """Upsert a batch of funder records. Returns number of rows upserted."""
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


def run_bmf_import(
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Download IRS BMF, filter to private foundations, upsert to discovery_funders.

    Returns stats dict: { total_rows, foundations_found, upserted, errors, elapsed_seconds }
    """
    from supabase import create_client
    from utils.config import get_settings
    _s = get_settings()
    sb = create_client(_s.supabase_url, _s.supabase_service_key)

    started = time.time()
    total_rows = 0
    foundations_found = 0
    upserted = 0
    errors = 0

    def _cb(msg: str) -> None:
        logger.info("BMF import: %s", msg)
        if progress_cb:
            try:
                progress_cb({"message": msg, "upserted": upserted, "foundations_found": foundations_found})
            except Exception:
                pass

    for url in _BMF_URLS:
        region = url.split("/")[-1].replace(".csv", "")
        _cb(f"downloading {region}")
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=120, stream=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("BMF download failed for %s: %s", url, exc)
            errors += 1
            continue

        # Stream-parse the CSV to avoid loading the whole file into memory
        batch: List[Dict[str, Any]] = []
        content = resp.content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            total_rows += 1
            funder = _row_to_funder(row)
            if funder is None:
                continue
            foundations_found += 1
            batch.append(funder)
            if len(batch) >= _BATCH_SIZE:
                upserted += _upsert_batch(batch, sb)
                batch = []
                if foundations_found % 5000 == 0:
                    _cb(f"{region}: {foundations_found} foundations processed so far")

        if batch:
            upserted += _upsert_batch(batch, sb)

        _cb(f"{region} done ({foundations_found} foundations so far)")

    elapsed = round(time.time() - started, 1)
    stats = {
        "total_rows": total_rows,
        "foundations_found": foundations_found,
        "upserted": upserted,
        "errors": errors,
        "elapsed_seconds": elapsed,
    }
    logger.info("BMF import complete: %s", stats)

    # Record import timestamp in discovery_config
    try:
        from utils.discovery.config_store import update_import_timestamps
        update_import_timestamps(bmf_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.warning("Could not update BMF import timestamp: %s", exc)

    return stats
