"""Data transformation and formatting functions for the grant pipeline."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def utc_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def first_non_empty_text(value: Any) -> str:
    """Extract first non-empty text from mixed input."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def build_funds_snapshot(
    merged_csv_path: Path,
    run_id: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    """Build the funds snapshot from the merged CSV output."""
    try:
        df = pd.read_csv(merged_csv_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to read merged CSV: {exc}")

    charity_count = len(df)
    grant_count = df["grant_counts"].sum() if "grant_counts" in df.columns else 0
    total_funding = df["total_awarded"].sum() if "total_awarded" in df.columns else 0.0

    source_extract_date = first_non_empty_text(
        df["source_extract_date"].iloc[0] if "source_extract_date" in df.columns else ""
    )
    source_extract_month = first_non_empty_text(
        df["source_extract_month"].iloc[0] if "source_extract_month" in df.columns else ""
    )

    return {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at_utc": generated_at_utc,
        "charity_count": int(charity_count),
        "grant_count": int(grant_count),
        "total_funding": float(total_funding),
        "source_extract_date": source_extract_date,
        "source_extract_month": source_extract_month,
        "sample_charities": df.head(5).to_dict(orient="records")
        if len(df) > 0
        else [],
    }


def calculate_monthly_delta(
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any],
    run_id: str,
    run_started_utc: str,
    previous_run_id: str = "",
    absolute_threshold: float = 50_000.0,
    percent_threshold: float = 0.20,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Calculate delta between current and previous snapshots."""
    current_charities = current_snapshot.get("charity_count", 0)
    previous_charities = previous_snapshot.get("charity_count", 0)
    current_grant_count = current_snapshot.get("grant_count", 0)
    previous_grant_count = previous_snapshot.get("grant_count", 0)
    current_funding = current_snapshot.get("total_funding", 0.0)
    previous_funding = previous_snapshot.get("total_funding", 0.0)

    charity_delta = current_charities - previous_charities
    grant_delta = current_grant_count - previous_grant_count
    funding_delta = current_funding - previous_funding

    is_significant = False
    reasons: list[str] = []
    if abs(funding_delta) >= absolute_threshold:
        is_significant = True
        reasons.append(f"funding_delta_abs={funding_delta:,.2f} >= {absolute_threshold:,.2f}")
    if (
        previous_funding > 0
        and abs(funding_delta / previous_funding) >= percent_threshold
    ):
        is_significant = True
        pct = (funding_delta / previous_funding) * 100
        reasons.append(f"funding_delta_pct={pct:.1f}% >= {percent_threshold*100:.1f}%")

    to_scrape_rows = []
    if is_significant or not previous_snapshot:
        for sample in current_snapshot.get("sample_charities", []):
            to_scrape_rows.append(
                {
                    "charity_number": str(sample.get("charity_number", "")),
                    "name": str(sample.get("name", "")),
                    "reason": "new_baseline" if not previous_snapshot else "significant_change",
                    "run_id": run_id,
                }
            )

    delta_payload = {
        "schema_version": 1,
        "run_id": run_id,
        "run_started_utc": run_started_utc,
        "previous_run_id": previous_run_id,
        "is_significant": bool(is_significant),
        "significance_reasons": reasons,
        "deltas": {
            "charities": int(charity_delta),
            "grants": int(grant_delta),
            "funding": float(funding_delta),
        },
        "previous_values": {
            "charities": int(previous_charities),
            "grants": int(previous_grant_count),
            "funding": float(previous_funding),
        },
        "current_values": {
            "charities": int(current_charities),
            "grants": int(current_grant_count),
            "funding": float(current_funding),
        },
        "counts": {
            "to_scrape_charities": len(to_scrape_rows),
        },
    }
    return delta_payload, to_scrape_rows
