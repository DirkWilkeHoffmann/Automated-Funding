"""New York state grants source.

NY's Grants Gateway (grantsgateway.ny.gov) requires a login for most queries,
but the state's open data portal (data.ny.gov) publishes several public grant
datasets via CKAN's datastore_search API.

We pull from the "Grants and Bonds Awarded" dataset as the closest public
proxy. This is awards-data (already given) rather than open opportunities,
which means downstream URLs link to the awarding agency rather than an
application page — still useful for finding active funders by EIN/agency.

If NY publishes a public "open opportunities" dataset in the future, swap the
RESOURCE_ID below.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# NY Open Data — Grants and Bonds Awarded
# See: https://data.ny.gov/Government-Finance/Grants-and-Bonds-Awarded-Beginning-2004/m99r-2c2p
_DATASET_URL = "https://data.ny.gov/resource/m99r-2c2p.json"
_HEADERS = {"Accept": "application/json", "User-Agent": "automated-funding-bot/1.0"}


def fetch_ny_grants(
    *,
    keywords: str = "",
    since_date: Optional[str] = None,
    max_results: int = 200,
) -> List[Dict[str, Any]]:
    """Pull NY state grant award records from data.ny.gov (Socrata SoQL).

    Socrata SoQL supports:
      $where=date_executed>='YYYY-MM-DD'
      $q=<free text>
      $limit=<n>
    """
    where_clauses: List[str] = []
    if since_date:
        try:
            date.fromisoformat(since_date)
            where_clauses.append(f"date_executed >= '{since_date}'")
        except ValueError:
            logger.warning("NY grants: invalid since_date %r — ignoring", since_date)

    params: Dict[str, Any] = {"$limit": min(max_results, 1000), "$order": "date_executed DESC"}
    if where_clauses:
        params["$where"] = " AND ".join(where_clauses)
    if keywords and keywords.strip():
        params["$q"] = keywords.strip()

    try:
        resp = requests.get(_DATASET_URL, params=params, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        records = resp.json()
    except Exception as exc:
        logger.warning("NY grants API error: %s", exc)
        return []

    if not isinstance(records, list):
        logger.warning("NY grants: unexpected payload type %s", type(records))
        return []

    results: List[Dict[str, Any]] = []
    seen_agencies: set = set()
    for rec in records:
        # Each record is a single bond/grant award. We surface the awarding
        # agency's page rather than the award itself — that's the actionable
        # URL for a future applicant.
        agency = (rec.get("agency_name") or rec.get("agency") or "").strip()
        if not agency:
            continue
        # De-dupe by agency to keep volume manageable; a single agency may
        # have hundreds of awards but only one funder page.
        agency_key = agency.lower()
        if agency_key in seen_agencies:
            continue
        seen_agencies.add(agency_key)

        # Try to surface a useful URL — prefer any URL field, else search hint
        url = rec.get("url") or rec.get("agency_url") or ""
        if not url and agency:
            # Fall back to a state-search URL the user can click through
            url = f"https://www.ny.gov/search?q={agency.replace(' ', '+')}+grants"

        results.append({
            "url": url,
            "title": rec.get("project_title") or rec.get("project") or agency,
            "agency": agency,
            "deadline": "",
            "applicant_types": "",
            "description": rec.get("project_description", ""),
            "funding_amount": rec.get("amount_awarded") or rec.get("amount", ""),
            "categories": rec.get("category", ""),
            "state": "NY",
        })
        if len(results) >= max_results:
            break

    logger.info("NY data: %d awarding-agency entries returned", len(results))
    return results
