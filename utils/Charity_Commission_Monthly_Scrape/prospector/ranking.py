"""Ranking and analysis logic for grant prospector."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Set


def calculate_percentages(numerator: int, denominator: int) -> float:
    """Calculate percentage, handling zero denominator."""
    if denominator == 0:
        return 0.0
    return (numerator / denominator) * 100


def analyze_cross_file_overlap(
    annual_charity_ids: Set[int],
    classification_charity_ids: Set[int],
) -> tuple[Dict[str, Any], Set[int]]:
    """Analyze overlap between annual return and classification files."""
    overlap = annual_charity_ids & classification_charity_ids
    only_annual = annual_charity_ids - classification_charity_ids
    only_classification = classification_charity_ids - annual_charity_ids
    union_ids = annual_charity_ids | classification_charity_ids
    only_one_file_total = len(only_annual) + len(only_classification)
    either_file_total = len(overlap) + only_one_file_total

    comparison_payload = {
        "counts": {
            "in_both_files": len(overlap),
            "only_in_annual_return_file": len(only_annual),
            "only_in_classification_file": len(only_classification),
            "in_either_file_total": len(union_ids),
        },
        "charity_ids": {
            "in_both_files": sorted(overlap),
            "only_in_annual_return_file": sorted(only_annual),
            "only_in_classification_file": sorted(only_classification),
        },
    }

    return comparison_payload, union_ids


def build_merged_charities(
    union_ids: Set[int],
    overlap: Set[int],
    only_annual: Set[int],
    only_classification: Set[int],
    annual_filtered_rows: Dict[int, list[Dict[str, Any]]],
    classification_filtered_rows: Dict[int, list[Dict[str, Any]]],
    charity_rows: Dict[int, list[Dict[str, Any]]],
    area_rows: Dict[int, list[Dict[str, Any]]],
    classification_rows: Dict[int, list[Dict[str, Any]]],
    history_rows_by_charity: Dict[int, list[Dict[str, Any]]],
    parta_rows: Dict[int, list[Dict[str, Any]]],
    partb_rows: Dict[int, list[Dict[str, Any]]],
) -> list[Dict[str, Any]]:
    """Build merged charity data with segment classification."""
    merged_charities: list[Dict[str, Any]] = []
    for charity_id in sorted(union_ids):
        if charity_id in overlap:
            segment = "in_both_files"
        elif charity_id in only_annual:
            segment = "only_in_annual_return_file"
        else:
            segment = "only_in_classification_file"

        merged_charities.append(
            {
                "registered_charity_number": charity_id,
                "segment": segment,
                "matched_rows": {
                    "annual_return_filtered": annual_filtered_rows.get(charity_id, []),
                    "classification_filtered": classification_filtered_rows.get(charity_id, []),
                },
                "charity": charity_rows.get(charity_id, []),
                "area_of_operation": area_rows.get(charity_id, []),
                "classification_all_rows": classification_rows.get(charity_id, []),
                "annual_return_history": history_rows_by_charity.get(charity_id, []),
                "annual_return_parta": parta_rows.get(charity_id, []),
                "annual_return_partb": partb_rows.get(charity_id, []),
            }
        )

    return merged_charities


def print_filter_report(
    active_charities_count: int,
    in_date_charities_count: int,
    eligible_after_recent: int,
    history_income_charities_count: int,
    eligible_after_history_income: int,
    area_charities_count: int,
    eligible_after_area: int,
    partb_grants_positive_charities_count: int,
    eligible_charities_count: int,
    history_rows: int,
    history_income_rows: int,
    area_rows: int,
    partb_rows: int,
    recent_window_days: int,
    min_history_income: float,
    cutoff_date_str: str,
    extract_date_str: str,
) -> None:
    """Print detailed filter report."""
    print(f"Active charities found (date_of_removal is NULL): {active_charities_count:,}")
    print(
        "Charities with at least one submission in the last "
        f"{recent_window_days} days "
        f"(from {cutoff_date_str} to {extract_date_str}): "
        f"{in_date_charities_count:,}"
    )
    print("After AND filter (active + recent submission): " f"{eligible_after_recent:,}")
    print(
        f"Charities with total_gross_income >= {min_history_income:,.0f} "
        f"(history): {history_income_charities_count:,}"
    )
    print(
        "After AND filter (+ history total_gross_income >= 250,000): "
        f"{eligible_after_history_income:,}"
    )
    print("Charities in selected geographic areas: " f"{area_charities_count:,}")
    print("After AND filter (+ selected area): " f"{eligible_after_area:,}")
    print(
        "Charities with expenditure_grants_institution > 0 (partb): "
        f"{partb_grants_positive_charities_count:,}"
    )
    print("After AND filter (+ partb grants condition): " f"{eligible_charities_count:,}")
    print(f"Annual return history rows scanned: {history_rows:,}")
    print(f"Annual return history rows scanned (income check): {history_income_rows:,}")
    print(f"Area of operation rows scanned: {area_rows:,}")
    print(f"Annual return partb rows scanned: {partb_rows:,}")


def print_results_report(
    annual_result_written_rows: int,
    classification_result_written_rows: int,
    overlap_count: int,
    only_annual_count: int,
    only_classification_count: int,
    union_ids_count: int,
    only_one_file_total: int,
    either_file_total: int,
    annual_duplicates: int,
    classification_duplicates: int,
    comparison_output_name: str,
    merged_output_name: str,
) -> None:
    """Print results and comparison report."""
    print()
    print("Saved files:")
    print(f"- grant_making_main_activity_active.json")
    print(f"- grant_making_classification_302_active.json")
    print()
    print("Counts after filtering to all AND conditions:")
    print(f"- Annual return (grant_making_is_main_activity = True): {annual_result_written_rows:,}")
    print(
        "- Classification (classification_code = 302): " f"{classification_result_written_rows:,}"
    )
    print(
        "- Count difference (classification - annual): "
        f"{classification_result_written_rows - annual_result_written_rows:,}"
    )
    print()
    print("Cross-file comparison by charity id:")
    print(f"- In both files: {overlap_count:,}")
    print(f"- Only in annual return file: {only_annual_count:,}")
    print(f"- Only in classification file: {only_classification_count:,}")
    print()
    print("Percentages:")
    print(
        "- Annual-only as % of all charities found in either file: "
        f"{calculate_percentages(only_annual_count, either_file_total):.2f}%"
    )
    print(
        "- Classification-only as % of all charities found in either file: "
        f"{calculate_percentages(only_classification_count, either_file_total):.2f}%"
    )
    print(
        "- In both as % of all charities found in either file: "
        f"{calculate_percentages(overlap_count, either_file_total):.2f}%"
    )
    print(
        "- Annual-only as % of charities that appear in only one file: "
        f"{calculate_percentages(only_annual_count, only_one_file_total):.2f}%"
    )
    print(
        "- Classification-only as % of charities that appear in only one file: "
        f"{calculate_percentages(only_classification_count, only_one_file_total):.2f}%"
    )
    print(
        "- Annual-only as % of annual file: "
        f"{calculate_percentages(only_annual_count, annual_result_written_rows):.2f}%"
    )
    print(
        "- Classification-only as % of classification file: "
        f"{calculate_percentages(only_classification_count, classification_result_written_rows):.2f}%"
    )
    print()
    print("Uniqueness checks (charity ids):")
    print(
        "- Annual return output unique: "
        f"{'YES' if annual_duplicates == 0 else f'NO ({annual_duplicates} duplicates)'}"
    )
    print(
        "- Classification output unique: "
        f"{'YES' if classification_duplicates == 0 else f'NO ({classification_duplicates} duplicates)'}"
    )
    print()
    print(f"Saved cross-file comparison JSON: {comparison_output_name}")
    print(f"Saved merged detailed CSV: {merged_output_name}")
