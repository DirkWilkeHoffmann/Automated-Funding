"""Organization profile store.

Reads the single org profile from the organizations table and provides
a formatted string for injection into LLM prompts.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from utils.db.client import get_supabase
from utils.utils_helpers import log_message

logger = logging.getLogger(__name__)

_ORG_PROFILE_PLACEHOLDER = (
    "Organization: (not configured)\n"
    "Please insert your organization profile in the Supabase organizations table."
)


@lru_cache(maxsize=1)
def _get_org_cached() -> Optional[dict]:
    try:
        response = get_supabase().table("organizations").select("*").limit(1).execute()
        rows = response.data or []
        return rows[0] if rows else None
    except Exception as exc:
        log_message(f"Could not load org profile: {exc}", "warning")
        return None


def get_org_profile_text() -> str:
    """Return a formatted org profile string for LLM prompt injection."""
    org = _get_org_cached()
    if not org:
        return _ORG_PROFILE_PLACEHOLDER

    def _join(v) -> str:
        if isinstance(v, list):
            return ", ".join(str(x).strip() for x in v if str(x).strip())
        return str(v or "").strip()

    parts = []
    if org.get("name"):
        parts.append(f"Organization: {org['name']}")
    if org.get("ein"):
        parts.append(f"EIN: {org['ein']}")

    # ── Geography (Phase 10) — source of truth for fund geo matching ──────
    # The LLM's GEOGRAPHY RULE references service_countries and service_regions.
    # We surface these PROMINENTLY before the legacy `Location`/`Service area
    # (states)` lines so the LLM doesn't anchor on the US-only fields when an
    # org also operates internationally.
    #
    # Country names are stored as FULL human-readable names (e.g.
    # "United States", "South Africa"). We pass them verbatim — the LLM
    # reasons better about "South Africa" than an alpha-2 code "ZA".
    hq_country = (org.get("country") or "").strip()
    city = (org.get("city") or "").strip()
    state = (org.get("state") or "").strip()
    hq_pieces = [p for p in (city, state, hq_country) if p]
    if hq_pieces:
        parts.append(f"HQ location: {', '.join(hq_pieces)}")

    svc_countries = org.get("service_countries") or []
    if isinstance(svc_countries, list) and svc_countries:
        names = ", ".join(str(c).strip() for c in svc_countries if str(c).strip())
        if names:
            parts.append(f"Countries the org operates in (service_countries): {names}")

    svc_regions = org.get("service_regions") or {}
    if isinstance(svc_regions, dict) and svc_regions:
        # Only emit region entries whose key exactly matches a known service_country
        # (case-insensitive). This filters out stale abbreviated keys (e.g. "SO",
        # "UN") that ended up in the DB from earlier data migrations and would
        # confuse the LLM's geography matching.
        valid_country_names = {str(c).strip().lower(): str(c).strip() for c in svc_countries if str(c).strip()}
        region_lines = []
        for ctry, regions in svc_regions.items():
            canonical = valid_country_names.get(str(ctry).strip().lower())
            if canonical is None:
                continue  # Skip stale or unrecognised keys
            if isinstance(regions, list) and regions:
                region_lines.append(
                    f"  {canonical}: {', '.join(str(r).strip() for r in regions if str(r).strip())}"
                )
        if region_lines:
            parts.append("Sub-regions per country (service_regions):\n" + "\n".join(region_lines))

    # Surface legal registrations immediately after geography so the LLM
    # sees them while still in the geographic/legal context frame, before
    # anchoring on mission/program text.
    if org.get("accreditations"):
        a = _join(org["accreditations"])
        if a:
            parts.append(f"Legal registrations / accreditations: {a}")

    if org.get("mission"):
        parts.append(f"Mission: {org['mission']}")
    if org.get("services"):
        services = org["services"]
        if isinstance(services, list):
            services = ", ".join(services)
        parts.append(f"Services: {services}")
    if org.get("annual_income"):
        parts.append(f"Annual income: ${org['annual_income']:,}")
    if org.get("staff_count"):
        parts.append(f"Staff: {org['staff_count']}")
    if org.get("volunteer_count"):
        parts.append(f"Volunteers: {org['volunteer_count']}")

    # Phase 3 fields — give the LLM scorer the policy context too.
    if org.get("ntee_codes"):
        ntee = org["ntee_codes"]
        if isinstance(ntee, list):
            ntee = ", ".join(ntee)
        parts.append(f"NTEE focus areas: {ntee}")
    if org.get("service_states"):
        ss = org["service_states"]
        if isinstance(ss, list):
            ss = ", ".join(ss)
        parts.append(f"Service area (states): {ss}")
    if org.get("applicant_types"):
        at = org["applicant_types"]
        if isinstance(at, list):
            at = ", ".join(at)
        parts.append(f"Applicant types: {at}")
    if org.get("accepts_unsolicited") is False:
        parts.append("Accepts unsolicited proposals: NO (invitation-only funders only)")
    if org.get("can_cost_share") is False:
        parts.append("Can provide cost-share/matching funds: NO")
    if org.get("min_grant_size") or org.get("max_grant_size"):
        lo = org.get("min_grant_size")
        hi = org.get("max_grant_size")
        cur = (org.get("currency") or "USD").strip().upper() or "USD"
        symbol = "$" if cur == "USD" else f"{cur} "
        if lo and hi:
            parts.append(f"Target grant size: {symbol}{lo:,}–{symbol}{hi:,}")
        elif lo:
            parts.append(f"Minimum useful grant size: {symbol}{lo:,}")
        elif hi:
            parts.append(f"Maximum needed grant size: {symbol}{hi:,}")

    # Phase 9 — structured profile fields. Each block is appended only when
    # present so partial profiles render cleanly.
    if org.get("org_type_description"):
        parts.append(f"Org type: {org['org_type_description']}")
    if org.get("service_area_description"):
        parts.append(f"Service area (detail): {org['service_area_description']}")
    if org.get("beneficiaries"):
        b = _join(org["beneficiaries"])
        if b:
            parts.append(f"Beneficiaries served: {b}")
    if org.get("programs"):
        p = _join(org["programs"])
        if p:
            parts.append(f"Programs: {p}")
    if org.get("target_outcomes"):
        t = _join(org["target_outcomes"])
        if t:
            parts.append(f"Target outcomes: {t}")
    if org.get("partner_orgs"):
        po = _join(org["partner_orgs"])
        if po:
            parts.append(f"Partner organisations: {po}")
    if org.get("income_sources"):
        i = _join(org["income_sources"])
        if i:
            parts.append(f"Income sources: {i}")
    if org.get("founded_year"):
        parts.append(f"Founded: {org['founded_year']}")
    if org.get("currency") and (org.get("currency") or "").strip().upper() != "USD":
        parts.append(f"Reporting currency: {org['currency']}")

    return "\n".join(parts) if parts else _ORG_PROFILE_PLACEHOLDER


def get_prompt_templates() -> tuple[str, str]:
    """Return (system_prompt, user_prompt_template) from DB, falling back to defaults."""
    from utils.constants.llm import LLM_PROMPT, LLM_SYSTEM_PROMPT
    org = _get_org_cached()
    system = (org.get("ai_system_prompt") or "").strip() if org else ""
    user = (org.get("ai_user_prompt") or "").strip() if org else ""
    return (system or LLM_SYSTEM_PROMPT, user or LLM_PROMPT)


def clear_org_cache() -> None:
    _get_org_cached.cache_clear()
