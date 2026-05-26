"""Texas state grants source.

Texas eGrants (egrants.gov.texas.gov) is the official state grants portal but
doesn't publish a public JSON API. We fall back to the Texas Open Data portal
(data.texas.gov, Socrata) which has several public grant-related datasets.

Specifically, this queries the "Awards Granted" dataset published by the Office
of the Governor, Criminal Justice Division — one of the few public state
datasets that covers grants to nonprofits.

This is a best-effort stub: extend by adding more dataset IDs as Texas
publishes them.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Office of the Governor — Criminal Justice Division grant awards
# Socrata dataset id (subject to change if the publisher rotates it)
_DATASET_URL = "https://data.texas.gov/resource/p4ed-w6fr.json"
_HEADERS = {"Accept": "application/json", "User-Agent": "automated-funding-bot/1.0"}


def fetch_tx_grants(
    *,
    keywords: str = "",
    since_date: Optional[str] = None,
    max_results: int = 200,
) -> List[Dict[str, Any]]:
    """Pull TX grant records via Socrata SoQL."""
    params: Dict[str, Any] = {"$limit": min(max_results, 1000)}
    if keywords and keywords.strip():
        params["$q"] = keywords.strip()

    try:
        resp = requests.get(_DATASET_URL, params=params, headers=_HEADERS, timeout=20)
        if resp.status_code == 404:
            # Dataset may have moved; degrade gracefully.
            logger.info("TX dataset returned 404 — adapter is a best-effort stub")
            return []
        resp.raise_for_status()
        records = resp.json()
    except Exception as exc:
        logger.warning("TX grants API error: %s", exc)
        return []

    if not isinstance(records, list):
        return []

    results: List[Dict[str, Any]] = []
    seen_agencies: set = set()
    for rec in records:
        agency = (rec.get("agency_name") or rec.get("granting_agency") or "Texas state grant").strip()
        agency_key = agency.lower()
        if agency_key in seen_agencies:
            continue
        seen_agencies.add(agency_key)

        url = rec.get("url") or f"https://egrants.gov.texas.gov/?q={agency.replace(' ', '+')}"

        results.append({
            "url": url,
            "title": rec.get("project_title") or agency,
            "agency": agency,
            "deadline": "",
            "applicant_types": "",
            "description": rec.get("project_description", ""),
            "funding_amount": rec.get("amount_awarded", ""),
            "state": "TX",
        })
        if len(results) >= max_results:
            break

    logger.info("TX data: %d entries returned", len(results))
    return results
