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
    raw = org.get("website") or org.get("url") or ""
    if raw and raw.lower() not in ("n/a", "na", "none"):
        return raw if raw.startswith("http") else "https://" + raw
    return ""


def resolve_org_website(ein: str) -> str:
    """Fetch the org's registered website from the ProPublica detail endpoint.

    This makes one HTTP call per EIN and is intended to be called from a
    thread pool (see ProPublicaSource).  Returns an empty string on failure
    or when the API has no website recorded for this EIN.
    """
    if not ein:
        return ""
    try:
        resp = requests.get(
            f"{_BASE_URL}/organizations/{ein}.json",
            headers=_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        org = data.get("organization") or {}
        raw = (org.get("website") or org.get("url") or "").strip()
        if raw and raw.lower() not in ("n/a", "na", "none", ""):
            return raw if raw.startswith("http") else "https://" + raw
    except Exception as exc:
        logger.debug("ProPublica website lookup failed for EIN %s: %s", ein, exc)
    return ""


def foundations_to_scrape_urls(foundations: List[Dict[str, Any]]) -> List[str]:
    """Extract scrape-ready URLs from foundation records (website preferred, ProPublica fallback)."""
    urls = []
    for f in foundations:
        url = f.get("website") or f.get("propublica_url") or ""
        if url:
            urls.append(url)
    return urls


def fetch_latest_form_990(ein: str) -> Optional[Dict[str, Any]]:
    """Look up the most recent Form 990 PDF + structured data for an EIN.

    Returns a dict with keys: pdf_url, filing_year, form_type, filing (the raw
    structured filing dict from ProPublica's `filings_with_data`), org (the
    org-level metadata) — or None if the org has no machine-readable filings.

    The `filing` dict is what callers should pass to `synthesize_filing_text`
    when the PDF cannot be downloaded (ProPublica's PDFs sit behind
    Cloudflare and 403 server-side requests).
    """
    if not ein:
        return None
    try:
        resp = requests.get(
            f"{_BASE_URL}/organizations/{ein}.json", headers=_HEADERS, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("ProPublica org lookup failed for ein=%s: %s", ein, exc)
        return None

    org_meta = data.get("organization") or {}
    filings_with = data.get("filings_with_data") or []
    filings_without = data.get("filings_without_data") or []

    candidates: List[Dict[str, Any]] = []
    for f in filings_with:
        year = f.get("tax_prd_yr") or f.get("tax_period_year") or f.get("filing_year")
        if year is None:
            continue
        try:
            candidates.append({
                "pdf_url": f.get("pdf_url") or "",
                "filing_year": int(year),
                "form_type": f.get("formtype_str") or f.get("formtype") or "",
                "filing": f,
                "has_structured": True,
            })
        except (TypeError, ValueError):
            continue
    # Fall back to filings_without_data if we have no structured filings
    if not candidates:
        for f in filings_without:
            pdf_url = f.get("pdf_url") or f.get("pdf") or ""
            year = f.get("tax_prd_yr") or f.get("tax_period_year") or f.get("filing_year")
            if pdf_url and year:
                try:
                    candidates.append({
                        "pdf_url": pdf_url,
                        "filing_year": int(year),
                        "form_type": f.get("formtype_str") or f.get("formtype") or "",
                        "filing": f,
                        "has_structured": False,
                    })
                except (TypeError, ValueError):
                    continue

    if not candidates:
        return None
    candidates.sort(key=lambda c: c["filing_year"], reverse=True)
    top = candidates[0]
    top["org"] = org_meta
    return top


# Fields most useful to a grant-seeker; numeric IRS line items
_FILING_NUMERIC_FIELDS = [
    ("totrevenue", "Total revenue (year)"),
    ("totfuncexpns", "Total functional expenses (year)"),
    ("totassetsend", "Total assets (end of year)"),
    ("totliabend", "Total liabilities (end of year)"),
    ("totrcptperbks", "Total receipts per books"),
    ("grntspdtothr", "Grants paid to other organizations"),
    ("contrpdpbks", "Contributions/grants paid per books"),
    ("compofficers", "Compensation of officers"),
    ("pf_totexpns", "Total expenses (private foundation)"),
    ("fairmrktvalamt", "Fair market value of assets"),
    ("qlfydistribtot", "Qualifying distributions (total)"),
    ("grsinvstinctot", "Gross investment income (total)"),
    ("netinvstinc", "Net investment income"),
    ("distribamt", "Distribution amount (grants/qualifying distributions)"),
]


def synthesize_filing_text(top_filing: Dict[str, Any]) -> str:
    """Build a plain-text summary of a ProPublica filing record.

    Used when the underlying PDF can't be downloaded so we can still get
    grant signals out via the LLM extractor. Includes the org's NTEE category,
    address, and the most useful numeric line items from the filing.
    """
    org = top_filing.get("org") or {}
    filing = top_filing.get("filing") or {}
    lines: List[str] = []

    name = org.get("name") or ""
    ntee = org.get("ntee_code") or ""
    addr = org.get("address") or ""
    city = org.get("city") or ""
    state = org.get("state") or ""
    ein = org.get("ein") or ""

    lines.append(f"Form 990 Filing Summary — {name}")
    if ein:
        lines.append(f"EIN: {ein}")
    if ntee:
        lines.append(f"NTEE code: {ntee} (T-codes are grantmaking foundations)")
    if any([addr, city, state]):
        loc = ", ".join(p for p in [addr, city, state] if p)
        lines.append(f"Location: {loc}")

    year = top_filing.get("filing_year")
    form_type = top_filing.get("form_type") or filing.get("formtype_str") or ""
    if year:
        lines.append(f"Filing year: {year}")
    if form_type:
        lines.append(f"Form type: {form_type}")

    lines.append("")
    lines.append("Key financial line items (USD):")
    found_any = False
    for key, label in _FILING_NUMERIC_FIELDS:
        val = filing.get(key)
        if val is None or val == 0:
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        lines.append(f"  {label}: ${n:,}")
        found_any = True
    if not found_any:
        lines.append("  (no structured financial data available)")

    lines.append("")
    lines.append(
        "Source: ProPublica Nonprofit Explorer structured Form 990 data. "
        "Use these signals to characterise the funder's scale, focus, and grantmaking activity. "
        "Numeric values come straight from the IRS filing."
    )
    return "\n".join(lines)
