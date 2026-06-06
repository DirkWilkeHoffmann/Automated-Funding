"""LLM-based extraction and analysis."""

import json
import logging
import os
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

from openai import OpenAI

from utils.config import get_settings
from utils.constants import ELIGIBILITY_ORDER, LLM_PROMPT, LLM_SYSTEM_PROMPT
from utils.db.org_store import get_org_profile_text
from utils.utils_helpers import log_message

logger = logging.getLogger(__name__)

_MAX_CHARS = 30000
# _MODEL_FAST = "gpt-4o-mini"
_MODEL_FAST = "gpt-4o"
_MODEL_FULL = "gpt-4.1"

# Set to True to write every LLM call + response to logs/ in the repo root.
LLM_DEBUG_LOGGING = True
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_PATH = os.path.join(_REPO_ROOT, "logs", "llm_debug.log")
_ANALYSIS_LOG_DIR = os.path.join(_REPO_ROOT, "logs", "analysis")
# Phase 10 — consolidated per-fund log. Replaces the split scrape/analysis
# logs going forward. One file per fund with: scrape text + LLM phase 1 +
# LLM phase 2 + final extracted fields, all in one place.
_FUND_LOG_DIR = os.path.join(_REPO_ROOT, "logs", "funds")


def write_fund_log_section(fund_url: str, section_title: str, body: str, *, reset: bool = False) -> None:
    """Append a labelled section to the consolidated per-fund log.

    `reset=True` truncates the file before writing (used by the scrape worker
    at the start of a fresh scrape so old data doesn't accumulate).
    """
    if not LLM_DEBUG_LOGGING or not fund_url:
        return
    try:
        from utils.utils_helpers import safe_filename_from_url
        os.makedirs(_FUND_LOG_DIR, exist_ok=True)
        path = os.path.join(_FUND_LOG_DIR, f"{safe_filename_from_url(fund_url)}.txt")
        mode = "w" if reset else "a"
        sep = "=" * 100
        ts = datetime.now().isoformat()
        with open(path, mode, encoding="utf-8") as f:
            f.write(f"\n{sep}\n{section_title}  [{ts}]\n{sep}\n{body.rstrip()}\n")
    except Exception as exc:
        logger.warning("Could not write fund log for %s: %s", fund_url, exc)


def _write_debug_log(
    *,
    fund_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response_text: str,
    eligibility: str,
) -> None:
    if not LLM_DEBUG_LOGGING:
        return
    try:
        from utils.utils_helpers import safe_filename_from_url

        sep = "=" * 100
        thin = "-" * 100
        ts = datetime.now().isoformat()

        lines = [
            "",
            sep,
            f"TIMESTAMP  : {ts}",
            f"FUND URL   : {fund_url}",
            f"MODEL      : {model}",
            f"ELIGIBILITY: {eligibility}",
            thin,
            "── SYSTEM PROMPT ──",
            system_prompt.strip(),
            thin,
            "── USER PROMPT (org profile + scraped text) ──",
            user_prompt.strip(),
            thin,
            "── RAW LLM RESPONSE ──",
            response_text.strip(),
            sep,
            "",
        ]
        entry = "\n".join(lines)

        # 1. Append to the global rolling log.
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry)

        # 2. Phase 10 consolidated per-fund log — all phases land in one file
        # at logs/funds/{url_safe}.txt. The scrape worker writes the scrape
        # section first (with reset=True), then each LLM phase appends here.
        phase_label = "LLM PHASE 2" if "phase2" in model.lower() else "LLM PHASE 1"
        write_fund_log_section(
            fund_url,
            f"{phase_label} — model={model}, eligibility={eligibility}",
            "\n".join([
                "── SYSTEM PROMPT ──",
                system_prompt.strip(),
                "── USER PROMPT ──",
                user_prompt.strip(),
                "── RAW LLM RESPONSE ──",
                response_text.strip(),
            ]),
        )

        # 3. (legacy) Per-URL analysis log — kept for backwards compat. Phase 1
        # truncates (w); Phase 2 appends (a). Deprecated in favour of the
        # consolidated log above; will be removed once the operator confirms
        # the new layout works for them.
        if fund_url:
            os.makedirs(_ANALYSIS_LOG_DIR, exist_ok=True)
            url_safe = safe_filename_from_url(fund_url)
            mode = "a" if "phase2" in model.lower() else "w"
            with open(os.path.join(_ANALYSIS_LOG_DIR, f"{url_safe}.txt"), mode, encoding="utf-8") as f:
                f.write(entry)

    except Exception as exc:
        logger.warning("Could not write LLM debug log: %s", exc)


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


