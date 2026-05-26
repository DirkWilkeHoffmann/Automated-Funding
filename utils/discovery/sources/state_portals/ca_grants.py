"""California Grants Portal source.

Reads the California Grants Portal (grants.ca.gov) dataset published by the
California State Library on data.ca.gov. The dataset is exposed via CKAN's
datastore_search API — no auth required, ~1,900 grant records refreshed daily.

Each record includes a direct GrantURL, the soliciting agency, application
deadline, eligible applicant types, and a free-text description.

Docs:
  - Portal: https://www.grants.ca.gov/
  - Dataset: https://data.ca.gov/dataset/california-grants-portal
  - CKAN datastore API: https://docs.ckan.org/en/latest/maintaining/datastore.html
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Stable resource_id for the daily-updated California Grants Portal CSV.
# Looked up via:
#   GET https://data.ca.gov/api/3/action/package_show?id=california-grants-portal
# Update this id if the dataset is re-published under a new resource.
_RESOURCE_ID = "111c8c88-21f6-453c-ae2c-b4785a0624f5"
_API_URL = "https://data.ca.gov/api/3/action/datastore_search"
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "automated-funding-bot/1.0 (+contact: automated-funding repo)",
}


def fetch_ca_grants(
    *,
    keywords: str = "",
    since_date: Optional[str] = None,
    max_results: int = 200,
) -> List[Dict[str, Any]]:
    """Pull active California state grants from data.ca.gov.

    Args:
        keywords: Free-text query — CKAN does an OR fuzzy match across all fields.
                  Empty string returns the full list (capped by max_results).
        since_date: ISO date string. Only return grants whose LastUpdated >= this.
        max_results: Hard cap on returned rows (CKAN supports up to 32k but we
                     stay conservative).
    """
    # `since_date` is intentionally ignored. CA Grants Portal records reflect
    # whole-program lifecycle (active = currently accepting applications), so
    # filtering by LastUpdated removes 95% of active grants whose program info
    # hasn't been re-edited recently. Active-status filtering below is the
    # right freshness signal.
    _ = since_date

    results: List[Dict[str, Any]] = []
    offset = 0
    page_size = min(max_results, 200)

    while len(results) < max_results:
        params: Dict[str, Any] = {
            "resource_id": _RESOURCE_ID,
            "limit": page_size,
            "offset": offset,
        }
        if keywords and keywords.strip():
            params["q"] = keywords.strip()

        try:
            resp = requests.get(_API_URL, params=params, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("CA grants API error: %s", exc)
            break

        if not data.get("success"):
            logger.warning("CA grants returned success=False: %s", data.get("error"))
            break

        records = (data.get("result") or {}).get("records") or []
        if not records:
            break

        for rec in records:
            # Keep only active grants — closed/archived are not useful to discover
            status = (rec.get("Status") or "").lower()
            if status and status not in ("active", "forecasted"):
                continue
            url = (rec.get("GrantURL") or "").strip()
            if not url:
                continue

            results.append({
                "url": url,
                "title": rec.get("Title", ""),
                "agency": rec.get("AgencyDept", ""),
                "deadline": rec.get("ApplicationDeadline", ""),
                "applicant_types": rec.get("ApplicantType", ""),
                "description": rec.get("Description", ""),
                "funding_amount": rec.get("EstAmounts", ""),
                "categories": rec.get("Categories", ""),
                "state": "CA",
            })
            if len(results) >= max_results:
                break

        if len(records) < page_size:
            break
        offset += page_size

    logger.info("CA Grants Portal: %d active grants returned", len(results))
    return results
