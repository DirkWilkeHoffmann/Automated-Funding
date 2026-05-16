"""LLM-based extraction and analysis."""

import json
import logging
import re
from typing import Any, Dict, Optional

from openai import OpenAI

from utils.config import get_settings
from utils.constants import ELIGIBILITY_ORDER, LLM_PROMPT
from utils.utils_helpers import log_message

logger = logging.getLogger(__name__)


def get_client() -> Optional[OpenAI]:
    """Get OpenAI client if API key is configured."""
    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def call_llm_extract(text: str) -> Dict[str, Any]:
    """
    Extract funding information from text using GPT-4.

    Returns a dict with keys:
    - applicant_types
    - geographic_scope
    - beneficiary_focus
    - funding_range
    - restrictions
    - application_status
    - deadline
    - notes
    - eligibility
    - evidence
    """
    client = get_client()
    if client is None:
        return {
            "applicant_types": "",
            "geographic_scope": "",
            "beneficiary_focus": "",
            "funding_range": "",
            "restrictions": "",
            "application_status": "unclear",
            "deadline": "",
            "notes": "LLM not configured (no API key).",
            "eligibility": "Low Match",
            "evidence": "LLM extraction skipped (no API key).",
        }

    max_chars = 50000
    if len(text) > max_chars:
        log_message(f"Text truncated from {len(text)} to {max_chars} chars", "warning")
        text = text[: max_chars // 2] + "\n...[content truncated]...\n" + text[-max_chars // 2 :]

    prompt = LLM_PROMPT.replace("{text}", text)

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at evaluating charity funding eligibility. You extract structured data and provide accurate eligibility assessments based on specific criteria.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        output = resp.choices[0].message.content.strip()
        output = re.sub(r"^```json\s*|\s*```$", "", output, flags=re.MULTILINE)
        data = json.loads(output)

        normalized = {
            "applicant_types": data.get("applicant_types", []),
            "geographic_scope": data.get("geographic_scope", ""),
            "beneficiary_focus": data.get("beneficiary_focus", []),
            "funding_range": data.get("funding_range", ""),
            "restrictions": data.get("restrictions", []),
            "application_status": data.get("application_status", "unclear"),
            "deadline": data.get("deadline", ""),
            "notes": data.get("notes", ""),
            "eligibility": data.get("eligibility", "Low Match"),
            "evidence": data.get("evidence", ""),
        }

        if normalized["eligibility"] not in ELIGIBILITY_ORDER:
            log_message(
                f"Invalid eligibility value from LLM: {normalized['eligibility']}; defaulting to 'Low Match'",
                "warning",
            )
            normalized["eligibility"] = "Low Match"

        for key in ["applicant_types", "beneficiary_focus", "restrictions"]:
            if isinstance(normalized[key], list):
                normalized[key] = "; ".join(normalized[key]) if normalized[key] else ""

        return normalized

    except json.JSONDecodeError as e:
        log_message(f"Invalid JSON from LLM: {e}", "error")
        return {
            "applicant_types": "",
            "geographic_scope": "",
            "beneficiary_focus": "",
            "funding_range": "",
            "restrictions": "",
            "application_status": "unclear",
            "deadline": "",
            "notes": f"JSON parsing error: {str(e)}",
            "eligibility": "Low Match",
            "evidence": f"Error: Could not parse LLM response - {str(e)}",
        }
    except Exception as e:
        log_message(f"LLM extraction failed: {e}", "error")
        return {
            "applicant_types": "",
            "geographic_scope": "",
            "beneficiary_focus": "",
            "funding_range": "",
            "restrictions": "",
            "application_status": "unclear",
            "deadline": "",
            "notes": f"Extraction failed: {str(e)}",
            "eligibility": "Low Match",
            "evidence": f"Error: LLM extraction failed - {str(e)}",
        }