def stage1_extract(text: str, *, client: "OpenAI", fund_url: str = "") -> Dict[str, Any]:
    """Stage 1: extract objective fund facts. No org profile in prompt."""
    from utils.constants.llm import LLM_PROMPT_STAGE1, LLM_SYSTEM_PROMPT

    if len(text) > _MAX_CHARS:
        half = _MAX_CHARS // 2
        text = text[:half] + "\n...[content truncated]...\n" + text[-half:]

    prompt = LLM_PROMPT_STAGE1.format(text=text)
    _ALLOWED_STATUS = {"open", "closed", "paused", "rolling", "seasonal", "unclear"}

    for model in (_MODEL_FAST, _MODEL_FULL):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
                timeout=60,
            )
            response_text = resp.choices[0].message.content
            data = json.loads(response_text)

            raw_status = str(data.get("application_status", "") or "").strip().lower()
            status = raw_status if raw_status in _ALLOWED_STATUS else "unclear"

            result = {
                "fund_name_extracted": (data.get("fund_name") or "").strip(),
                "funder_name": (data.get("funder_name") or "").strip(),
                "geographic_scope": (data.get("geographic_scope") or "").strip(),
                "us_state_scope": data.get("us_state_scope") or [],
                "applicant_types_list": data.get("applicant_types") or [],
                "topic_areas": data.get("topic_areas") or [],
                "beneficiaries_list": data.get("beneficiaries") or [],
                "funding_range": (data.get("funding_range") or "").strip(),
                "deadline": (data.get("deadline") or "").strip(),
                "application_status": status,
                "restrictions_list": data.get("restrictions") or [],
                "grant_type": (data.get("grant_type") or "other").strip(),
                "application_process": (data.get("application_process") or "").strip(),
                "notes": (data.get("notes") or "").strip(),
            }

            important = ["geographic_scope", "applicant_types_list", "topic_areas", "funding_range"]
            empty_count = sum(1 for k in important if not result.get(k))
            if empty_count >= 3 and model == _MODEL_FAST and len(text) > 2000:
                log_message(f"Thin Stage 1 result from {model}; retrying with {_MODEL_FULL}", "warning")
                continue

            write_fund_log_section(
                fund_url,
                f"STAGE 1 EXTRACTION — model={model}",
                f"── PROMPT ──\n{prompt[:2000]}\n── RESPONSE ──\n{response_text}",
            )
            return result

        except json.JSONDecodeError as exc:
            log_message(f"Stage 1 JSON error ({model}): {exc}", "error")
        except Exception as exc:
            log_message(f"Stage 1 extraction failed ({model}): {exc}", "error")
            break

    return {
        "fund_name_extracted": "", "funder_name": "", "geographic_scope": "",
        "us_state_scope": [], "applicant_types_list": [], "topic_areas": [],
        "beneficiaries_list": [], "funding_range": "", "deadline": "",
        "application_status": "unclear", "restrictions_list": [],
        "grant_type": "other", "application_process": "", "notes": "",
    }


def stage2_evaluate(
    stage1_facts: Dict[str, Any],
    org_profile: str,
    geo_verdict: Dict[str, str],
    *,
    client: "OpenAI",
    fund_url: str = "",
) -> Dict[str, Any]:
    """Stage 2: score eligibility rubric from Stage 1 facts + org profile."""
    from utils.constants.llm import LLM_PROMPT_STAGE2, LLM_SYSTEM_PROMPT

    def _join(lst) -> str:
        if isinstance(lst, list):
            return "; ".join(str(x) for x in lst if x) or "Not stated"
        return str(lst or "Not stated")

    geo_verdict_text = (
        f"{geo_verdict.get('verdict', 'unknown').upper()} — {geo_verdict.get('evidence', '')}"
    )

    prompt = LLM_PROMPT_STAGE2.format(
        org_profile=org_profile,
        fund_name=stage1_facts.get("fund_name_extracted") or "Not stated",
        funder_name=stage1_facts.get("funder_name") or "Not stated",
        geographic_scope=stage1_facts.get("geographic_scope") or "Not stated",
        geo_verdict_text=geo_verdict_text,
        applicant_types=_join(stage1_facts.get("applicant_types_list")),
        topic_areas=_join(stage1_facts.get("topic_areas")),
        beneficiaries=_join(stage1_facts.get("beneficiaries_list")),
        funding_range=stage1_facts.get("funding_range") or "Not stated",
        application_status=stage1_facts.get("application_status") or "unclear",
        restrictions=_join(stage1_facts.get("restrictions_list")),
        grant_type=stage1_facts.get("grant_type") or "other",
    )

    try:
        resp = client.chat.completions.create(
            model=_MODEL_FULL,
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=60,
        )
        response_text = resp.choices[0].message.content
        data = json.loads(response_text)

        rubric = _normalize_rubric(data.get("rubric"))
        evidence = (data.get("evidence") or "").strip()

        write_fund_log_section(
            fund_url,
            f"STAGE 2 EVALUATION — model={_MODEL_FULL}",
            f"── PROMPT ──\n{prompt[:2000]}\n── RESPONSE ──\n{response_text}",
        )

        return {
            "match_rubric": rubric,
            "eligibility": data.get("eligibility", "Low Match"),
            "evidence": evidence,
        }
    except json.JSONDecodeError as exc:
        log_message(f"Stage 2 JSON error: {exc}", "error")
    except Exception as exc:
        log_message(f"Stage 2 evaluation failed: {exc}", "error")

    return {"match_rubric": {}, "eligibility": "unclear", "evidence": ""}


