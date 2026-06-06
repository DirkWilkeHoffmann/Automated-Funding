"""Background scraping worker and single-fund processing."""

import hashlib
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd

from utils.constants import CSV_COLUMNS, SAVE_DIR
from utils.data_processing import clear_results_cache
from utils.db.funds_store import append_funds, upsert_fund
from utils.db.pending_urls_store import upsert_pending_urls as _upsert_pending
from utils.llm_utils import call_llm_extract
from utils.models import ScrapeProgress
from utils.scraping import detect_listing_page, extract_listing_urls, fetch_page, prioritized_crawl
from utils.utils_helpers import log_message, safe_filename_from_url

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_URLS = 3
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRAPE_LOG_DIR = os.path.join(_REPO_ROOT, "logs", "scrape")


def _write_fund_log_scrape_start(
    url: str,
    raw_text: str,
    visited_urls: list,
    pages_scraped: int,
) -> None:
    """Reset the per-fund consolidated log and write the SCRAPE section.

    Must be called BEFORE call_llm_extract so the file is cleared before LLM
    phases begin appending. Calling it after LLM would truncate their output.
    """
    try:
        from utils.llm_utils import LLM_DEBUG_LOGGING, write_fund_log_section
        if not LLM_DEBUG_LOGGING:
            return
        scrape_body_lines = [
            f"URL        : {url}",
            f"PAGES      : {pages_scraped}",
            f"VISITED    : {len(visited_urls)}",
            f"TEXT LEN   : {len(raw_text)} chars",
            "",
            "VISITED URLS:",
        ]
        scrape_body_lines.extend(f"  {vu}" for vu in visited_urls)
        scrape_body_lines.extend(["", "── RAW SCRAPED TEXT ──", raw_text])
        write_fund_log_section(url, "SCRAPE", "\n".join(scrape_body_lines), reset=True)
    except Exception as exc:
        logger.warning("Could not write scrape start log for %s: %s", url, exc)


def _write_scrape_log(
    url: str,
    raw_text: str,
    visited_urls: list,
    pages_scraped: int,
    extracted: dict,
) -> None:
    """Append the FINAL EXTRACTED FIELDS section to the per-fund log, and write
    the legacy split log.

    The SCRAPE section (with reset=True) is written separately by
    _write_fund_log_scrape_start BEFORE LLM extraction so that LLM Phase 1/2
    sections append to a freshly cleared file. This function is called AFTER
    LLM extraction and only appends.
    """
    try:
        from utils.llm_utils import LLM_DEBUG_LOGGING, write_fund_log_section
        if not LLM_DEBUG_LOGGING:
            return
        from utils.utils_helpers import safe_filename_from_url

        # ── Consolidated per-fund log — FINAL EXTRACTED FIELDS (append) ───
        skip = {"pdf_text", "content_hash", "visited_urls", "match_rubric"}
        fields_lines = []
        for k, v in extracted.items():
            if k in skip:
                continue
            fields_lines.append(f"  {k:<28}: {v}")
        # Render the rubric as a compact table at the end.
        rubric = extracted.get("match_rubric") or {}
        if rubric:
            fields_lines.append("")
            fields_lines.append("RUBRIC:")
            for dim, entry in rubric.items():
                if isinstance(entry, dict):
                    v = entry.get("verdict", "?")
                    e = (entry.get("evidence") or "")[:120]
                    fields_lines.append(f"  {dim:<22} {v:<10} {e}")
        write_fund_log_section(url, "FINAL EXTRACTED FIELDS", "\n".join(fields_lines))

        # ── Legacy split log (kept for backwards compat) ───────────────────
        os.makedirs(_SCRAPE_LOG_DIR, exist_ok=True)
        url_safe = safe_filename_from_url(url)
        log_path = os.path.join(_SCRAPE_LOG_DIR, f"{url_safe}.txt")
        sep = "=" * 100
        thin = "-" * 60
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"{sep}\n")
            f.write("SCRAPE LOG\n")
            f.write(f"TIMESTAMP  : {datetime.now(timezone.utc).isoformat()}\n")
            f.write(f"URL        : {url}\n")
            f.write(f"PAGES      : {pages_scraped}\n")
            f.write(f"VISITED    : {len(visited_urls)}\n")
            f.write(f"TEXT LEN   : {len(raw_text)} chars\n")
            f.write(f"\n{thin}\nVISITED URLS:\n")
            for vu in visited_urls:
                f.write(f"  {vu}\n")
            f.write(f"\n{thin}\nRAW SCRAPED TEXT:\n{thin}\n")
            f.write(raw_text)
            f.write(f"\n\n{sep}\nEXTRACTED FIELDS (LLM output):\n{thin}\n")
            for k, v in extracted.items():
                if k not in {"pdf_text", "content_hash", "visited_urls"}:
                    f.write(f"  {k:<28}: {v}\n")
            f.write(f"{sep}\n")
    except Exception as exc:
        logger.warning("Could not write scrape log for %s: %s", url, exc)


