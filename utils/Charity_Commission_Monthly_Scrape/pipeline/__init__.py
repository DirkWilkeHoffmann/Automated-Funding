"""Grant making pipeline module with backwards-compatible re-exports."""

from .orchestration import (
    allocate_run_id,
    archive_run_results,
    copy_latest_aliases,
    find_latest_snapshot,
    orchestrate_pipeline,
    parse_args,
    run_grant_script,
)
from .queries import (
    build_download_manifest_entry,
    build_input_manifest,
    discover_json_zip_urls,
    download_file,
    ensure_required_inputs_present,
    extract_download_links_from_html,
    extract_json_files,
    load_download_manifest,
    load_json_file,
    load_snapshot_payload,
    save_download_manifest,
    select_urls,
    write_json_payload,
    write_to_scrape_csv,
)
from .transformations import (
    build_funds_snapshot,
    calculate_monthly_delta,
    first_non_empty_text,
    utc_iso,
)

__all__ = [
    # orchestration
    "run_grant_script",
    "allocate_run_id",
    "find_latest_snapshot",
    "copy_latest_aliases",
    "parse_args",
    "archive_run_results",
    "orchestrate_pipeline",
    # queries
    "load_json_file",
    "write_json_payload",
    "load_download_manifest",
    "save_download_manifest",
    "load_snapshot_payload",
    "discover_json_zip_urls",
    "extract_download_links_from_html",
    "select_urls",
    "build_download_manifest_entry",
    "download_file",
    "extract_json_files",
    "ensure_required_inputs_present",
    "build_input_manifest",
    "write_to_scrape_csv",
    # transformations
    "utc_iso",
    "first_non_empty_text",
    "build_funds_snapshot",
    "calculate_monthly_delta",
]
