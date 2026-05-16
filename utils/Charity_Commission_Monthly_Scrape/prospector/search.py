"""Search and filter logic for grant prospector."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Set

from .sources import get_charity_id, iter_json_array


def coerce_int(value: Any) -> Optional[int]:
    """Coerce a value to integer."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def coerce_float(value: Any) -> Optional[float]:
    """Coerce a value to float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def is_trueish(value: Any) -> bool:
    """Check if value is truthy in a relaxed way."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return False


def is_null_like(value: Any) -> bool:
    """Check if value is null or null-like."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().upper() in {"", "NULL"}
    return False


def parse_iso_date(value: Any) -> Optional[date]:
    """Parse ISO date string."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text.split("T", 1)[0])
        except ValueError:
            return None
    return None


def build_active_charity_set(charity_file: Path) -> Set[int]:
    """Build set of active charities (not removed)."""
    active_charities: Set[int] = set()
    for row in iter_json_array(charity_file):
        charity_id = get_charity_id(row)
        if charity_id is None:
            continue
        if is_null_like(row.get("date_of_removal")):
            active_charities.add(charity_id)
    return active_charities


def build_recent_submission_charity_set(
    history_file: Path, window_days: int
) -> tuple[Set[int], Optional[date], int]:
    """Build set of charities with recent submissions."""
    in_date_charities: Set[int] = set()
    extract_date: Optional[date] = None
    cutoff_date: Optional[date] = None
    source_rows = 0

    for row in iter_json_array(history_file):
        source_rows += 1
        if extract_date is None:
            extract_date = parse_iso_date(row.get("date_of_extract"))
            if extract_date is not None:
                cutoff_date = extract_date - timedelta(days=window_days)

        if cutoff_date is None:
            continue

        charity_id = get_charity_id(row)
        if charity_id is None:
            continue

        annual_return_date = parse_iso_date(row.get("date_annual_return_received"))
        accounts_date = parse_iso_date(row.get("date_accounts_received"))
        latest_submission_date = max(
            (d for d in (annual_return_date, accounts_date) if d is not None),
            default=None,
        )

        if latest_submission_date is not None and latest_submission_date >= cutoff_date:
            in_date_charities.add(charity_id)

    return in_date_charities, extract_date, source_rows


def build_history_income_charity_set(
    history_file: Path, minimum_income: float
) -> tuple[Set[int], int]:
    """Build set of charities meeting minimum income threshold."""
    income_charities: Set[int] = set()
    source_rows = 0

    for row in iter_json_array(history_file):
        source_rows += 1
        charity_id = get_charity_id(row)
        if charity_id is None:
            continue

        total_gross_income = coerce_float(row.get("total_gross_income"))
        if total_gross_income is None:
            continue

        if total_gross_income >= minimum_income:
            income_charities.add(charity_id)

    return income_charities, source_rows


def build_area_filtered_charity_set(
    area_file: Path, wanted_areas: Set[str]
) -> tuple[Set[int], int]:
    """Build set of charities in selected geographic areas."""
    area_charities: Set[int] = set()
    source_rows = 0
    wanted_lookup = {name.casefold() for name in wanted_areas}

    for row in iter_json_array(area_file):
        source_rows += 1
        description = row.get("geographic_area_description")
        if not isinstance(description, str):
            continue
        if description.strip().casefold() not in wanted_lookup:
            continue

        charity_id = get_charity_id(row)
        if charity_id is None:
            continue
        area_charities.add(charity_id)

    return area_charities, source_rows


def build_partb_filtered_charity_set(partb_file: Path) -> tuple[Set[int], int]:
    """Build set of charities with positive grants expenditure."""
    grants_positive_charities: Set[int] = set()
    source_rows = 0

    for row in iter_json_array(partb_file):
        source_rows += 1
        charity_id = get_charity_id(row)
        if charity_id is None:
            continue

        grants_institution = coerce_float(row.get("expenditure_grants_institution"))
        if grants_institution is None:
            continue

        if grants_institution > 0:
            grants_positive_charities.add(charity_id)

    return grants_positive_charities, source_rows


def verify_unique_charity_ids(output_file: Path) -> int:
    """Verify output file has unique charity IDs."""
    seen: Set[int] = set()
    duplicates = 0
    for row in iter_json_array(output_file):
        charity_id = get_charity_id(row)
        if charity_id is None:
            continue
        if charity_id in seen:
            duplicates += 1
        else:
            seen.add(charity_id)
    return duplicates
