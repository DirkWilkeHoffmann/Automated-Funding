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

# Keywords that make a NOTICE strongly likely to be a grant opportunity
_GRANT_KEYWORDS = (
    "nonprofit grants funding opportunity notice|"
    "notice of funding availability|"
    "funding opportunity announcement|"
    "notice announcing|competition"
)


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

    params: Dict[str, Any] = {
        "conditions[term]": f"{keywords} grants funding opportunity",
        "conditions[type][]": "NOTICE",
        "conditions[publication_date][gte]": since_date,
        "per_page": min(max_results, 100),
        "order": "newest",
        "fields[]": ["html_url", "title", "publication_date", "agencies"],
    }

    try:
        resp = requests.get(_BASE_URL, params=params, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Federal Register API error: %s", exc)
        return []

    results = data.get("results") or []
    logger.info(
        "Federal Register: %d notices (since %s, total in API: %d)",
        len(results), since_date, data.get("count", 0),
    )
    return results[:max_results]


def federal_register_to_scrape_urls(docs: List[Dict[str, Any]]) -> List[str]:
    """Extract Federal Register HTML document URLs ready for scraping."""
    return [d["html_url"] for d in docs if d.get("html_url")]
