"""
Grants.gov — federal grant opportunity search.

Searches the Grants.gov REST API for open federal grant opportunities.
No API key required.

API docs: https://www.grants.gov/web/grants/s2s/grantor/searchOpportunities.html
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://apply07.grants.gov/grantsws/rest/opportunities/search/"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "automated-funding-bot/1.0",
}


def search_federal_grants(
    *,
    keywords: str,
    eligible_applicants: Optional[List[str]] = None,
    posted_from: Optional[str] = None,
    max_results: int = 100,
) -> List[Dict[str, Any]]:
    """
    Search Grants.gov for open federal grant opportunities.

    Args:
        keywords: Search terms (e.g. "hospice", "palliative care", "arts education").
        eligible_applicants: Grants.gov eligibility codes to filter by.
            Common codes:
              "12" = Nonprofits with 501(c)(3) status
              "13" = Nonprofits without 501(c)(3) status
              "25" = Private institutions of higher education
        max_results: Maximum number of results to return.

    Returns:
        List of grant dicts with keys: opportunity_id, opportunity_title,
        agency_name, post_date, close_date, estimated_funding, opportunity_url.
    """
    body: Dict[str, Any] = {
        "keyword": keywords,
        "oppStatuses": "posted",
        "rows": min(max_results, 100),
        "startRecordNum": 0,
    }
    if eligible_applicants:
        body["eligibilities"] = eligible_applicants
    if posted_from:
        body["postDateFrom"] = posted_from

    try:
        resp = requests.post(_SEARCH_URL, json=body, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("Grants.gov API error: %s", exc)
        return []

    opportunities = data.get("oppHits") or []
    results = []
    for opp in opportunities:
        results.append(
            {
                "opportunity_id": opp.get("id", ""),
                "opportunity_number": opp.get("number", ""),
                "opportunity_title": opp.get("title", ""),
                "agency_name": opp.get("agencyName", ""),
                "post_date": opp.get("openDate", ""),
                "close_date": opp.get("closeDate", ""),
                "estimated_funding": opp.get("estimatedFunding"),
                "opportunity_url": f"https://grants.gov/search-results-detail/{opp.get('id', '')}",
                "synopsis": opp.get("synopsis", ""),
            }
        )

    return results[:max_results]


def federal_grants_to_scrape_urls(grants: List[Dict[str, Any]]) -> List[str]:
    """Return Grants.gov opportunity page URLs ready for scraping."""
    return [g["opportunity_url"] for g in grants if g.get("opportunity_url")]
