"""Grant prospector module with backwards-compatible re-exports."""

from .ranking import (
    analyze_cross_file_overlap,
    build_merged_charities,
    calculate_percentages,
    print_filter_report,
    print_results_report,
)
from .search import (
    build_active_charity_set,
    build_area_filtered_charity_set,
    build_history_income_charity_set,
    build_partb_filtered_charity_set,
    build_recent_submission_charity_set,
    coerce_float,
    coerce_int,
    is_null_like,
    is_trueish,
    parse_iso_date,
    verify_unique_charity_ids,
)
from .sources import (
    FilterResult,
    collect_rows_for_charities,
    filter_source_to_output,
    get_charity_id,
    iter_json_array,
    write_json_array,
    write_json_object,
    write_merged_csv,
)

__all__ = [
    # ranking
    "calculate_percentages",
    "analyze_cross_file_overlap",
    "build_merged_charities",
    "print_filter_report",
    "print_results_report",
    # search
    "coerce_int",
    "coerce_float",
    "is_trueish",
    "is_null_like",
    "parse_iso_date",
    "build_active_charity_set",
    "build_recent_submission_charity_set",
    "build_history_income_charity_set",
    "build_area_filtered_charity_set",
    "build_partb_filtered_charity_set",
    "verify_unique_charity_ids",
    # sources
    "FilterResult",
    "get_charity_id",
    "iter_json_array",
    "write_json_array",
    "write_json_object",
    "collect_rows_for_charities",
    "filter_source_to_output",
    "write_merged_csv",
]