def call_llm_extract(text: str, fund_url: str = "") -> Dict[str, Any]:
    """Orchestrate Stage 1 extraction → geography check → Stage 2 evaluation → Phase 2 enrichment.

    Public API unchanged. Stage 1 extracts fund facts without org data (eliminates template
    echo). Python checks geography deterministically. Stage 2 evaluates eligibility from
    clean facts + org profile.
    """
    from utils.constants.llm import ELIGIBILITY_ORDER, PHASE2_PROMOTE_TIERS

    client = get_client()
    if client is None:
        return _empty_result("LLM not configured (no API key).", "LLM extraction skipped.")

    if len(text) > _MAX_CHARS:
        log_message(f"Text truncated from {len(text)} to {_MAX_CHARS} chars", "warning")
        half = _MAX_CHARS // 2
        text = text[:half] + "\n...[content truncated]...\n" + text[-half:]

    # ── Stage 1: fact extraction (no org profile in prompt) ───────────────
    s1 = stage1_extract(text, client=client, fund_url=fund_url)

    # ── Deterministic geography check ─────────────────────────────────────
    from utils.db.org_store import get_prompt_templates, _get_org_cached
    _org = _get_org_cached() or {}
    _svc_countries = [str(c).strip() for c in (_org.get("service_countries") or []) if str(c).strip()]
    _svc_regions: Dict[str, list] = _org.get("service_regions") or {}
    geo_verdict = _compute_geography_verdict(
        str(s1.get("geographic_scope", "") or ""),
        service_countries=_svc_countries,
        service_regions=_svc_regions,
    )

    # ── Stage 2: eligibility evaluation (clean facts + org profile) ───────
    org_profile = get_org_profile_text()
    system_prompt, _ = get_prompt_templates()
    s2 = stage2_evaluate(s1, org_profile, geo_verdict, client=client, fund_url=fund_url)

    # ── Merge geography verdict + derive deterministic tier ────────────────
    rubric = {**_normalize_rubric(s2.get("match_rubric")), "geography": geo_verdict}
    tier = _tier_from_rubric(rubric)
    if tier not in ELIGIBILITY_ORDER:
        tier = "Low Match"

    # ── Phase 2 enrichment (only for promising tiers) ─────────────────────
    evidence = s2.get("evidence", "")
    if tier in PHASE2_PROMOTE_TIERS:
        phase2 = _phase2_enrich(
            client,
            text=text,
            org_profile=org_profile,
            phase1_result={"evidence": evidence, "eligibility": tier},
            system_prompt=system_prompt,
            fund_url=fund_url,
        )
        if phase2:
            evidence = _format_rich_evidence(
                phase1_evidence=evidence,
                tier=tier,
                phase2=phase2,
            )

    # ── Flatten Stage 1 lists → semicolon strings (existing DB schema) ────
    def _join_list(v) -> str:
        if isinstance(v, list):
            return "; ".join(str(x) for x in v if x)
        return str(v or "")

    result: Dict[str, Any] = {
        "applicant_types": _join_list(s1.get("applicant_types_list")),
        "geographic_scope": s1.get("geographic_scope", ""),
        "us_state_scope": _join_list(s1.get("us_state_scope")),
        "beneficiary_focus": _join_list(s1.get("beneficiaries_list")),
        "funding_range": s1.get("funding_range", ""),
        "restrictions": _join_list(s1.get("restrictions_list")),
        "application_status": s1.get("application_status", "unclear"),
        "deadline": s1.get("deadline", ""),
        "notes": s1.get("notes", ""),
        "grant_type": s1.get("grant_type", "other"),
        "funder_name": s1.get("funder_name", ""),
        "topic_areas": _join_list(s1.get("topic_areas")),
        "stage1_fund_name": s1.get("fund_name_extracted", ""),
        "match_rubric": rubric,
        "eligibility": tier,
        "evidence": evidence,
    }
    if result["eligibility"] not in ELIGIBILITY_ORDER:
        result["eligibility"] = "Low Match"
    return result


