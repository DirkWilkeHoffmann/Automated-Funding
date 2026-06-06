"""Federal Register — Notice of Funding Availability (NOFA) source.

Uses the free Federal Register JSON API (no key required) to find recent
grant competition and funding announcement notices. Each result is a Federal
Register document page that describes the grant opportunity in full detail.

API docs: https://www.federalregister.gov/developers/documentation/api/v1
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.federalregister.gov/api/v1/documents.json"
_HEADERS = {"User-Agent": "automated-funding-bot/1.0", "Accept": "application/json"}

# Title must contain at least one of these to be considered a grant notice
_TITLE_MUST_CONTAIN = {
    "grant", "funding opportunity", "funds available", "notice of funding",
    "funding availability", "announcement of", "solicitation", "competition",
    "cooperative agreement", "financial assistance", "award", "assistance listing",
    "request for applications", "request for proposals", "rfp", "rfq",
}

# Reject titles containing these phrases — they're regulatory/administrative notices
# that happen to mention "grants" in a non-funding context.
_TITLE_REJECT_PHRASES = {
    "rule change", "proposed rule", "order instituting", "self-regulatory",
    "notice of filing", "exchange act", "investment advisers act",
    "securities act", "commodity exchange", "administrative proceeding",
    "disciplinary proceeding", "no-action letter", "exemptive application",
    "interpretive letter", "staff bulletin",
}


def _is_grant_notice(title: str) -> bool:
    """Return True if a Federal Register notice title looks like a grant opportunity."""
    t = title.lower()
    if any(phrase in t for phrase in _TITLE_REJECT_PHRASES):
        return False
    return any(kw in t for kw in _TITLE_MUST_CONTAIN)


def fetch_federal_register_grants(
    *,
    keywords: str,
    since_date: Optional[str] = None,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch recent grant funding notices from the Federal Register.

    Args:
        keywords: Search terms (e.g. "workforce development nonprofit").
        since_date: ISO date string (YYYY-MM-DD). Only return notices published on or after
                    this date. Defaults to 30 days ago.
        max_results: Maximum number of documents to return.

    Returns:
        List of dicts with keys: title, publication_date, html_url, agencies.
    """
    if not since_date:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        since_date = since.strftime("%Y-%m-%d")

    # Federal Register's `conditions[term]` is a phrase-search, so combining
    # caller keywords with "grants funding opportunity" never matches.
    # Strategy: when caller provides a single-word/short keyword, use it
    # standalone. Otherwise fall back to a single broad term that returns
    # the most NOFAs ("grants").
    kw_clean = (keywords or "").strip()
    if kw_clean and len(kw_clean.split()) <= 2:
        term = kw_clean
    else:
        term = "grants"

    params: Dict[str, Any] = {
        "conditions[term]": term,
        "conditions[type][]": "NOTICE",
        "conditions[publication_date][gte]": since_date,
        "per_page": min(max_results, 100),
        "order": "newest",
        "fields[]": ["html_url", "title", "publication_date", "agencies", "pdf_url"],
    }

    try:
        resp = requests.get(_BASE_URL, params=params, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Federal Register API error: %s", exc)
        return []

    raw = data.get("results") or []
    results = [r for r in raw if _is_grant_notice(r.get("title", ""))]
    logger.info(
        "Federal Register: %d/%d notices pass grant filter (since %s, API total: %d)",
        len(results), len(raw), since_date, data.get("count", 0),
    )
    return results[:max_results]


def federal_register_to_scrape_urls(docs: List[Dict[str, Any]]) -> List[str]:
    """Extract Federal Register HTML document URLs ready for scraping."""
    return [d["html_url"] for d in docs if d.get("html_url")]
