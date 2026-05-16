"""Grant making pipeline prospector - entry point."""

from datetime import date, timedelta
from pathlib import Path

from prospector import (
    analyze_cross_file_overlap,
    build_active_charity_set,
    build_area_filtered_charity_set,
    build_history_income_charity_set,
    build_merged_charities,
    build_partb_filtered_charity_set,
    build_recent_submission_charity_set,
    collect_rows_for_charities,
    coerce_int,
    filter_source_to_output,
    is_trueish,
    print_filter_report,
    print_results_report,
    verify_unique_charity_ids,
    write_json_object,
    write_merged_csv,
)

BASE_DIR = Path(__file__).resolve().parent

CHARITY_FILE = BASE_DIR / "input/publicextract.charity.json"
ANNUAL_RETURN_FILE = BASE_DIR / "input/publicextract.charity_annual_return_parta.json"
CLASSIFICATION_FILE = BASE_DIR / "input/publicextract.charity_classification.json"
ANNUAL_RETURN_HISTORY_FILE = BASE_DIR / "input/publicextract.charity_annual_return_history.json"
AREA_OF_OPERATION_FILE = BASE_DIR / "input/publicextract.charity_area_of_operation.json"
ANNUAL_RETURN_PARTB_FILE = BASE_DIR / "input/publicextract.charity_annual_return_partb.json"

ANNUAL_RETURN_OUTPUT = BASE_DIR / "output/grant_making_main_activity_active.json"
CLASSIFICATION_OUTPUT = BASE_DIR / "output/grant_making_classification_302_active.json"
COMPARISON_OUTPUT = BASE_DIR / "output/grant_making_cross_file_comparison.json"
MERGED_OUTPUT = BASE_DIR / "output/grant_making_merged_detailed.csv"
CHARITY_DETAILS_URL_TEMPLATE = (
    "https://register-of-charities.charitycommission.gov.uk/en/charity-search/-/charity-details/"
    "{charity_number}?_uk_gov_ccew_onereg_charitydetails_web_portlet_CharityDetailsPortlet_organisationNumber="
    "{charity_number}"
)
RECENT_SUBMISSION_WINDOW_DAYS = 365
MIN_HISTORY_TOTAL_GROSS_INCOME = 250_000
GEOGRAPHICAL_AREAS_WANTED = {
    "Kent",
    "Medway",
    "Throughout London",
    "Throughout England",
    "Throughout England And Wales",
}


