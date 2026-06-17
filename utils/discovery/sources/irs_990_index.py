"""IRS 990 annual e-file index — EIN ↔ batch ZIP lookup.

The IRS publishes Form 990 XML filings as ~50 ZIPs per submission year (one
batch per ~thousands of filings) at:
  https://apps.irs.gov/pub/epostcard/990/xml/{year}/{year}_TEOS_XML_NNA.zip

A companion index CSV at:
  https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv
maps each filing's EIN to its object_id and the ZIP batch it lives in.

We cache the index in Supabase (table irs_990_index) so EIN lookups become
O(1) instead of re-downloading 90MB of CSV per run. The index is refreshed
weekly per submission_year.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests

from utils.db.client import get_supabase

logger = logging.getLogger(__name__)

_INDEX_URL = "https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/octet-stream",
}
_REFRESH_TTL_DAYS = 7
_UPSERT_CHUNK = 1000


def _refresh_age_days(submission_year: int) -> Optional[float]:
    try:
        rows = (
            get_supabase()
            .table("irs_990_index_refresh")
            .select("refreshed_at")
            .eq("submission_year", submission_year)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            return None
        refreshed = datetime.fromisoformat(rows[0]["refreshed_at"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - refreshed).total_seconds() / 86400
    except Exception as exc:
        logger.warning("irs_990_index_refresh lookup failed for %s: %s", submission_year, exc)
        return None


def _mark_refreshed(submission_year: int, row_count: int) -> None:
    try:
        get_supabase().table("irs_990_index_refresh").upsert({
            "submission_year": submission_year,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "row_count": row_count,
        }).execute()
    except Exception as exc:
        logger.warning("Could not mark irs_990_index_refresh: %s", exc)


def _stream_index(
    submission_year: int,
    *,
    local_dir: Optional[str] = None,
) -> Iterable[Dict[str, Any]]:
    """Stream rows from the IRS year index CSV.

    The file is ~90MB; we stream-parse to avoid loading it all into memory.

    When `local_dir` is set, reads `index_{year}.csv` (or `irs_990_index_{year}.csv`
    as named by our analysis script) from that directory instead of downloading.
    """
    if local_dir:
        for candidate in (
            os.path.join(local_dir, f"index_{submission_year}.csv"),
            os.path.join(local_dir, f"irs_990_index_{submission_year}.csv"),
        ):
            if os.path.isfile(candidate):
                logger.info("Reading IRS index from local file %s", candidate)
                with open(candidate, encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        yield row
                return
        logger.warning("IRS index local file not found for year %s in %s", submission_year, local_dir)
        return

    url = _INDEX_URL.format(year=submission_year)
    logger.info("Fetching IRS index for submission_year=%s", submission_year)
    with requests.get(url, headers=_HEADERS, stream=True, timeout=180) as resp:
        resp.raise_for_status()
        line_iter = resp.iter_lines(decode_unicode=True)
        reader = csv.DictReader(line_iter)
        for row in reader:
            yield row


def refresh_index_for_year(
    submission_year: int,
    *,
    force: bool = False,
    local_dir: Optional[str] = None,
) -> int:
    """Download + persist the IRS index for `submission_year`. Returns row count.

    Skips download if a refresh has happened within REFRESH_TTL_DAYS unless
    force=True. Upserts in chunks to avoid huge single POSTs to Supabase.

    Args:
        submission_year: e.g. 2024
        force:           skip TTL check
        local_dir:       if set, read from local index_{year}.csv instead of downloading
    """
    age = _refresh_age_days(submission_year)
    if not force and not local_dir and age is not None and age < _REFRESH_TTL_DAYS:
        logger.info(
            "IRS index for %s already fresh (refreshed %.1f days ago)",
            submission_year, age,
        )
        return 0

    pending: List[Dict[str, Any]] = []
    total = 0
    seen_ein_year: set = set()

    for row in _stream_index(submission_year, local_dir=local_dir):
        ein = (row.get("EIN") or "").strip()
        if not ein:
            continue
        tax_period = (row.get("TAX_PERIOD") or "").strip()
        if not tax_period:
            continue
        # tax_period format: YYYYMM (e.g. 202312)
        try:
            tax_year = int(tax_period[:4])
        except ValueError:
            continue

        key = (ein, tax_year)
        if key in seen_ein_year:
            continue  # one row per ein+year (skip 990T/etc. follow-ups)
        seen_ein_year.add(key)

        pending.append({
            "ein": ein,
            "tax_year": tax_year,
            "object_id": (row.get("OBJECT_ID") or "").strip(),
            "batch_zip": (row.get("XML_BATCH_ID") or "").strip(),
            "return_type": (row.get("RETURN_TYPE") or "").strip(),
            "tax_period": tax_period,
            "submission_year": submission_year,
            "taxpayer_name": (row.get("TAXPAYER_NAME") or "").strip()[:200],
        })

        if len(pending) >= _UPSERT_CHUNK:
            total += _bulk_upsert(pending)
            pending = []
            if total and total % 10000 == 0:
                logger.info("  IRS index %s: %d rows ingested", submission_year, total)

    if pending:
        total += _bulk_upsert(pending)

    _mark_refreshed(submission_year, total)
    # Also stamp the discovery_config.import_config so the admin UI can show
    # a single "Last refreshed" per dataset alongside BMF / Grants.gov / SAM.
    try:
        from utils.discovery.config_store import update_import_timestamps
        update_import_timestamps(irs_990_index_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.warning("Could not update 990 index import timestamp: %s", exc)
    logger.info("IRS index %s refresh complete: %d rows", submission_year, total)
    return total


def _bulk_upsert(rows: List[Dict[str, Any]]) -> int:
    """Upsert a batch. Returns rows actually persisted (0 on failure)."""
    try:
        get_supabase().table("irs_990_index").upsert(
            rows, on_conflict="ein,tax_year"
        ).execute()
        return len(rows)
    except Exception as exc:
        logger.warning("irs_990_index upsert failed (%d rows): %s", len(rows), exc)
        return 0


def lookup_filing(ein: str, *, max_age_years: int = 3) -> Optional[Dict[str, Any]]:
    """Return the most recent filing record we have for an EIN, or None.

    Filters out filings older than `max_age_years` (in tax_year). Falls back
    to the unfiltered most-recent if no rows pass the filter.
    """
    if not ein:
        return None
    ein = ein.strip()
    try:
        rows = (
            get_supabase()
            .table("irs_990_index")
            .select("*")
            .eq("ein", ein)
            .order("tax_year", desc=True)
            .limit(5)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.warning("irs_990_index lookup failed for ein=%s: %s", ein, exc)
        return None

    if not rows:
        return None
    cutoff_year = datetime.now(timezone.utc).year - max_age_years
    for r in rows:
        if int(r.get("tax_year") or 0) >= cutoff_year:
            return r
    return rows[0]  # fall back to most recent regardless of age


_bg_refresh_threads: Dict[int, "threading.Thread"] = {}
_bg_refresh_lock = "_bg_refresh_lock"


def ensure_recent_indexes(years_back: int = 2, *, blocking: bool = False) -> None:
    """Best-effort: refresh the most recent annual IRS indexes.

    By default, fire-and-forget — a 700k-row ingest takes 5-10 minutes and
    must NOT block a live discovery run. Discovery proceeds with whatever
    index rows are already cached in Supabase; the background refresh keeps
    them up to date over time.

    Pass blocking=True for the one-time bootstrap or for an admin endpoint.
    """
    import threading
    current_year = datetime.now(timezone.utc).year
    years = list(range(current_year - years_back, current_year + 1))

    if blocking:
        for year in years:
            try:
                refresh_index_for_year(year)
            except Exception as exc:
                logger.warning("Could not refresh IRS index for %s: %s", year, exc)
        return

    for year in years:
        # Skip if already fresh (cheap DB check)
        if _refresh_age_days(year) is not None and _refresh_age_days(year) < _REFRESH_TTL_DAYS:
            continue
        # Skip if a background refresh for this year is already in flight
        existing = _bg_refresh_threads.get(year)
        if existing and existing.is_alive():
            continue

        def _refresh(y: int = year) -> None:
            try:
                refresh_index_for_year(y)
            except Exception as exc:
                logger.warning("Background IRS index refresh for %s failed: %s", y, exc)

        t = threading.Thread(target=_refresh, name=f"irs-idx-refresh-{year}", daemon=True)
        _bg_refresh_threads[year] = t
        t.start()
        logger.info("Kicked off background IRS index refresh for %s", year)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="IRS 990 index importer")
    parser.add_argument("--year", type=int, help="Single submission year (e.g. 2024)")
    parser.add_argument("--years-back", type=int, default=2,
                        help="Refresh the last N+1 years (default 2 → current + 2 prior)")
    parser.add_argument("--local", dest="local_dir",
                        help="Directory holding index_{year}.csv files (skip download)")
    parser.add_argument("--force", action="store_true", help="Skip TTL check")
    args = parser.parse_args()
    if args.year:
        print(refresh_index_for_year(args.year, force=args.force, local_dir=args.local_dir))
    else:
        current_year = datetime.now(timezone.utc).year
        for y in range(current_year - args.years_back, current_year + 1):
            print(f"--- {y} ---")
            print(refresh_index_for_year(y, force=args.force, local_dir=args.local_dir))
