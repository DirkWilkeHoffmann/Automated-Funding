"""LLM-based extraction and analysis."""

import json
import logging
from functools import lru_cache
from typing import Any, Dict, Optional

from openai import OpenAI

from utils.config import get_settings
from utils.constants import ELIGIBILITY_ORDER, LLM_PROMPT, LLM_SYSTEM_PROMPT
from utils.db.org_store import get_org_profile_text
from utils.utils_helpers import log_message

logger = logging.getLogger(__name__)

_MAX_CHARS = 30000
_MODEL_FAST = "gpt-4o-mini"
_MODEL_FULL = "gpt-4.1"


@lru_cache(maxsize=1)
def _cached_db_openai_key() -> Optional[str]:
    """Read OpenAI key from api_tokens table (cached). Returns None if not set."""
    try:
        from utils.db.client import get_supabase

        rows = (
            get_supabase()
            .table("api_tokens")
            .select("key_value")
            .eq("service", "openai")
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0]["key_value"].strip() if rows else None
    except Exception:
        return None


def clear_openai_key_cache() -> None:
    _cached_db_openai_key.cache_clear()


def _get_openai_key() -> Optional[str]:
    """DB key takes precedence over env var."""
    db_key = _cached_db_openai_key()
    if db_key:
        return db_key
    return (get_settings().openai_api_key or "").strip() or None


def get_client() -> Optional[OpenAI]:
    """Get OpenAI client, preferring the DB-stored key over the env var."""
    api_key = _get_openai_key()
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def call_llm_extract(text: str) -> Dict[str, Any]:
    """
    Extract funding information from text.

    Tries gpt-4o-mini first; falls back to gpt-4.1 if the result looks like an
    extraction failure (too many empty fields).
    """
    client = get_client()
    if client is None:
        return _empty_result("LLM not configured (no API key).", "LLM extraction skipped.")

    if len(text) > _MAX_CHARS:
        log_message(f"Text truncated from {len(text)} to {_MAX_CHARS} chars", "warning")
        half = _MAX_CHARS // 2
        text = text[:half] + "\n...[content truncated]...\n" + text[-half:]

    org_profile = get_org_profile_text()
    from utils.db.org_store import get_prompt_templates
    system_prompt, user_prompt_template = get_prompt_templates()
    prompt = user_prompt_template.format(org_profile=org_profile, text=text)

    result = _call_model(client, prompt, _MODEL_FAST, system_prompt=system_prompt)
    if _is_thin_result(result) and len(text) > 2000:
        log_message(f"Thin result from {_MODEL_FAST}; retrying with {_MODEL_FULL}", "warning")
        result = _call_model(client, prompt, _MODEL_FULL, system_prompt=system_prompt)
    return result


def _call_model(client: OpenAI, prompt: str, model: str, *, system_prompt: str = "") -> Dict[str, Any]:
    from utils.constants.llm import LLM_SYSTEM_PROMPT
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt or LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=60,
        )
        data = json.loads(resp.choices[0].message.content)

        normalized = {
            "applicant_types": data.get("applicant_types", []),
            "geographic_scope": data.get("geographic_scope", ""),
            "us_state_scope": data.get("us_state_scope", []),
            "beneficiary_focus": data.get("beneficiary_focus", []),
            "funding_range": data.get("funding_range", ""),
            "restrictions": data.get("restrictions", []),
            "application_status": data.get("application_status", "unclear"),
            "deadline": data.get("deadline", ""),
            "notes": data.get("notes", ""),
            "grant_type": data.get("grant_type", "other"),
            "eligibility": data.get("eligibility", "Low Match"),
            "evidence": data.get("evidence", ""),
        }

        if normalized["eligibility"] not in ELIGIBILITY_ORDER:
            log_message(
                f"Invalid eligibility from {model}: {normalized['eligibility']}; defaulting to 'Low Match'",
                "warning",
            )
            normalized["eligibility"] = "Low Match"

        for key in ["applicant_types", "us_state_scope", "beneficiary_focus", "restrictions"]:
            if isinstance(normalized[key], list):
                normalized[key] = "; ".join(normalized[key]) if normalized[key] else ""

        return normalized

    except json.JSONDecodeError as e:
        log_message(f"Invalid JSON from LLM ({model}): {e}", "error")
        return _empty_result(f"JSON parsing error: {e}", f"Could not parse LLM response: {e}")
    except Exception as e:
        log_message(f"LLM extraction failed ({model}): {e}", "error")
        return _empty_result(f"Extraction failed: {e}", f"LLM extraction failed: {e}")


def _is_thin_result(result: Dict[str, Any]) -> bool:
    """True when the extraction looks like a failure — too many key fields are empty."""
    important = ["applicant_types", "geographic_scope", "beneficiary_focus", "funding_range", "evidence"]
    empty_count = sum(1 for k in important if not result.get(k))
    return empty_count >= 3 or result.get("eligibility") not in ELIGIBILITY_ORDER


def _empty_result(notes: str, evidence: str) -> Dict[str, Any]:
    return {
        "applicant_types": "",
        "geographic_scope": "",
        "us_state_scope": "",
        "beneficiary_focus": "",
        "funding_range": "",
        "restrictions": "",
        "application_status": "unclear",
        "deadline": "",
        "notes": notes,
        "grant_type": "other",
        "eligibility": "Low Match",
        "evidence": evidence,
    }
