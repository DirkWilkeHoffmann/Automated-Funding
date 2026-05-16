"""Background scraping worker and single-fund processing."""

import logging
import os
import threading
import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

import pandas as pd

from utils.constants import CSV_COLUMNS, SAVE_DIR
from utils.data_processing import clear_results_cache
from utils.google_sheets import append_to_google_sheet
from utils.llm_utils import call_llm_extract
from utils.models import ScrapeProgress
from utils.scraping import extract_charity_commission_name, fetch_page, prioritized_crawl
from utils.utils_helpers import is_charity_commission_url, log_message, safe_filename_from_url

logger = logging.getLogger(__name__)


def process_single_fund(url: str, fund_name: Optional[str] = None, *, persist: bool = True) -> dict:
    """
    Process a single funding opportunity URL.

    Returns a dict with fund details, eligibility assessment, and any errors.
    """
    if fund_name:
        fund_name = fund_name.strip()
    if not fund_name or "<" in fund_name or "register of charities" in fund_name.lower():
        if is_charity_commission_url(url):
            seed_html = fetch_page(url)
            extracted_name = extract_charity_commission_name(seed_html)
            if extracted_name:
                fund_name = extracted_name
    fund_name = fund_name or urlparse(url).netloc
    result = {
        "fund_url": url,
        "fund_name": fund_name,
        "extraction_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        text, folder, pages_scraped, visited_urls, pdf_meta = prioritized_crawl(url)
        result["visited_urls"] = visited_urls
        result["pdf_read"] = bool(pdf_meta.get("pdf_read"))
        result["pdf_url"] = pdf_meta.get("pdf_url", "")
        result["pdf_pages"] = pdf_meta.get("pdf_pages", 0)
        result["pdf_text"] = pdf_meta.get("pdf_text", "")
        if not text or len(text) < 100:
            result["error"] = "Insufficient text extracted"
            log_message(f"Insufficient text extracted for {url}", "warning")
            return result
        data = call_llm_extract(text)
        result.update(data)
        result["pages_scraped"] = pages_scraped
        result["visited_urls_count"] = len(visited_urls)
        result["error"] = ""
        try:
            single_df = pd.DataFrame([result])
            for col in CSV_COLUMNS:
                if col not in single_df.columns:
                    single_df[col] = ""
            single_df = single_df[CSV_COLUMNS]
            domain_folder = os.path.join(SAVE_DIR, safe_filename_from_url(url))
            os.makedirs(domain_folder, exist_ok=True)
            single_df.to_csv(os.path.join(domain_folder, "fund_result.csv"), index=False)
        except Exception as e:
            log_message(f"Could not write individual CSV for {fund_name}: {e}", "warning")
    except Exception as e:
        # Friendly error mapping
        msg = str(e)
        if "Name or service not known" in msg or "Failed to establish a new connection" in msg:
            log_message(f"Network error contacting {url}: {msg}", "error")
        else:
            log_message(f"Processing failed for {url}: {msg}", "error")
        result["error"] = msg
    finally:
        if persist:
            # Persist to Google Sheet as soon as each fund finishes (even if errored)
            try:
                append_to_google_sheet([result])
                clear_results_cache()
            except Exception as e:
                log_message(f"Failed to persist {url} to Google Sheets: {e}", "error")
    return result


def start_background_scrape(urls: List[str]) -> ScrapeProgress:
    """
    Kick off a background scrape for the provided URLs.
    Returns a ScrapeProgress object that callers can poll.
    """

    progress = ScrapeProgress(started_at=time.time())
    total = max(len(urls), 1)

    def worker():
        for idx, url in enumerate(urls, start=1):
            try:
                progress.current_url = url
                progress.current_started_at = time.time()
                res = process_single_fund(url)
                progress.results.append(res)
                if res.get("error"):
                    progress.errors.append((url, res["error"]))
            except Exception as exc:
                progress.errors.append((url, str(exc)))
                res = {"fund_url": url, "error": str(exc)}
            finally:
                if progress.current_started_at:
                    duration = max(0.0, time.time() - progress.current_started_at)
                else:
                    duration = 0.0
                progress.url_timings.append(
                    {
                        "url": url,
                        "duration_seconds": duration,
                        "started_at": progress.current_started_at or time.time(),
                        "finished_at": time.time(),
                        "error": res.get("error") if isinstance(res, dict) else None,
                    }
                )
                progress.current_url = None
                progress.current_started_at = None

            progress.progress_percent = int(idx / total * 100)

        progress.done = True
        progress.finished_at = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return progress