def _phase2_enrich(
    client: OpenAI,
    *,
    text: str,
    org_profile: str,
    phase1_result: Dict[str, Any],
    system_prompt: str = "",
    fund_url: str = "",
) -> Optional[Dict[str, Any]]:
    """Run the Phase 2 enrichment LLM call. Returns the parsed dict, or None on failure."""
    from utils.constants.llm import LLM_PROMPT_PHASE2, LLM_SYSTEM_PROMPT

    phase1_verdict = (phase1_result.get("evidence") or "").strip() or (
        f"VERDICT: {phase1_result.get('eligibility', 'Low Match')} — (no detail captured in Phase 1)"
    )
    prompt = LLM_PROMPT_PHASE2.format(
        org_profile=org_profile,
        text=text,
        phase1_verdict_line=phase1_verdict,
    )

    try:
        resp = client.chat.completions.create(
            model=_MODEL_FAST,
            messages=[
                {"role": "system", "content": system_prompt or LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=60,
        )
        response_text = resp.choices[0].message.content
        data = json.loads(response_text)

        _write_debug_log(
            fund_url=fund_url,
            model=f"{_MODEL_FAST} (phase2)",
            system_prompt=system_prompt or LLM_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_text=response_text,
            eligibility=phase1_result.get("eligibility", ""),
        )
        return data
    except json.JSONDecodeError as exc:
        log_message(f"Phase 2 invalid JSON: {exc}", "warning")
        return None
    except Exception as exc:
        log_message(f"Phase 2 enrichment failed: {exc}", "warning")
        return None


def _format_rich_evidence(*, phase1_evidence: str, tier: str, phase2: Dict[str, Any]) -> str:
    """Concatenate Phase 1 verdict + Phase 2 structured enrichment into a single text block."""
    lines: list[str] = []

    # VERDICT — always use the deterministic tier; extract reason from phase1_evidence
    _p1 = phase1_evidence.strip()
    _reason = ""
    if " — " in _p1:
        _reason = _p1.split(" — ", 1)[1].strip()
    elif _p1.upper().startswith("VERDICT:"):
        rest = _p1[len("VERDICT:"):].strip()
        if " — " in rest:
            _reason = rest.split(" — ", 1)[1].strip()
    verdict_line = tier + (f" — {_reason}" if _reason else "")
    lines.append("=== VERDICT ===")
    lines.append(verdict_line)
    lines.append("")

    # WHY IT FITS
    why = phase2.get("why_it_fits") or []
    if isinstance(why, list) and why:
        lines.append("=== WHY IT FITS ===")
        for w in why:
            lines.append(f"- {str(w).strip()}")
        lines.append("")

    # PAST GRANTEES
    grantees = phase2.get("past_grantees") or []
    if isinstance(grantees, list) and grantees:
        lines.append("=== PAST GRANTEES (similar to your org) ===")
        for g in grantees[:3]:
            if isinstance(g, dict):
                name = (g.get("name") or "").strip()
                amt = (g.get("amount") or "").strip()
                proj = (g.get("project") or "").strip()
                pieces = [p for p in (name, amt, proj) if p]
                lines.append(f"- {' — '.join(pieces)}")
            else:
                lines.append(f"- {str(g).strip()}")
        lines.append("")

    # TYPICAL GRANT SIZE
    tgs = (phase2.get("typical_grant_size") or "").strip()
    if tgs and tgs.lower() not in {"not stated", "not inferable from page"}:
        lines.append("=== TYPICAL GRANT SIZE ===")
        lines.append(tgs)
        lines.append("")

    # APPLICATION PROCESS
    ap = (phase2.get("application_process") or "").strip()
    if ap:
        lines.append("=== APPLICATION PROCESS ===")
        lines.append(ap)
        lines.append("")

    # STRATEGIC ANGLE
    sa = (phase2.get("strategic_angle") or "").strip()
    if sa:
        lines.append("=== STRATEGIC ANGLE ===")
        lines.append(sa)
        lines.append("")

    # CONCERNS
    concerns = phase2.get("concerns") or []
    if isinstance(concerns, list) and concerns:
        lines.append("=== CONCERNS ===")
        for c in concerns:
            lines.append(f"- {str(c).strip()}")
        lines.append("")
    else:
        lines.append("=== CONCERNS ===")
        lines.append("No significant concerns identified")
        lines.append("")

    # NEXT STEP
    ns = (phase2.get("next_step") or "").strip()
    if ns:
        lines.append("=== NEXT STEP ===")
        lines.append(ns)

    return "\n".join(lines).rstrip()


# Maps continental scope terms to a continent identifier.
# Sorted longest-first so "sub-saharan africa" matches before "africa".
_CONTINENTAL_TERMS: List[tuple] = sorted([
    ("sub-saharan africa", "africa"),
    ("east africa", "africa"),
    ("eastern africa", "africa"),
    ("southern africa", "africa"),
    ("west africa", "africa"),
    ("western africa", "africa"),
    ("north africa", "africa"),
    ("northern africa", "africa"),
    ("central africa", "africa"),
    ("latin america", "latin america"),
    ("central america", "latin america"),
    ("south america", "latin america"),
    ("north america", "north america"),
    ("southeast asia", "asia"),
    ("south asia", "asia"),
    ("east asia", "asia"),
    ("middle east", "middle east"),
    ("africa", "africa"),
    ("asia", "asia"),
    ("europe", "europe"),
], key=lambda x: -len(x[0]))

# Maps country (lowercase) to continent identifier.
_COUNTRY_CONTINENT: Dict[str, str] = {
    "south africa": "africa", "kenya": "africa", "namibia": "africa",
    "ethiopia": "africa", "nigeria": "africa", "ghana": "africa",
    "tanzania": "africa", "uganda": "africa", "zimbabwe": "africa",
    "mozambique": "africa", "zambia": "africa", "malawi": "africa",
    "botswana": "africa", "rwanda": "africa", "senegal": "africa",
    "cameroon": "africa", "angola": "africa", "egypt": "africa",
    "honduras": "latin america", "mexico": "latin america",
    "guatemala": "latin america", "el salvador": "latin america",
    "nicaragua": "latin america", "costa rica": "latin america",
    "panama": "latin america", "colombia": "latin america",
    "brazil": "latin america", "peru": "latin america",
    "united states": "north america", "canada": "north america",
    "india": "asia", "cambodia": "asia", "bangladesh": "asia",
    "nepal": "asia", "philippines": "asia", "indonesia": "asia",
    "china": "asia", "vietnam": "asia", "thailand": "asia",
    "united kingdom": "europe", "germany": "europe", "france": "europe",
    "netherlands": "europe", "sweden": "europe", "norway": "europe",
}

# Known sub-national divisions per country (lowercase).
# Used to distinguish "KwaZulu-Natal, South Africa" (SA province → partial)
# from "London, Northern Ireland, South Africa" (UK regions → ignore).
_COUNTRY_SUBDIVISIONS: Dict[str, frozenset] = {
    "south africa": frozenset({
        "eastern cape", "western cape", "northern cape", "north west",
        "gauteng", "limpopo", "mpumalanga", "kwazulu-natal", "kwazulu natal",
        "free state", "kzn",
    }),
    "united states": frozenset({
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
        "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan", "minnesota",
        "mississippi", "missouri", "montana", "nebraska", "nevada",
        "new hampshire", "new jersey", "new mexico", "new york",
        "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia", "washington",
        "west virginia", "wisconsin", "wyoming", "dc", "district of columbia",
    }),
    "kenya": frozenset({
        "nairobi", "mombasa", "kisumu", "nakuru", "eldoret",
        "central", "coast", "nyanza", "rift valley", "eastern", "north eastern",
    }),
    "ethiopia": frozenset({
        "addis ababa", "oromia", "amhara", "tigray", "snnpr", "somali",
        "afar", "benishangul-gumuz", "gambela", "harari", "dire dawa",
    }),
    "namibia": frozenset({
        "khomas", "erongo", "hardap", "karas", "kavango", "kunene",
        "ohangwena", "omaheke", "omusati", "oshana", "oshikoto",
        "otjozondjupa", "zambezi",
    }),
}


def _compute_geography_verdict(
    geographic_scope: str,
    *,
    service_countries: list,
    service_regions: Dict[str, list],
) -> Dict[str, str]:
    """Deterministically compute the geography rubric verdict.

    Algorithm:
      1. Unknown/empty scope → unknown
      2. Global terms → match
      3. Country name match → sub-region logic
      4. No country match → try continental terms
      5. Still no match → unknown
    """
    import re as _re

    scope = (geographic_scope or "").strip()
    scope_lower = scope.lower()

    _UNKNOWN_TERMS = {"not stated", "not_stated", "not applicable", "n/a", ""}
    _GLOBAL_TERMS = {"worldwide", "global", "international", "all countries", "anywhere"}

    if scope_lower in _UNKNOWN_TERMS:
        return {"verdict": "unknown", "evidence": "Geographic scope not stated"}
    if any(t in scope_lower for t in _GLOBAL_TERMS):
        return {"verdict": "match", "evidence": f"Fund has global/international scope: '{scope}'"}

    # Build country lookup: lowercase name → canonical name
    country_map = {str(c).strip().lower(): str(c).strip() for c in service_countries if str(c).strip()}

    # Build region lookups
    region_to_country: Dict[str, str] = {}
    country_regions: Dict[str, list] = {}
    for ctry_raw, regions in service_regions.items():
        canonical = country_map.get(str(ctry_raw).strip().lower())
        if not canonical:
            continue
        ctry_l = canonical.lower()
        country_regions.setdefault(ctry_l, [])
        for r in (regions or []):
            r_l = str(r).strip().lower()
            if r_l:
                region_to_country[r_l] = canonical
                country_regions[ctry_l].append(r_l)

    # Step 3a: find fund country by direct name match
    matched_country: Optional[str] = None
    for ctry_l, ctry_canonical in country_map.items():
        if ctry_l in scope_lower:
            matched_country = ctry_canonical
            break

    # Step 3b: find org sub-regions present in scope
    scope_org_regions = [r_l for r_l in region_to_country if r_l in scope_lower]

    # Step 3c: infer country from sub-regions
    if matched_country is None and scope_org_regions:
        matched_country = region_to_country[scope_org_regions[0]]

    # Step 4: continental fallback (only when no specific country matched)
    if matched_country is None:
        org_continents = {_COUNTRY_CONTINENT.get(c.lower()) for c in service_countries if c}
        for term, continent in _CONTINENTAL_TERMS:
            if term in scope_lower:
                if continent in org_continents:
                    matched_orgs = [
                        c for c in service_countries
                        if _COUNTRY_CONTINENT.get(c.lower()) == continent
                    ]
                    return {
                        "verdict": "match",
                        "evidence": (
                            f"Fund scope '{scope}' covers {continent}; "
                            f"org operates in {matched_orgs}"
                        ),
                    }
                return {
                    "verdict": "unknown",
                    "evidence": (
                        f"Fund scope '{scope}' covers {continent} but org has "
                        f"no service_countries on that continent"
                    ),
                }
        return {
            "verdict": "unknown",
            "evidence": f"Cannot map scope '{scope}' to any service country — treating as unknown",
        }

    # Step 5: sub-region logic for matched_country
    org_regions = country_regions.get(matched_country.lower(), [])

    if not org_regions:
        return {
            "verdict": "match",
            "evidence": f"'{matched_country}' is in service_countries; no sub-region restriction set",
        }

    if scope_org_regions:
        return {
            "verdict": "match",
            "evidence": (
                f"Fund scope '{scope}' overlaps org's listed regions "
                f"{[r.title() for r in scope_org_regions]} in '{matched_country}'"
            ),
        }

    # No org sub-regions in scope. Determine if the residual text is:
    #   a) a known sub-division of matched_country → partial
    #   b) regions of other countries → match (other-country text, not a restriction)
    scope_residual = scope_lower.replace(matched_country.lower(), "").strip(" ,.-/()")

    if not scope_residual:
        return {
            "verdict": "match",
            "evidence": f"Fund targets '{matched_country}' at country level; org operates there",
        }

    known_subs = _COUNTRY_SUBDIVISIONS.get(matched_country.lower(), frozenset())
    residual_tokens = [t for t in _re.split(r"[\s,.\-/()/]+", scope_residual.lower()) if t]

    # Check if any residual token (or multi-word combo) matches a known sub-division
    residual_joined = " ".join(residual_tokens)
    has_known_subdivision = any(sub in residual_joined for sub in known_subs)

    if has_known_subdivision:
        return {
            "verdict": "partial",
            "evidence": (
                f"'{matched_country}' is in service_countries but fund targets specific "
                f"sub-regions not in org's listed regions "
                f"{[r.title() for r in org_regions]}"
            ),
        }

    # Residual contains no known sub-divisions of matched_country → other-country text
    return {
        "verdict": "match",
        "evidence": (
            f"Fund explicitly targets '{matched_country}'; "
            f"other text in scope refers to other countries"
        ),
    }


def _call_model(client: OpenAI, prompt: str, model: str, *, system_prompt: str = "", fund_url: str = "") -> Dict[str, Any]:
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
        response_text = resp.choices[0].message.content
        data = json.loads(response_text)

        # Coerce application_status to one of the allowed enum values.
        _ALLOWED_STATUS = {"open", "closed", "paused", "rolling", "seasonal", "unclear"}
        raw_status = str(data.get("application_status", "") or "").strip().lower()
        status = raw_status if raw_status in _ALLOWED_STATUS else "unclear"

        # Validate + deterministic-tier-derive the rubric (Phase 10).
        # The LLM emits a per-dimension rubric AND its own `eligibility` tier.
        # We don't trust the LLM's tier — we derive it from the rubric so the
        # veto rules are enforced deterministically.
        rubric = _normalize_rubric(data.get("rubric"))
        derived_tier = _tier_from_rubric(rubric)

        normalized = {
            "applicant_types": data.get("applicant_types", []),
            "geographic_scope": data.get("geographic_scope", ""),
            "us_state_scope": data.get("us_state_scope", []),
            "beneficiary_focus": data.get("beneficiary_focus", []),
            "funding_range": data.get("funding_range", ""),
            "restrictions": data.get("restrictions", []),
            "application_status": status,
            "deadline": data.get("deadline", ""),
            "notes": data.get("notes", ""),
            "grant_type": data.get("grant_type", "other"),
            "match_rubric": rubric,
            "eligibility": derived_tier or data.get("eligibility", "Low Match"),
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

        _write_debug_log(
            fund_url=fund_url,
            model=model,
            system_prompt=system_prompt or LLM_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_text=response_text,
            eligibility=normalized["eligibility"],
        )

        return normalized

    except json.JSONDecodeError as e:
        log_message(f"Invalid JSON from LLM ({model}): {e}", "error")
        return _empty_result(f"JSON parsing error: {e}", f"Could not parse LLM response: {e}")
    except Exception as e:
        log_message(f"LLM extraction failed ({model}): {e}", "error")
        return _empty_result(f"Extraction failed: {e}", f"LLM extraction failed: {e}")


def _normalize_rubric(raw) -> Dict[str, Dict[str, str]]:
    """Coerce the LLM's rubric output into the canonical 8-dimension structure.

    The LLM occasionally returns a malformed rubric (missing dimensions,
    invalid verdicts, etc.). We normalize so downstream always sees the
    full 8 keys with valid verdicts.
    """
    from utils.constants.llm import RUBRIC_DIMENSIONS, RUBRIC_VERDICTS
    out: Dict[str, Dict[str, str]] = {}
    if not isinstance(raw, dict):
        raw = {}
    for dim in RUBRIC_DIMENSIONS:
        entry = raw.get(dim) if isinstance(raw.get(dim), dict) else {}
        verdict = str(entry.get("verdict", "unknown")).strip().lower()
        if verdict not in RUBRIC_VERDICTS:
            verdict = "unknown"
        evidence = str(entry.get("evidence", "") or "").strip()[:500]
        out[dim] = {"verdict": verdict, "evidence": evidence}
    return out


def _tier_from_rubric(rubric: Dict[str, Dict[str, str]]) -> str:
    """Deterministic eligibility tier from the 8-dimension rubric.

    Veto rule: any `mismatch` on geography, applicant_type, org_history,
    cost_share, or explicit_exclusion → Not Eligible.

    Tier mapping (when no veto fires):
      • ≥6 of 8 `match`, no `mismatch` anywhere → Highly Eligible
      • ≥3 of 8 `match`, ≤1 non-veto `mismatch`  → Eligible
      • 2 of 8 `match`                            → Possibly Eligible
      • 0-1 of 8 `match`                          → Low Match
    """
    from utils.constants.llm import RUBRIC_DIMENSIONS, VETO_DIMENSIONS

    if not rubric:
        return "Low Match"

    verdicts = {d: rubric.get(d, {}).get("verdict", "unknown") for d in RUBRIC_DIMENSIONS}

    # Veto check
    for dim in VETO_DIMENSIONS:
        if verdicts.get(dim) == "mismatch":
            return "Not Eligible"

    match_count = sum(1 for v in verdicts.values() if v == "match")
    mismatch_count = sum(1 for v in verdicts.values() if v == "mismatch")  # non-veto only at this point

    if mismatch_count == 0 and match_count >= 6:
        return "Highly Eligible"
    if mismatch_count <= 1 and match_count >= 3:
        return "Eligible"
    if match_count == 2:
        return "Possibly Eligible"
    return "Low Match"


def _is_thin_result(result: Dict[str, Any]) -> bool:
    """True when the extraction looks like a failure — too many key fields are empty."""
    important = ["applicant_types", "geographic_scope", "beneficiary_focus", "funding_range", "evidence"]
    empty_count = sum(1 for k in important if not result.get(k))
    return empty_count >= 3 or result.get("eligibility") not in ELIGIBILITY_ORDER


_DOCUMENT_SYSTEM_PROMPT = (
    "You analyse grant-related documents to surface signals useful to a nonprofit "
    "applying for funding. Reply with strict JSON matching the requested schema. "
    "Use empty strings or empty arrays when information is not present."
)

_FORM_990_USER_PROMPT = """Extract grant-signals from this Form 990 (or 990-PF) text.

Return JSON with EXACTLY these keys:
  program_areas: array of strings — funder's stated grantmaking focus areas
  total_grants_paid: string — dollar amount paid as grants this year (e.g. "$1,250,000") or ""
  top_grantees: array of objects {{name, amount, purpose}} for up to 10 largest grants this filing year
  contact_email: string or ""
  contact_phone: string or ""
  application_process: string — brief description of how to apply, or "" if not disclosed
  geographic_scope: string — where the funder gives (e.g. "California only", "national", "")

Form 990 text:
{text}"""

_RFP_USER_PROMPT = """Extract grant-signals from this funding opportunity / RFP / NOFA text.

Return JSON with EXACTLY these keys:
  eligibility: string — who can apply
  funding_range: string — $ amount(s) available
  deadline: string — application due date or "rolling" / ""
  program_focus: string — topical focus
  application_url: string — where to apply or ""
  contact: string — name/email/phone of program contact or ""
  geographic_scope: string — eligible geography

RFP / notice text:
{text}"""


def extract_from_document(text: str, kind: str) -> Dict[str, Any]:
    """Pull grant signals out of a downloaded document.

    `kind` is one of: 'form_990', 'rfp', 'notice', 'attachment'.
    Uses the same gpt-4o-mini → gpt-4.1 fallback as call_llm_extract.
    Returns {} when no LLM key is configured so callers can persist the
    document text without a summary and skip cost.
    """
    client = get_client()
    if client is None:
        return {}

    if not text or not text.strip():
        return {}

    if len(text) > _MAX_CHARS:
        log_message(
            f"Document text truncated from {len(text)} to {_MAX_CHARS} chars for {kind}",
            "warning",
        )
        half = _MAX_CHARS // 2
        text = text[:half] + "\n...[content truncated]...\n" + text[-half:]

    template = _FORM_990_USER_PROMPT if kind == "form_990" else _RFP_USER_PROMPT
    prompt = template.format(text=text)

    result = _call_document_model(client, prompt, _MODEL_FAST)
    if _is_thin_doc_result(result, kind) and len(text) > 2000:
        log_message(
            f"Thin document result from {_MODEL_FAST} for {kind}; retrying with {_MODEL_FULL}",
            "warning",
        )
        result = _call_document_model(client, prompt, _MODEL_FULL)
    return result


def _call_document_model(client: OpenAI, prompt: str, model: str) -> Dict[str, Any]:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _DOCUMENT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=60,
        )
        return json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError as exc:
        log_message(f"Invalid JSON from document LLM ({model}): {exc}", "error")
        return {}
    except Exception as exc:
        log_message(f"Document LLM extraction failed ({model}): {exc}", "error")
        return {}


def _is_thin_doc_result(result: Dict[str, Any], kind: str) -> bool:
    if not result:
        return True
    if kind == "form_990":
        return not (result.get("program_areas") or result.get("top_grantees"))
    return not (result.get("eligibility") or result.get("funding_range") or result.get("program_focus"))


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
