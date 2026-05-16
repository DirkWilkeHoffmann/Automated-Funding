"""Automated Funding scraping and analysis utilities."""

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
    # Config
    "configure_tools",
    "get_settings",
    # Models
    "ScrapeProgress",
    "ToolSettings",
    # Scraping
    "discover_links",
    "download_and_extract_pdf_text",
    "extract_charity_commission_accounts_links",
    "extract_charity_commission_name",
    "extract_visible_text",
    "fetch_page",
    "prioritized_crawl",
    "score_candidate",
    # LLM
    "call_llm_extract",
    "get_client",
    # Google Sheets
    "append_to_google_sheet",
    "load_google_sheet_as_dataframe",
    # Data Processing
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
    # Scrape Worker
    "process_single_fund",
    "start_background_scrape",
    # Utilities
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
