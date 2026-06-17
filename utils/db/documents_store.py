"""Supabase-backed document storage for discovery-harvested PDFs/attachments."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from utils.db.client import get_supabase

logger = logging.getLogger(__name__)

_TEXT_MAX_CHARS = 200_000  # ~200KB per row cap


def existing_document_urls(urls: List[str]) -> Set[str]:
    """Return the subset of `urls` already present in the documents table.

    Used by the document fetcher to skip work that's already been done in a
    previous discovery run.
    """
    if not urls:
        return set()
    found: Set[str] = set()
    # Supabase REST has URL length limits; chunk the IN clause
    chunk_size = 100
    for i in range(0, len(urls), chunk_size):
        chunk = urls[i : i + chunk_size]
        try:
            rows = (
                get_supabase()
                .table("documents")
                .select("document_url")
                .in_("document_url", chunk)
                .execute()
                .data
                or []
            )
            for r in rows:
                if r.get("document_url"):
                    found.add(r["document_url"])
        except Exception as exc:
            logger.warning("Could not check existing documents: %s", exc)
    return found


def upsert_document(record: Dict[str, Any]) -> Optional[str]:
    """Insert (or upsert by document_url) a document row. Returns id."""
    if not record.get("document_url"):
        return None

    payload = dict(record)
    if isinstance(payload.get("text_content"), str) and len(payload["text_content"]) > _TEXT_MAX_CHARS:
        payload["text_content"] = payload["text_content"][:_TEXT_MAX_CHARS] + "\n...[truncated]..."

    if "fetched_at" not in payload:
        payload["fetched_at"] = datetime.now(timezone.utc).isoformat()

    try:
        result = (
            get_supabase()
            .table("documents")
            .upsert(payload, on_conflict="document_url")
            .execute()
        )
        rows = result.data or []
        return rows[0].get("id") if rows else None
    except Exception as exc:
        logger.warning("Could not upsert document %s: %s", payload.get("document_url"), exc)
        return None


def list_for_fund(fund_url: str) -> List[Dict[str, Any]]:
    """Return all documents linked to a fund URL."""
    if not fund_url:
        return []
    try:
        return (
            get_supabase()
            .table("documents")
            .select("*")
            .eq("fund_url", fund_url)
            .order("fetched_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.warning("Could not list documents for fund %s: %s", fund_url, exc)
        return []