def _get_document_summaries(fund_url: str) -> str:
    """Return formatted text from any pre-extracted 990/document summaries for this URL.

    Called after website crawl, before call_llm_extract() — wires in discovery-phase
    IRS 990 data (focus areas, grantees, geographic scope) so the eligibility scorer
    has concrete funder signals even when the website text is vague.
    Returns an empty string when no documents exist (safe no-op).
    """
    try:
        from utils.db.documents_store import list_for_fund
        docs = list_for_fund(fund_url)
        if not docs:
            return ""
        parts: list[str] = []
        for doc in docs:
            summary = doc.get("llm_summary")
            kind = doc.get("kind", "")
            if not summary or not isinstance(summary, dict):
                continue
            if kind == "form_990":
                lines = ["=== IRS Form 990 (structured funder data) ==="]
                if summary.get("program_areas"):
                    areas = summary["program_areas"]
                    if isinstance(areas, list):
                        areas = ", ".join(str(a) for a in areas)
                    lines.append(f"Grantmaking focus areas: {areas}")
                if summary.get("geographic_scope"):
                    lines.append(f"Geographic scope: {summary['geographic_scope']}")
                if summary.get("total_grants_paid"):
                    lines.append(f"Total grants paid this year: {summary['total_grants_paid']}")
                if summary.get("application_process"):
                    lines.append(f"Application process: {summary['application_process']}")
                if summary.get("contact_email"):
                    lines.append(f"Contact: {summary['contact_email']}")
                grantees = summary.get("top_grantees") or []
                if isinstance(grantees, list) and grantees:
                    names = [
                        g.get("name", "") for g in grantees[:5]
                        if isinstance(g, dict) and g.get("name")
                    ]
                    if names:
                        lines.append(f"Recent grantees include: {', '.join(names)}")
                parts.append("\n".join(lines))
            elif kind in ("rfp", "notice", "attachment"):
                lines = ["=== Funding Document Data ==="]
                if summary.get("eligibility"):
                    lines.append(f"Eligibility: {summary['eligibility']}")
                if summary.get("funding_range"):
                    lines.append(f"Funding range: {summary['funding_range']}")
                if summary.get("deadline"):
                    lines.append(f"Deadline: {summary['deadline']}")
                if summary.get("program_focus"):
                    lines.append(f"Program focus: {summary['program_focus']}")
                if summary.get("geographic_scope"):
                    lines.append(f"Geographic scope: {summary['geographic_scope']}")
                if summary.get("application_url"):
                    lines.append(f"Apply at: {summary['application_url']}")
                parts.append("\n".join(lines))
        return "\n\n".join(parts)
    except Exception as exc:
        logger.warning("Could not load document summaries for %s: %s", fund_url, exc)
        return ""


_GRANTS_GOV_DETAIL_RE = re.compile(
    r"https?://(?:www\.)?grants\.gov/search-results-detail/(.+)", re.IGNORECASE
)