def main() -> None:
    """Run the grant prospector analysis."""
    active_charities = build_active_charity_set(CHARITY_FILE)
    in_date_charities, extract_date, history_rows = build_recent_submission_charity_set(
        ANNUAL_RETURN_HISTORY_FILE, RECENT_SUBMISSION_WINDOW_DAYS
    )
    history_income_charities, history_income_rows = build_history_income_charity_set(
        ANNUAL_RETURN_HISTORY_FILE, MIN_HISTORY_TOTAL_GROSS_INCOME
    )
    area_charities, area_rows = build_area_filtered_charity_set(
        AREA_OF_OPERATION_FILE, GEOGRAPHICAL_AREAS_WANTED
    )
    partb_grants_positive_charities, partb_rows = build_partb_filtered_charity_set(
        ANNUAL_RETURN_PARTB_FILE
    )

    eligible_after_recent = active_charities & in_date_charities
    eligible_after_history_income = eligible_after_recent & history_income_charities
    eligible_after_area = eligible_after_history_income & area_charities
    eligible_charities = eligible_after_area & partb_grants_positive_charities

    if extract_date is None:
        raise ValueError("Could not determine date_of_extract from annual return history file.")
    cutoff_date = extract_date - timedelta(days=RECENT_SUBMISSION_WINDOW_DAYS)

    print_filter_report(
        active_charities_count=len(active_charities),
        in_date_charities_count=len(in_date_charities),
        eligible_after_recent=len(eligible_after_recent),
        history_income_charities_count=len(history_income_charities),
        eligible_after_history_income=len(eligible_after_history_income),
        area_charities_count=len(area_charities),
        eligible_after_area=len(eligible_after_area),
        partb_grants_positive_charities_count=len(partb_grants_positive_charities),
        eligible_charities_count=len(eligible_charities),
        history_rows=history_rows,
        history_income_rows=history_income_rows,
        area_rows=area_rows,
        partb_rows=partb_rows,
        recent_window_days=RECENT_SUBMISSION_WINDOW_DAYS,
        min_history_income=MIN_HISTORY_TOTAL_GROSS_INCOME,
        cutoff_date_str=cutoff_date.isoformat(),
        extract_date_str=extract_date.isoformat(),
    )

    annual_result = filter_source_to_output(
        source_file=ANNUAL_RETURN_FILE,
        output_file=ANNUAL_RETURN_OUTPUT,
        active_charities=eligible_charities,
        predicate=lambda row: is_trueish(row.get("grant_making_is_main_activity")),
    )

    classification_result = filter_source_to_output(
        source_file=CLASSIFICATION_FILE,
        output_file=CLASSIFICATION_OUTPUT,
        active_charities=eligible_charities,
        predicate=lambda row: coerce_int(row.get("classification_code")) == 302,
    )

    annual_duplicates_in_output = verify_unique_charity_ids(ANNUAL_RETURN_OUTPUT)
    classification_duplicates_in_output = verify_unique_charity_ids(CLASSIFICATION_OUTPUT)

    comparison_payload, union_ids = analyze_cross_file_overlap(
        annual_result.charity_ids, classification_result.charity_ids
    )

    overlap = comparison_payload["counts"]["in_both_files"]
    only_annual = comparison_payload["counts"]["only_in_annual_return_file"]
    only_classification = comparison_payload["counts"]["only_in_classification_file"]
    either_file_total = comparison_payload["counts"]["in_either_file_total"]
    only_one_file_total = only_annual + only_classification

    print_results_report(
        annual_result_written_rows=annual_result.written_rows,
        classification_result_written_rows=classification_result.written_rows,
        overlap_count=overlap,
        only_annual_count=only_annual,
        only_classification_count=only_classification,
        union_ids_count=len(union_ids),
        only_one_file_total=only_one_file_total,
        either_file_total=either_file_total,
        annual_duplicates=annual_duplicates_in_output,
        classification_duplicates=classification_duplicates_in_output,
        comparison_output_name=COMPARISON_OUTPUT.name,
        merged_output_name=MERGED_OUTPUT.name,
    )

    write_json_object(COMPARISON_OUTPUT, comparison_payload)

    charity_rows = collect_rows_for_charities(CHARITY_FILE, union_ids)
    area_rows_dict = collect_rows_for_charities(AREA_OF_OPERATION_FILE, union_ids)
    classification_rows = collect_rows_for_charities(CLASSIFICATION_FILE, union_ids)
    history_rows_by_charity = collect_rows_for_charities(ANNUAL_RETURN_HISTORY_FILE, union_ids)
    parta_rows = collect_rows_for_charities(ANNUAL_RETURN_FILE, union_ids)
    partb_rows_dict = collect_rows_for_charities(ANNUAL_RETURN_PARTB_FILE, union_ids)
    annual_filtered_rows = collect_rows_for_charities(ANNUAL_RETURN_OUTPUT, union_ids)
    classification_filtered_rows = collect_rows_for_charities(CLASSIFICATION_OUTPUT, union_ids)

    overlap_ids = set(comparison_payload["charity_ids"]["in_both_files"])
    only_annual_ids = set(comparison_payload["charity_ids"]["only_in_annual_return_file"])
    only_classification_ids = set(comparison_payload["charity_ids"]["only_in_classification_file"])

    merged_charities = build_merged_charities(
        union_ids=union_ids,
        overlap=overlap_ids,
        only_annual=only_annual_ids,
        only_classification=only_classification_ids,
        annual_filtered_rows=annual_filtered_rows,
        classification_filtered_rows=classification_filtered_rows,
        charity_rows=charity_rows,
        area_rows=area_rows_dict,
        classification_rows=classification_rows,
        history_rows_by_charity=history_rows_by_charity,
        parta_rows=parta_rows,
        partb_rows=partb_rows_dict,
    )

    write_merged_csv(MERGED_OUTPUT, merged_charities, CHARITY_DETAILS_URL_TEMPLATE)


if __name__ == "__main__":
    main()
