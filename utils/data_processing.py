"""Data processing and results filtering utilities."""

import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, Set

import pandas as pd

from utils.constants import CSV_COLUMNS, SAVE_DIR
from utils.db.funds_store import (
    clear_funds_cache,
    get_processed_urls,
    load_funds,
)
from utils.utils_helpers import (
    canon_funder_url,
    log_message,
    normalize_url,
    parse_extraction_timestamp,
    subtract_months,
)

logger = logging.getLogger(__name__)


def load_results_csv(force_refresh: bool = False) -> pd.DataFrame:
    """Load all fund results from Supabase. Returns a defensive copy."""
    return load_funds(force_refresh=force_refresh)


def clear_results_cache() -> None:
    """Invalidate cached fund results."""
    clear_funds_cache()


def get_already_processed_urls(force_refresh: bool = False) -> Set[str]:
    """Get the set of already-processed (normalized) fund URLs."""
    return get_processed_urls(force_refresh=force_refresh)


@lru_cache(maxsize=4)
def _get_scraped_domains_cached(save_dir: str) -> Set[str]:
    """Internal cached lookup of scraped domains."""
    if not os.path.exists(save_dir):
        return set()
    scraped = set()
    for item in os.listdir(save_dir):
        item_path = os.path.join(save_dir, item)
        if os.path.isdir(item_path):
            scraped.add(item.lower())
    return scraped


def get_scraped_domains(save_dir: str = SAVE_DIR, force_refresh: bool = False) -> Set[str]:
    """Get the set of domains that have been scraped."""
    if force_refresh:
        _get_scraped_domains_cached.cache_clear()
    return set(_get_scraped_domains_cached(save_dir))


def clear_scraped_domains_cache() -> None:
    """Clear cached scraped-domain lookups."""
    _get_scraped_domains_cached.cache_clear()


def latest_results_by_key(df: pd.DataFrame, *, key_func: Callable[[str], str]) -> pd.DataFrame:
    """Return the most recent row per key_func(url) based on extraction_timestamp."""
    if df is None:
        return pd.DataFrame(columns=CSV_COLUMNS)
    if df.empty or "fund_url" not in df.columns:
        return df.copy()

    working = df.copy()
    working["_row_order"] = range(len(working))
    working["_result_key"] = (
        working["fund_url"]
        .fillna("")
        .astype(str)
        .str.strip()
        .apply(lambda u: key_func(u) if u else "")
    )
    if "extraction_timestamp" in working.columns:
        parsed = pd.to_datetime(
            working["extraction_timestamp"].apply(parse_extraction_timestamp), errors="coerce"
        )
    else:
        parsed = pd.Series(pd.NaT, index=working.index)
    working["_parsed_ts"] = parsed
    # Use a stable sort and keep NaT first so bad/missing timestamps don't
    # override valid newer rows for the same URL key.
    working = working.sort_values(
        by=["_result_key", "_parsed_ts", "_row_order"],
        kind="mergesort",
        na_position="first",
    )
    latest = working.drop_duplicates(subset="_result_key", keep="last")
    latest = latest.drop(columns=["_result_key", "_parsed_ts", "_row_order"])
    return latest


def stale_results_by_key(
    df: pd.DataFrame, *, months: int = 3, key_func: Callable[[str], str]
) -> pd.DataFrame:
    """Return latest rows that are older than the month cutoff (or have no timestamp)."""
    latest = latest_results_by_key(df, key_func=key_func)
    if latest.empty:
        return latest
    parsed = (
        pd.to_datetime(
            latest["extraction_timestamp"].apply(parse_extraction_timestamp), errors="coerce"
        )
        if "extraction_timestamp" in latest.columns
        else pd.Series(pd.NaT, index=latest.index)
    )
    cutoff = subtract_months(datetime.now(), months)
    stale_mask = parsed.isna() | (parsed < cutoff)
    return latest.loc[stale_mask].copy()


def latest_results_by_url(df: pd.DataFrame) -> pd.DataFrame:
    """Latest results using normalized URLs for grouping."""
    return latest_results_by_key(df, key_func=normalize_url)


def latest_results_by_canon_url(df: pd.DataFrame) -> pd.DataFrame:
    """Latest results using canonical funder URLs for grouping."""
    return latest_results_by_key(df, key_func=canon_funder_url)


def stale_results_by_url(df: pd.DataFrame, *, months: int = 3) -> pd.DataFrame:
    """Stale results using normalized URLs for grouping."""
    return stale_results_by_key(df, months=months, key_func=normalize_url)


def stale_results_by_canon_url(df: pd.DataFrame, *, months: int = 3) -> pd.DataFrame:
    """Stale results using canonical funder URLs for grouping."""
    return stale_results_by_key(df, months=months, key_func=canon_funder_url)


def load_text_from_folder(folder_path: str) -> tuple[str, int, str]:
    """Load all text files from a folder and combine them."""
    txt_files = list(Path(folder_path).glob("*.txt"))
    if not txt_files:
        return "", 0, ""
    combined_text = []
    fund_url = ""
    txt_files.sort()
    for txt_file in txt_files:
        try:
            with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                combined_text.append(f"\n=== {txt_file.name} ===\n{content}")
                if not fund_url and "_" in txt_file.name:
                    domain = txt_file.name.split("_")[0]
                    fund_url = f"https://{domain}"
        except Exception as e:
            log_message(f"Could not read {txt_file}: {e}", "warning")
            continue
    full_text = "\n".join(combined_text)
    return full_text, len(txt_files), fund_url
