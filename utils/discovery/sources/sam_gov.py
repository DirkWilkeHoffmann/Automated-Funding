"""SAM.gov Opportunities API search module.

Requires a free API key from https://sam.gov/content/entity-information (register an account,
then generate a Public API key under "User Account" → "API Keys").

Store the key via POST /admin/tokens/sam_gov in the admin UI.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_SAM_GOV_SEARCH_URL = "https://api.sam.gov/opportunities/v2/search"
_PAUSE_SECONDS = 0.5


def search_sam_gov(
    *,
    keywords: str,
    api_key: str,
    posted_from: Optional[str] = None,
    max_results: int = 100,
) -> List[Dict[str, Any]]:
    """
    Search SAM.gov for federal contract/grant opportunities matching keywords.

    Args:
        keywords: Search terms (e.g. "hospice palliative care")
        api_key: SAM.gov Public API key (required)
        posted_from: ISO date string (YYYY-MM-DD) — only return notices posted on/after this date.
                     Defaults to 30 days ago.
        max_results: Maximum number of results to return.

    Returns:
        List of opportunity dicts with keys:
            opportunity_id, title, agency_name, posted_date, close_date,
            opportunity_type, opportunity_url, notice_id
    """
    if not api_key or not api_key.strip():
        raise ValueError("SAM.gov API key is required")

    if not posted_from:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        posted_from = since.strftime("%m/%d/%Y")
    else:
        try:
            dt = datetime.fromisoformat(posted_from)
            posted_from = dt.strftime("%m/%d/%Y")
        except ValueError:
            pass

    results: List[Dict[str, Any]] = []
    page = 0
    page_size = min(max_results, 100)

    # SAM.gov rejects requests with only postedFrom — it demands both ends of
    # the window. Default postedTo to today (MM/DD/YYYY format the API wants).
    posted_to = datetime.now(timezone.utc).strftime("%m/%d/%Y")

    while len(results) < max_results:
        params = {
            "api_key": api_key.strip(),
            "q": keywords,
            "postedFrom": posted_from,
            "postedTo": posted_to,
            "limit": page_size,
            "offset": page * page_size,
            "ptype": "g",  # grants only (not procurement contracts)
        }
        try:
            resp = requests.get(_SAM_GOV_SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("SAM.gov API request failed: %s", exc)
            break

        opportunities = data.get("opportunitiesData") or []
        if not opportunities:
            break

        for opp in opportunities:
            if len(results) >= max_results:
                break
            notice_id = opp.get("noticeId") or opp.get("id", "")
            title = opp.get("title", "")
            agency = opp.get("organizationHierarchy", [{}])
            agency_name = agency[0].get("name", "") if agency else opp.get("organizationName", "")
            resource_links = opp.get("resourceLinks") or []
            if not isinstance(resource_links, list):
                resource_links = []
            description = opp.get("description", "") or opp.get("synopsis", "") or ""
            results.append({
                "opportunity_id": notice_id,
                "title": title,
                "agency_name": agency_name,
                "posted_date": opp.get("postedDate", ""),
                "close_date": opp.get("responseDeadLine", ""),
                "opportunity_type": opp.get("type", ""),
                "naics_code": opp.get("naicsCode", ""),
                "set_aside_type": opp.get("typeOfSetAsideDescription", ""),
                "description": description,
                "opportunity_url": (
                    f"https://sam.gov/opp/{notice_id}/view"
                    if notice_id
                    else ""
                ),
                "notice_id": notice_id,
                "resource_links": resource_links,
            })

        if len(opportunities) < page_size:
            break

        page += 1
        time.sleep(_PAUSE_SECONDS)

    logger.info("SAM.gov search for %r returned %d results", keywords, len(results))
    return results


def sam_gov_to_scrape_urls(opportunities: List[Dict[str, Any]]) -> List[str]:
    """Extract scrape-ready SAM.gov opportunity page URLs."""
    urls = []
    for opp in opportunities:
        url = opp.get("opportunity_url", "")
        if url:
            urls.append(url)
    return urls
