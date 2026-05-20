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

    parts = []
    if org.get("name"):
        parts.append(f"Organization: {org['name']}")
    if org.get("ein"):
        parts.append(f"EIN: {org['ein']}")
    city = org.get("city", "").strip()
    state = org.get("state", "").strip()
    location = ", ".join(filter(None, [city, state]))
    if location:
        parts.append(f"Location: {location}")
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
