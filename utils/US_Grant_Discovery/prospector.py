"""
ProPublica Nonprofit Explorer — US foundation prospector.

Finds US grant-making foundations by state and mission using the free
ProPublica Nonprofit Explorer API (no API key required).

API docs: https://projects.propublica.org/nonprofits/api
NTEE code T = Philanthropy, Voluntarism and Grantmaking Foundations
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://projects.propublica.org/nonprofits/api/v2"
_HEADERS = {"Accept": "application/json", "User-Agent": "automated-funding-bot/1.0"}
_PAUSE = 0.5  # seconds between API calls (be a good citizen)

# NTEE codes for grant-making / foundation types
# T20 = Private grantmaking foundations
# T21 = Corporate foundations
# T22 = Private operating foundations
# T30 = Public foundations
# T31 = Community foundations
GRANTMAKING_NTEE_CODES = ["T20", "T21", "T22", "T30", "T31"]

# Minimum gross receipts to consider (filters out tiny orgs)
MIN_GROSS_RECEIPTS = 100_000


def search_foundations(
    *,
    state: Optional[str] = None,
    keywords: Optional[str] = None,
    ntee_codes: Optional[List[str]] = None,
    min_receipts: int = MIN_GROSS_RECEIPTS,
    max_results: int = 200,
) -> List[Dict[str, Any]]:
    """
    Search ProPublica for grant-making foundations.

    Args:
        state: Two-letter US state code (e.g. "CA", "NY"). If omitted, searches all states.
        keywords: Optional search keywords to filter by name/mission.
        ntee_codes: NTEE codes to filter by (defaults to GRANTMAKING_NTEE_CODES).
        min_receipts: Minimum gross_receipts to include.
        max_results: Maximum number of results to return.

    Returns:
        List of foundation dicts with keys: name, ein, city, state, website,
        ntee_code, gross_receipts, asset_amount.
    """
    results: List[Dict[str, Any]] = []
    page = 0

    while len(results) < max_results:
        params: Dict[str, Any] = {"page": page}
        if state:
            params["state[id]"] = state
        if keywords:
            params["q"] = keywords

        try:
            resp = requests.get(
                f"{_BASE_URL}/search.json", params=params, headers=_HEADERS, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("ProPublica API error (state=%s page=%d): %s", state, page, exc)
            break

        orgs = data.get("organizations") or []
        if not orgs:
            break

        for org in orgs:
            receipts = org.get("gross_receipts")
            if receipts is not None and receipts < min_receipts:
                continue
            results.append(
                {
                    "name": org.get("name", ""),
                    "ein": org.get("ein", ""),
                    "city": org.get("city", ""),
                    "state": org.get("state", ""),
                    "website": _extract_website(org),
                    "ntee_code": org.get("ntee_code", ""),
                    "gross_receipts": receipts,
                    "asset_amount": org.get("asset_amount") or 0,
                    "propublica_url": (
                        f"https://projects.propublica.org/nonprofits/organizations/{org.get('ein', '')}"
                    ),
                }
            )
            if len(results) >= max_results:
                break

        page += 1
        time.sleep(_PAUSE)

    return results[:max_results]


def _extract_website(org: Dict[str, Any]) -> str:
    """Best-effort website URL from a ProPublica org record."""
    return org.get("website") or org.get("url") or ""


def foundations_to_scrape_urls(foundations: List[Dict[str, Any]]) -> List[str]:
    """Extract scrape-ready URLs from foundation records (website preferred, ProPublica fallback)."""
    urls = []
    for f in foundations:
        url = f.get("website") or f.get("propublica_url") or ""
        if url:
            urls.append(url)
    return urls
