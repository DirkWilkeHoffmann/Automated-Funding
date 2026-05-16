"""
Backwards compatibility module - tools have been refactored into modular components.

This module re-exports all tools for backwards compatibility.
New code should import directly from the specific modules:
- utils.config: configure_tools, get_settings
- utils.models: ScrapeProgress, ToolSettings
- utils.scraping: fetch_page, prioritized_crawl, etc.
- utils.llm_utils: call_llm_extract, get_client
- utils.google_sheets: append_to_google_sheet, etc.
- utils.data_processing: load_results_csv, latest_results_by_url, etc.
- utils.scrape_worker: process_single_fund, start_background_scrape
- utils.utils_helpers: normalize_url, safe_filename_from_url, etc.
"""

# Re-export all public APIs for backwards compatibility
from utils.config import configure_tools, get_settings
from utils.data_processing import (
    clear_results_cache,
    clear_scraped_domains_cache,
    get_already_processed_urls,
    get_scraped_domains,
    latest_results_by_canon_url,
    latest_results_by_url,
    load_results_csv,
    load_text_from_folder,
    stale_results_by_canon_url,
    stale_results_by_url,
)
from utils.google_sheets import (
    append_to_google_sheet,
    load_google_sheet_as_dataframe,
)
from utils.llm_utils import call_llm_extract, get_client
from utils.models import ScrapeProgress, ToolSettings
from utils.scrape_worker import process_single_fund, start_background_scrape
from utils.scraping import (
    discover_links,
    download_and_extract_pdf_text,
    extract_charity_commission_accounts_links,
    extract_charity_commission_name,
    extract_visible_text,
    fetch_page,
    prioritized_crawl,
    score_candidate,
)
from utils.utils_helpers import (
    canon_funder_url,
    folder_name_for_url,
    initial_normalize_url,
    is_charity_commission_url,
    log_message,
    normalize_url,
    parse_extraction_timestamp,
    safe_filename_from_url,
    subtract_months,
)

__all__ = [
    "configure_tools",
    "get_settings",
    "ScrapeProgress",
    "ToolSettings",
    "discover_links",
    "download_and_extract_pdf_text",
    "extract_charity_commission_accounts_links",
    "extract_charity_commission_name",
    "extract_visible_text",
    "fetch_page",
    "prioritized_crawl",
    "score_candidate",
    "call_llm_extract",
    "get_client",
    "append_to_google_sheet",
    "load_google_sheet_as_dataframe",
    "clear_results_cache",
    "clear_scraped_domains_cache",
    "get_already_processed_urls",
    "get_scraped_domains",
    "latest_results_by_canon_url",
    "latest_results_by_url",
    "load_results_csv",
    "load_text_from_folder",
    "stale_results_by_canon_url",
    "stale_results_by_url",
    "process_single_fund",
    "start_background_scrape",
    "canon_funder_url",
    "folder_name_for_url",
    "initial_normalize_url",
    "is_charity_commission_url",
    "log_message",
    "normalize_url",
    "parse_extraction_timestamp",
    "safe_filename_from_url",
    "subtract_months",
]
