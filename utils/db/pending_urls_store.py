# utils/db/pending_urls_store.py
"""CRUD for the pending_urls table."""

from __future__ import annotations

import logging
from typing import List, Optional

from utils.db.client import get_supabase

logger = logging.getLogger(__name__)


def upsert_pending_urls(items: List[dict], source_url: str) -> int:
    """Insert pending URL rows, ignoring duplicates by URL.

    items: list of {"url": str, "title": str} dicts (from extract_listing_urls).
    Returns the number of rows attempted.
    """
    if not items:
        return 0
    rows = [
        {
            "url": item["url"],
            "title": (item.get("title") or "")[:240],
            "source_url": source_url,
            "status": "awaiting_review",
        }
        for item in items
        if item.get("url")
    ]
    if not rows:
        return 0
    try:
        get_supabase().table("pending_urls").upsert(
            rows, on_conflict="url", ignore_duplicates=True
        ).execute()
        return len(rows)
    except Exception as exc:
        logger.warning("upsert_pending_urls failed: %s", exc)
        return 0


def list_pending(status: str = "awaiting_review") -> List[dict]:
    """Return pending_urls rows with the given status, newest first."""
    try:
        return (
            get_supabase()
            .table("pending_urls")
            .select("*")
            .eq("status", status)
            .order("created_at", desc=True)
            .execute()
            .data or []
        )
    except Exception as exc:
        logger.warning("list_pending failed: %s", exc)
        return []


def approve_batch(ids: List[str], user_id: Optional[str] = None) -> List[str]:
    """Mark URLs as approved. Returns the approved URLs."""
    if not ids:
        return []
    try:
        update: dict = {"status": "approved"}
        if user_id:
            update["approved_by"] = user_id
        rows = (
            get_supabase()
            .table("pending_urls")
            .update(update)
            .in_("id", ids)
            .execute()
            .data or []
        )
        return [r["url"] for r in rows]
    except Exception as exc:
        logger.warning("approve_batch failed: %s", exc)
        return []


def mark_scraped(ids: List[str], scrape_job_id: Optional[str] = None) -> None:
    """Mark approved URLs as scraped after a scrape job is queued."""
    if not ids:
        return
    try:
        update: dict = {"status": "scraped"}
        if scrape_job_id:
            update["scrape_job_id"] = scrape_job_id
        get_supabase().table("pending_urls").update(update).in_("id", ids).execute()
    except Exception as exc:
        logger.warning("mark_scraped failed: %s", exc)


def reject_batch(ids: List[str]) -> None:
    """Mark URLs as rejected."""
    if not ids:
        return
    try:
        get_supabase().table("pending_urls").update({"status": "rejected"}).in_("id", ids).execute()
    except Exception as exc:
        logger.warning("reject_batch failed: %s", exc)


def pending_count() -> int:
    """Count awaiting_review rows (for notification badge)."""
    try:
        result = (
            get_supabase()
            .table("pending_urls")
            .select("id", count="exact", head=True)
            .eq("status", "awaiting_review")
            .execute()
        )
        return result.count or 0
    except Exception as exc:
        logger.warning("pending_count failed: %s", exc)
        return 0
