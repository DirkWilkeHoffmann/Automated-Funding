"""Document fetcher — downloads PDFs/attachments from sources and LLM-extracts them.

Pipeline (per document):
  1. Skip if document_url already exists in `documents` table (cross-run dedup)
  2. Download via download_and_extract_pdf_text (reuses the 24h HTML cache pattern)
  3. Truncate to PDF_MAX_PAGES / TEXT_MAX_CHARS for LLM cost control
  4. Call extract_from_document(text, kind) — gpt-4o-mini → gpt-4.1 fallback
  5. Upsert into `documents` table

Cost controls:
  - Per-run cap: max DOCUMENTS_PER_RUN (default 200) — oldest filing_year evicted first
  - Per-document size cap: PDF_MAX_PAGES, TEXT_MAX_CHARS
  - Dedup by document_url before download (no duplicate LLM cost)
  - Current-year filter applied at source level (see sources/registry.py)
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from utils.db.documents_store import existing_document_urls, upsert_document
from utils.discovery.sources.base import DocumentRef
from utils.llm_utils import extract_from_document
from utils.scraping import download_and_extract_pdf_text

logger = logging.getLogger(__name__)

PDF_MAX_PAGES = 60
TEXT_MAX_CHARS = 200_000
DOCUMENTS_PER_RUN_DEFAULT = 200
FETCHER_WORKERS = 4

# Per-run stats reported back to the orchestrator
DocStats = Dict[str, int]


def _select_within_cap(refs: List[DocumentRef], cap: int) -> List[DocumentRef]:
    """Apply the per-run cap, preferring newer filing years and PDFs over attachments."""
    if len(refs) <= cap:
        return refs
    # Newer filing_year first, then form_990 priority, then anything else
    def sort_key(r: DocumentRef) -> tuple:
        year = r.filing_year or 0
        kind_priority = {"form_990": 0, "rfp": 1, "notice": 2, "attachment": 3}.get(r.kind, 9)
        return (-year, kind_priority)
    return sorted(refs, key=sort_key)[:cap]


def _process_one(
    ref: DocumentRef,
    cancel_token: threading.Event,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]],
) -> Dict[str, Any]:
    """Download + extract a single document, persist, return stat update.

    If the ref carries `prefetched_text`, skip download entirely and feed the
    text straight to the LLM — used for sources whose PDFs are unreachable
    (e.g. ProPublica's Cloudflare-protected 990 PDFs).
    """
    stat: Dict[str, Any] = {"document_url": ref.url, "kind": ref.kind, "extracted": False}
    if cancel_token.is_set():
        stat["skipped"] = "cancelled"
        return stat

    source_name = ref.extra.get("source", "") if isinstance(ref.extra, dict) else ""
    text: str = ""
    page_count: int = 0
    file_size: Optional[int] = None

    if ref.prefetched_text:
        text = ref.prefetched_text
    else:
        pdf = download_and_extract_pdf_text(ref.url, max_chars=TEXT_MAX_CHARS)
        if not pdf.get("success"):
            stat["error"] = pdf.get("error", "download failed")
            upsert_document({
                "source_name": source_name,
                "source_url": ref.source_url,
                "document_url": ref.url,
                "kind": ref.kind,
                "filing_year": ref.filing_year,
                "fund_url": ref.source_url,
                "extraction_error": stat["error"][:500],
            })
            return stat
        text = pdf.get("text") or ""
        page_count = int(pdf.get("num_pages") or 0)
        file_size = pdf.get("file_size")
        # Honour the page cap by trimming text (PyPDF2 has already read all pages —
        # this guards LLM cost on extra-long docs that slipped past the source filter)
        if page_count > PDF_MAX_PAGES and text:
            text = text[: int(len(text) * (PDF_MAX_PAGES / page_count))]

    if cancel_token.is_set():
        stat["skipped"] = "cancelled"
        return stat

    summary = extract_from_document(text, ref.kind) if text else {}
    stat["extracted"] = bool(summary)

    upsert_document({
        "source_name": source_name,
        "source_url": ref.source_url,
        "document_url": ref.url,
        "kind": ref.kind,
        "filing_year": ref.filing_year,
        "text_content": text,
        "page_count": page_count or None,
        "file_size": file_size,
        "llm_summary": summary or None,
        "fund_url": ref.source_url,
        "extracted_at": (
            datetime.now(timezone.utc).isoformat() if summary else None
        ),
    })

    if progress_cb:
        try:
            progress_cb({"document_url": ref.url, "kind": ref.kind, "extracted": stat["extracted"]})
        except Exception:
            pass
    return stat


def fetch_documents(
    refs: List[DocumentRef],
    *,
    cancel_token: threading.Event,
    per_run_cap: int = DOCUMENTS_PER_RUN_DEFAULT,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> DocStats:
    """Run the full document pipeline. Returns aggregate stats."""
    if not refs:
        return {"submitted": 0, "skipped_dedup": 0, "downloaded": 0, "extracted": 0, "errors": 0}

    # Dedup against the documents table (skip docs already processed)
    all_urls = [r.url for r in refs if r.url]
    existing = existing_document_urls(all_urls)
    fresh = [r for r in refs if r.url and r.url not in existing]
    skipped_dedup = len(refs) - len(fresh)

    # Apply per-run cap
    selected = _select_within_cap(fresh, per_run_cap)

    submitted = len(selected)
    downloaded = extracted = errors = 0

    if not selected:
        return {
            "submitted": 0,
            "skipped_dedup": skipped_dedup,
            "downloaded": 0,
            "extracted": 0,
            "errors": 0,
        }

    started = time.time()
    logger.info(
        "Document fetcher: %d refs in, %d dedup-skipped, %d capped → fetching %d",
        len(refs), skipped_dedup, max(0, len(fresh) - submitted), submitted,
    )

    with ThreadPoolExecutor(max_workers=FETCHER_WORKERS, thread_name_prefix="docfetch") as pool:
        futures = {pool.submit(_process_one, ref, cancel_token, progress_cb): ref for ref in selected}
        for fut in as_completed(futures):
            try:
                stat = fut.result()
            except Exception as exc:
                logger.warning("Document worker crashed: %s", exc)
                errors += 1
                continue
            if stat.get("error"):
                errors += 1
            else:
                downloaded += 1
                if stat.get("extracted"):
                    extracted += 1

    elapsed = time.time() - started
    logger.info(
        "Document fetcher done in %.1fs: downloaded=%d extracted=%d errors=%d",
        elapsed, downloaded, extracted, errors,
    )
    return {
        "submitted": submitted,
        "skipped_dedup": skipped_dedup,
        "downloaded": downloaded,
        "extracted": extracted,
        "errors": errors,
    }
