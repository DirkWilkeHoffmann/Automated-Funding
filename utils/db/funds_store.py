"""Supabase-backed fund storage.

Replaces utils/google_sheets.py. Provides a cached DataFrame view of the
funds table plus helpers for writing new records and querying processed URLs.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Set

import pandas as pd

from utils.constants import CSV_COLUMNS
from utils.db.client import get_supabase
from utils.utils_helpers import log_message, normalize_url

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_funds_cached() -> pd.DataFrame:
    try:
        response = (
            get_supabase()
            .table("funds")
            .select("*")
            .order("extraction_timestamp", desc=True)
            .execute()
        )
        rows = response.data or []
        df = pd.DataFrame(rows)
    except Exception as exc:
        log_message(f"Error loading funds from Supabase: {exc}", "error")
        df = pd.DataFrame(columns=CSV_COLUMNS)

    for col in CSV_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[CSV_COLUMNS]


def load_funds(force_refresh: bool = False) -> pd.DataFrame:
    """Return a defensive copy of all funds, optionally bypassing cache."""
    if force_refresh:
        _load_funds_cached.cache_clear()
        _get_processed_urls_cached.cache_clear()
    return _load_funds_cached().copy()


def clear_funds_cache() -> None:
    """Invalidate all in-process fund caches."""
    _load_funds_cached.cache_clear()
    _get_processed_urls_cached.cache_clear()


@lru_cache(maxsize=1)
def _get_processed_urls_cached() -> frozenset:
    df = _load_funds_cached()
    if "fund_url" in df.columns:
        return frozenset(
            normalize_url(u) for u in df["fund_url"].dropna().astype(str).tolist()
        )
    return frozenset()


def get_processed_urls(force_refresh: bool = False) -> Set[str]:
    """Return the set of already-processed (normalized) fund URLs."""
    if force_refresh:
        clear_funds_cache()
    return set(_get_processed_urls_cached())


def append_funds(rows: List[dict]) -> None:
    """Insert fund records into Supabase and invalidate cache."""
    if not rows:
        return
    valid_cols = set(CSV_COLUMNS)
    cleaned = [
        {k: (str(v) if v is not None else None) for k, v in row.items() if k in valid_cols}
        for row in rows
    ]
    try:
        get_supabase().table("funds").insert(cleaned).execute()
        clear_funds_cache()
    except Exception as exc:
        log_message(f"Failed to write funds to Supabase: {exc}", "error")
