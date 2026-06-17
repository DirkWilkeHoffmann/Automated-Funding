"""Candid (formerly Foundation Center / GuideStar) — gated on paid API key.

Candid's "Public Profile" / "Essentials" / "Premier" APIs are paid subscriptions.
There is no free public REST endpoint that surfaces funder URLs in bulk — the
PND RFP feed (formerly free) has been folded into Candid's paid product.

This source is therefore gated on a `candid` API key being present in the
`api_tokens` table (same pattern as SAM.gov). When no key is present, the
source completes immediately with zero results and a clear "skipped (no key)"
status — it does not fail the run.

When a key is present, this implementation queries Candid's Essentials API
(api.candid.org/essentials/v3) for grantmaker profiles. Adjust the endpoint
URL when Candid changes their API version.

API docs: https://developer.candid.org
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.candid.org/essentials/v3"
_HEADERS_BASE = {"Accept": "application/json", "User-Agent": "automated-funding-bot/1.0"}


def search_candid_funders(
    *,
    api_key: str,
    keywords: str = "",
    state: Optional[str] = None,
    max_results: int = 100,
) -> List[Dict[str, Any]]:
    """Search Candid Essentials for grantmaking organizations.

    Returns dicts with: ein, name, website, location, mission, classification.
    Subscription is required — without a key this is unreachable.
    """
    if not api_key or not api_key.strip():
        raise ValueError("Candid API key is required")

    headers = {**_HEADERS_BASE, "Subscription-Key": api_key.strip()}
    params: Dict[str, Any] = {
        "search_terms": keywords or "foundation",
        "size": min(max_results, 100),
        # filter to grantmakers — NTEE T-codes are the grantmaking classification
        "filters[organization][specific_classifications]": "T20,T21,T22,T30,T31",
    }
    if state:
        params["filters[geography][state]"] = state

    try:
        resp = requests.get(_BASE_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Candid Essentials API error: %s", exc)
        return []

    hits = (data.get("data") or {}).get("hits") or []
    results: List[Dict[str, Any]] = []
    for h in hits[:max_results]:
        org = h.get("organization") or h
        results.append({
            "ein": (org.get("ein") or "").replace("-", ""),
            "name": org.get("organization_name") or org.get("name") or "",
            "website": org.get("website_url") or "",
            "city": (org.get("address") or {}).get("city", ""),
            "state": (org.get("address") or {}).get("state", ""),
            "mission": org.get("mission_statement", ""),
            "classification": org.get("ntee_major") or org.get("ntee_minor") or "",
        })

    logger.info("Candid: %d funders returned for q=%r state=%s", len(results), keywords, state)
    return results
