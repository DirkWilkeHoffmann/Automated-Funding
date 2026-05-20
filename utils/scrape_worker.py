"""Background scraping worker and single-fund processing."""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd

from utils.constants import CSV_COLUMNS, SAVE_DIR
from utils.data_processing import clear_results_cache
from utils.db.funds_store import append_funds
from utils.llm_utils import call_llm_extract
from utils.models import ScrapeProgress
from utils.scraping import fetch_page, prioritized_crawl
from utils.utils_helpers import log_message, safe_filename_from_url

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_URLS = 3


def process_single_fund(
    url: str,
    fund_name: Optional[str] = None,
    *,
    persist: bool = True,
    extra_fields: Optional[dict] = None,
) -> dict:
    """
    Process a single funding opportunity URL.

    Returns a dict with fund details, eligibility assessment, and any errors.
    """
    if fund_name:
        fund_name = fund_name.strip()
    fund_name = fund_name or urlparse(url).netloc
    result: dict = {
        "fund_url": url,
        "fund_name": fund_name,
        "extraction_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if extra_fields:
        result.update(extra_fields)

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
        msg = str(e)
        if "Name or service not known" in msg or "Failed to establish a new connection" in msg:
            log_message(f"Network error contacting {url}: {msg}", "error")
        else:
            log_message(f"Processing failed for {url}: {msg}", "error")
        result["error"] = msg
    finally:
        if persist:
            try:
                append_funds([result])
                clear_results_cache()
            except Exception as e:
                log_message(f"Failed to persist {url} to Supabase: {e}", "error")
    return result


def start_background_scrape(
    urls: List[str],
    *,
    job_id: Optional[str] = None,
    url_metadata: Optional[dict] = None,
    _progress: Optional[ScrapeProgress] = None,
) -> ScrapeProgress:
    """
    Kick off a background scrape for the provided URLs.

    Processes up to _MAX_CONCURRENT_URLS in parallel. If job_id is provided,
    syncs progress to the scrape_jobs table after each URL completes (enables
    Supabase Realtime on the frontend).

    url_metadata: optional dict mapping url -> extra fields (e.g. {"discovery_source": "grants_gov"})
    to merge into each result before persisting.

    Returns a ScrapeProgress object that callers can poll.
    """
    progress = _progress if _progress is not None else ScrapeProgress(started_at=time.time())
    total = max(len(urls), 1)
    _lock = threading.Lock()
    _url_metadata: dict = url_metadata or {}

    def process_one(url: str) -> Tuple[str, dict, float, float]:
        started = time.time()
        with _lock:
            progress.current_url = url
            progress.current_started_at = started
        res = process_single_fund(url, extra_fields=_url_metadata.get(url))
        return url, res, started, time.time()

    def worker():
        completed = 0
        with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_URLS) as pool:
            futures = {pool.submit(process_one, url): url for url in urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    _, res, start_ts, end_ts = future.result()
                except Exception as exc:
                    logger.exception("Unexpected error processing %s", url)
                    res = {"fund_url": url, "error": str(exc)}
                    start_ts = end_ts = time.time()

                with _lock:
                    progress.results.append(res)
                    if res.get("error"):
                        progress.errors.append((url, res["error"]))
                    progress.url_timings.append(
                        {
                            "url": url,
                            "duration_seconds": end_ts - start_ts,
                            "started_at": start_ts,
                            "finished_at": end_ts,
                            "error": res.get("error") if isinstance(res, dict) else None,
                        }
                    )
                    completed += 1
                    progress.progress_percent = int(completed / total * 100)

                if job_id:
                    _sync_job_progress(job_id, completed, total)

        with _lock:
            progress.current_url = None
            progress.current_started_at = None
            progress.done = True
            progress.finished_at = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return progress


def _sync_job_progress(job_id: str, completed: int, total: int) -> None:
    """Push intermediate progress to scrape_jobs — enables Supabase Realtime updates."""
    try:
        from utils.db.client import get_supabase

        get_supabase().table("scrape_jobs").update(
            {
                "progress_percent": int(completed / max(total, 1) * 100),
                "completed_urls": completed,
            }
        ).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("Could not sync job progress to DB for %s: %s", job_id, exc)