def _grants_gov_detail_text(url: str) -> Optional[tuple]:
    """For grants.gov SPA detail URLs, return (llm_text, title) from our grant_opportunities DB.

    grants.gov is a React SPA — the server serves a navigation shell for every route,
    so web-crawling yields zero grant content.  We already import the full XML extract
    daily, so reading from the DB is both faster and more accurate.

    Returns (text, title) tuple, or None if no DB record exists.
    """
    m = _GRANTS_GOV_DETAIL_RE.match(url)
    if not m:
        return None
    try:
        from utils.db.client import get_supabase
        canonical = f"https://www.grants.gov/search-results-detail/{m.group(1)}"
        rows = (
            get_supabase()
            .table("grant_opportunities")
            .select("*")
            .eq("url", canonical)
            .limit(1)
            .execute()
            .data or []
        )
        if not rows:
            logger.info("grants.gov: no DB record for %s", url)
            return None
        r = rows[0]
        parts = [f"GRANT OPPORTUNITY: {r.get('title', '')}",
                 f"Agency: {r.get('agency', '')}"]
        if r.get("opportunity_number"):
            parts.append(f"Funding Opportunity Number: {r['opportunity_number']}")
        if r.get("cfda_number"):
            parts.append(f"CFDA / Assistance Listing: {r['cfda_number']}")
        if r.get("category"):
            parts.append(f"Category of Funding Activity: {r['category']}")
        if r.get("award_ceiling"):
            parts.append(f"Award Ceiling: ${r['award_ceiling']:,}")
        if r.get("award_floor"):
            parts.append(f"Award Floor: ${r['award_floor']:,}")
        if r.get("close_date"):
            parts.append(f"Application Deadline: {r['close_date']}")
        if r.get("posted_date"):
            parts.append(f"Posted Date: {r['posted_date']}")
        if r.get("eligibility_text"):
            parts.append(f"\nEligibility:\n{r['eligibility_text']}")
        if r.get("description"):
            parts.append(f"\nDescription:\n{r['description']}")
        parts.append(f"\nSource URL: {canonical}")
        return "\n".join(parts), r.get("title") or ""
    except Exception as exc:
        logger.warning("Could not fetch grants.gov DB record for %s: %s", url, exc)
        return None


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
    result: dict = {
        "fund_url": url,
        "extraction_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if extra_fields:
        result.update(extra_fields)

    _do_persist = persist
    _existing_id: Optional[str] = None

    try:
        prefetched = _grants_gov_detail_text(url)
        if prefetched:
            text, db_title = prefetched
            # Use the DB title as fund_name when none was supplied (e.g. manual rescrape)
            if not fund_name:
                fund_name = db_title or urlparse(url).netloc
            folder = ""
            pages_scraped = 0
            visited_urls = [url]
            pdf_meta: dict = {"pdf_read": False, "pdf_url": "", "pdf_pages": 0, "pdf_text": ""}
            log_message(f"Used DB pre-fetch for grants.gov URL: {url}", "info")
        else:
            text, folder, pages_scraped, visited_urls, pdf_meta = prioritized_crawl(url)
        # Finalize fund_name now that prefetch may have resolved a title
        fund_name = fund_name or urlparse(url).netloc
        result["fund_name"] = fund_name
        result["visited_urls"] = visited_urls
        result["pdf_read"] = bool(pdf_meta.get("pdf_read"))
        result["pdf_url"] = pdf_meta.get("pdf_url", "")
        result["pdf_pages"] = pdf_meta.get("pdf_pages", 0)
        result["pdf_text"] = pdf_meta.get("pdf_text", "")
        if not text or len(text) < 100:
            result["error"] = "Insufficient text extracted"
            log_message(f"Insufficient text extracted for {url}", "warning")
            return result

        # Content-hash change detection: skip LLM if page is unchanged.
        now_iso = datetime.now(timezone.utc).isoformat()
        new_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        result["content_hash"] = new_hash
        result["last_checked_at"] = now_iso
        try:
            from utils.db.client import get_supabase
            existing_rows = (
                get_supabase()
                .table("funds")
                .select("id, content_hash")
                .eq("fund_url", url)
                .order("extraction_timestamp", desc=True)
                .limit(1)
                .execute()
                .data or []
            )
            if existing_rows:
                _existing_id = existing_rows[0].get("id")
                if existing_rows[0].get("content_hash") == new_hash:
                    # Unchanged — update timestamp only, skip LLM
                    get_supabase().table("funds").update(
                        {"last_checked_at": now_iso}
                    ).eq("id", _existing_id).execute()
                    result["skipped"] = "unchanged"
                    _do_persist = False
                    log_message(f"Content unchanged for {url}; skipping LLM", "info")
                    return result
        except Exception as exc:
            log_message(f"Hash check failed for {url}: {exc}", "warning")

        # Capture raw crawled text before doc-context is appended (for the scrape log).
        raw_crawled_text = text

        # Reset the per-fund log and write the SCRAPE section NOW, before LLM
        # extraction begins. LLM Phase 1/2 will append their sections afterwards.
        # If this call were placed after call_llm_extract, reset=True would erase
        # the LLM sections that had already been written.
        _write_fund_log_scrape_start(url, raw_crawled_text, visited_urls, pages_scraped)

        # Append any pre-extracted 990 / document summaries from the discovery phase.
        doc_context = _get_document_summaries(url)
        if doc_context:
            text = text + "\n\n" + doc_context
            log_message(f"Injected document context ({len(doc_context)} chars) for {url}", "info")

        # Listing page detection — fires before LLM to avoid garbage extraction
        if detect_listing_page(url, text):
            sub_items = extract_listing_urls(url)
            if sub_items:
                n = _upsert_pending(sub_items, source_url=url)
                log_message(
                    f"Listing page: {len(sub_items)} sub-URLs queued for review from {url}",
                    "info",
                )
            else:
                log_message(f"Listing page detected at {url} but no sub-URLs extracted", "warning")
            result["skipped"] = "listing_page"
            result["error"] = ""
            _do_persist = False
            return result

        data = call_llm_extract(text, fund_url=url)
        result.update(data)

        # Apply fund name priority: passed-in param > Stage 1 extracted > netloc fallback
        _s1_name = data.get("stage1_fund_name", "").strip()
        if result.get("fund_name") == urlparse(url).netloc and _s1_name:
            result["fund_name"] = _s1_name
        # Remove the internal staging key — not a DB column
        result.pop("stage1_fund_name", None)

        result["pages_scraped"] = pages_scraped
        result["visited_urls_count"] = len(visited_urls)
        result["error"] = ""
        # Re-stamp these after update() in case LLM data clobbered them
        result["content_hash"] = new_hash
        result["last_checked_at"] = now_iso

        # Write per-URL debug logs (scrape text + extracted fields).
        _write_scrape_log(url, raw_crawled_text, visited_urls, pages_scraped, result)
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
        if _do_persist:
            try:
                if _existing_id:
                    upsert_fund(result, existing_id=_existing_id)
                else:
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
        meta = _url_metadata.get(url) or {}
        fn = meta.get("fund_name") or None
        res = process_single_fund(url, fund_name=fn, extra_fields=meta)
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
