"""Admin endpoints — superuser only."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from api import dependencies
from api.schemas import (
    CategorySuggestionResponse,
    CreateUserRequest,
    CreateUserResponse,
    OrgProfileRequest,
    OrgProfileResponse,
    ProfileSuggestionResponse,
    SetBraveSearchKeyRequest,
    SetCandidKeyRequest,
    SetOpenAIKeyRequest,
    SetSamGovKeyRequest,
    TokenStatusResponse,
    UserRecord,
    UserRoleRequest,
)
from utils.db.client import get_supabase
from utils.db.org_store import clear_org_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_ORG_FIELDS = {
    "id", "name", "ein", "city", "state", "mission",
    "services", "annual_income", "staff_count", "volunteer_count",
    "website", "ai_system_prompt", "ai_user_prompt",
    # Phase 3 filter fields
    "ntee_codes", "service_states", "applicant_types",
    "accepts_unsolicited", "can_cost_share",
    "min_grant_size", "max_grant_size",
    # Phase 5 topic filter
    "cfda_categories", "eligible_applicant_codes", "category_suggestion_notes",
    # Phase 9 structured profile
    "org_type_description", "service_area_description", "beneficiaries", "programs",
    "income_sources", "currency", "founded_year", "target_outcomes",
    "partner_orgs", "accreditations",
    # Phase 10 geography
    "country", "service_countries", "service_regions",
}


# ── Org profile ──────────────────────────────────────────────────────────────


@router.get("/org", response_model=OrgProfileResponse)
def get_org(user=Depends(dependencies.require_superuser)):
    rows = get_supabase().table("organizations").select("*").limit(1).execute().data or []
    if not rows:
        return OrgProfileResponse()
    return OrgProfileResponse(**{k: v for k, v in rows[0].items() if k in _ORG_FIELDS})


@router.put("/org", response_model=OrgProfileResponse)
def update_org(
    payload: OrgProfileRequest,
    user=Depends(dependencies.require_superuser),
):
    data = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not data:
        raise HTTPException(status_code=400, detail="No fields provided")

    existing = get_supabase().table("organizations").select("id").limit(1).execute().data or []
    if existing:
        result = (
            get_supabase()
            .table("organizations")
            .update(data)
            .eq("id", existing[0]["id"])
            .execute()
        )
    else:
        result = get_supabase().table("organizations").insert(data).execute()

    clear_org_cache()
    rows = result.data or []
    return (
        OrgProfileResponse(**{k: v for k, v in rows[0].items() if k in _ORG_FIELDS})
        if rows
        else OrgProfileResponse(**data)
    )


@router.get("/org/default-prompts")
def get_default_prompts(_user=Depends(dependencies.require_superuser)) -> dict:
    """Return the live default system + user prompt strings.

    Used by the admin UI to display the actual current defaults instead of
    a hardcoded copy that goes stale every time the backend prompt is
    updated. Source of truth is `utils.constants.llm`.
    """
    from utils.constants.llm import LLM_PROMPT, LLM_SYSTEM_PROMPT
    return {
        "system": LLM_SYSTEM_PROMPT,
        "user": LLM_PROMPT,
    }


@router.get("/org/profile-text")
def get_profile_text(_user=Depends(dependencies.require_superuser)) -> dict:
    """Phase 10: return the live org-profile string that would be injected as `{org_profile}` at scrape time.

    Used by the admin UI's "Preview effective prompt" panel so the operator
    can verify exactly what the LLM will receive before running a scrape.
    """
    from utils.db.org_store import clear_org_cache, get_org_profile_text
    # Bust the cache so the preview always shows the very latest saved values.
    clear_org_cache()
    return {"org_profile_text": get_org_profile_text()}


@router.post("/org/suggest-categories", response_model=CategorySuggestionResponse)
def suggest_categories(user=Depends(dependencies.require_superuser)):
    """LLM-suggest CFDA categories + applicant codes from the saved org profile.

    Reads the org row, builds a prompt with the mission + services + applicant_types,
    calls gpt-4o-mini, and returns a recommendation. The frontend pre-checks
    the suggestions but the operator confirms/edits before saving.

    Cost: ~1 cheap LLM call per org-profile change. Safe to call repeatedly.
    """
    import json
    from utils.discovery.cfda_categories import CFDA_CATEGORIES
    from utils.discovery.grants_gov_codes import (
        CODE_TO_TYPES,
        ELIGIBLE_APPLICANTS_LABELS,
    )
    from utils.llm_utils import get_client

    rows = get_supabase().table("organizations").select("*").limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=400, detail="No organisation profile saved yet")
    org = rows[0]

    client = get_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured — set it in Admin → Tokens.",
        )

    cat_list = "\n".join(f"  {code} = {label}" for code, label in CFDA_CATEGORIES.items())
    code_list = "\n".join(
        f"  {code} = {label}"
        for code, label in ELIGIBLE_APPLICANTS_LABELS.items()
        if code not in {"00", "11", "25", "99"}  # hide catch-alls — never useful as filter
    )

    org_text_parts = [
        f"Name: {org.get('name') or ''}",
        f"Mission: {org.get('mission') or ''}",
        f"Services: {', '.join(org.get('services') or []) if isinstance(org.get('services'), list) else (org.get('services') or '')}",
        f"Applicant types claimed: {', '.join(org.get('applicant_types') or [])}",
        f"State / location: {org.get('state') or ''} / {org.get('city') or ''}",
    ]
    org_text = "\n".join(p for p in org_text_parts if p.split(": ", 1)[-1])

    system = (
        "You map a nonprofit organisation's profile to the Grants.gov category "
        "codes and applicant-eligibility codes that determine which federal grants "
        "they could plausibly apply for. Be inclusive but precise — every "
        "category you pick will be used to filter what they see, so unrelated "
        "categories must be excluded, but adjacent categories (e.g. an "
        "employment org probably also wants Education and Income Security) "
        "should be included. Reply with strict JSON only."
    )

    user_prompt = f"""=== Organisation profile ===
{org_text}

=== Available CFDA category codes ===
{cat_list}

=== Available applicant-eligibility codes ===
{code_list}

Pick the CFDA category codes that this organisation could plausibly apply for
based on their mission and services. Be inclusive but exclude clearly unrelated
categories. Also pick the applicant-eligibility codes that describe what KIND of
organisation they are (their org type, not what they fund).

Return JSON with EXACTLY these keys:
  cfda_categories: array of CFDA codes from the list above (e.g. ["ELT","ISS","ED"])
  eligible_applicant_codes: array of applicant codes from the list above (e.g. ["12"])
  notes: one short sentence explaining your reasoning.

Return ONLY the JSON object."""

    try:
        resp = client.chat.completions.create(
            # model="gpt-4o-mini",
            model=_MODEL_FAST,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=45,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.exception("Category suggestion failed")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    raw_cats = [str(c).upper() for c in data.get("cfda_categories", []) if c]
    cats = [c for c in raw_cats if c in CFDA_CATEGORIES]

    raw_codes = [str(c).zfill(2) for c in data.get("eligible_applicant_codes", []) if str(c).strip()]
    codes = [c for c in raw_codes if c in ELIGIBLE_APPLICANTS_LABELS]

    return CategorySuggestionResponse(
        cfda_categories=cats,
        eligible_applicant_codes=codes,
        notes=str(data.get("notes", "")).strip()[:500],
    )


@router.post("/org/suggest-profile", response_model=ProfileSuggestionResponse)
def suggest_profile(user=Depends(dependencies.require_superuser)):
    """Phase 9: LLM-suggest the 10 structured profile fields from the saved org.

    Reads name + mission + services + website + state, calls gpt-4o-mini, and
    returns a draft for org_type_description, service_area_description,
    beneficiaries, programs, income_sources, currency, founded_year,
    target_outcomes, partner_orgs, accreditations. The frontend pre-fills the
    UI; the operator confirms/edits before saving.

    Cost: ~1 cheap LLM call per profile change. Safe to call repeatedly.
    """
    import json
    from utils.llm_utils import get_client

    rows = get_supabase().table("organizations").select("*").limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=400, detail="No organisation profile saved yet — fill in at least the name and mission first.")
    org = rows[0]

    client = get_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured — set it in Admin → Tokens.",
        )

    svcs_raw = org.get("services")
    if isinstance(svcs_raw, list):
        services_text = ", ".join(str(s) for s in svcs_raw if s)
    else:
        services_text = (svcs_raw or "").strip()

    org_text_parts = [
        f"Name: {org.get('name') or ''}",
        f"Mission: {org.get('mission') or ''}",
        f"Services: {services_text}",
        f"Location: {org.get('city') or ''} / {org.get('state') or ''}",
        f"Website: {org.get('website') or ''}",
        f"Annual income: {org.get('annual_income') or ''}",
        f"Staff: {org.get('staff_count') or ''}",
        f"Volunteers: {org.get('volunteer_count') or ''}",
        f"EIN: {org.get('ein') or ''}",
    ]
    org_text = "\n".join(p for p in org_text_parts if p.split(": ", 1)[-1])

    system = (
        "You convert a nonprofit organisation's free-text profile into 10 "
        "structured fields used downstream by an AI grant evaluator. "
        "Be CONCRETE and SPECIFIC — short, factual entries that a grant "
        "analyst can match against funder criteria. Do NOT invent facts "
        "that aren't supported by the input; use empty arrays / null when "
        "unsure. Reply with strict JSON only."
    )

    user_prompt = f"""=== Organisation input ===
{org_text}

=== TASK ===
Produce a structured profile. Return JSON with EXACTLY these keys:

{{
  "org_type_description": "ONE-LINE org-type descriptor (e.g. 'Registered US 501(c)(3) nonprofit providing workforce development training in the US and internationally'). Max ~25 words.",
  "service_area_description": "Free-text geographic description finer than HQ state (e.g. 'Jasper, GA + 12 international W4AL Training Centers'). Empty string if not inferable.",
  "beneficiaries": ["target groups SERVED, not what the org does", "e.g. 'unemployed adults', 'low-income individuals', 'first-time entrepreneurs'"],
  "programs": ["distinct named programs", "more structured than the services blob", "max ~8"],
  "income_sources": ["funding source types", "e.g. 'donations', 'foundation grants', 'earned revenue', 'government grants'"],
  "currency": "USD | GBP | EUR | CAD | AUD | ZAR | other 3-letter code. Infer from location.",
  "founded_year": null,
  "target_outcomes": ["measurable outcomes the org aims for", "e.g. '% of trainees placed in jobs within 6 months', 'average wage increase per graduate'"],
  "partner_orgs": ["named partner organisations, employers, or funders mentioned in the input", "skip if none mentioned"],
  "accreditations": ["formal accreditations, certifications, or registrations", "e.g. '501(c)(3)', 'GuideStar Gold', 'CHEA-accredited', 'ISO 9001'"],
  "notes": "one short sentence summarising any non-obvious inferences you made"
}}

Rules:
- Return empty arrays [] when you have no confidence rather than guessing.
- Return null for founded_year if not inferable from the input.
- DO NOT echo the org's mission verbatim — distil it into the structured fields.
- Be terse: each list entry should be 2-6 words, not a paragraph.

Return ONLY the JSON object."""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=45,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.exception("Profile suggestion failed")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    def _as_list(v) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(x).strip() for x in v if str(x).strip()][:12]

    fy_raw = data.get("founded_year")
    founded_year: Optional[int] = None
    if isinstance(fy_raw, int):
        founded_year = fy_raw
    elif isinstance(fy_raw, str) and fy_raw.strip().isdigit():
        founded_year = int(fy_raw.strip())

    return ProfileSuggestionResponse(
        org_type_description=str(data.get("org_type_description") or "").strip()[:400],
        service_area_description=str(data.get("service_area_description") or "").strip()[:400],
        beneficiaries=_as_list(data.get("beneficiaries")),
        programs=_as_list(data.get("programs")),
        income_sources=_as_list(data.get("income_sources")),
        currency=(str(data.get("currency") or "USD").strip().upper()[:3] or "USD"),
        founded_year=founded_year,
        target_outcomes=_as_list(data.get("target_outcomes")),
        partner_orgs=_as_list(data.get("partner_orgs")),
        accreditations=_as_list(data.get("accreditations")),
        notes=str(data.get("notes") or "").strip()[:500],
    )


# ── User management ──────────────────────────────────────────────────────────


@router.get("/users", response_model=list[UserRecord])
def list_users(user=Depends(dependencies.require_superuser)):
    profiles = (
        get_supabase()
        .table("user_profiles")
        .select("id, role, created_at")
        .execute()
        .data
        or []
    )
    profile_map = {p["id"]: p for p in profiles}

    try:
        auth_users = get_supabase().auth.admin.list_users()
    except Exception as exc:
        logger.warning("Could not list auth users: %s", exc)
        auth_users = []

    results = []
    for au in auth_users:
        uid = str(au.id)
        profile = profile_map.get(uid, {})
        ts = au.created_at
        created = ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None
        results.append(
            UserRecord(id=uid, email=au.email, role=profile.get("role", "user"), created_at=created)
        )
    return results


@router.post("/users", response_model=CreateUserResponse, status_code=201)
def create_user(
    payload: CreateUserRequest,
    user=Depends(dependencies.require_superuser),
):
    try:
        result = get_supabase().auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
        })
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    uid = str(result.user.id)
    get_supabase().table("user_profiles").insert(
        {"id": uid, "role": payload.role}
    ).execute()

    return CreateUserResponse(id=uid, email=payload.email, role=payload.role)


@router.post("/users/{user_id}/role")
def set_user_role(
    user_id: str,
    payload: UserRoleRequest,
    user=Depends(dependencies.require_superuser),
):
    existing = (
        get_supabase()
        .table("user_profiles")
        .select("id")
        .eq("id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        get_supabase().table("user_profiles").update({"role": payload.role}).eq(
            "id", user_id
        ).execute()
    else:
        get_supabase().table("user_profiles").insert(
            {"id": user_id, "role": payload.role}
        ).execute()
    return {"status": "ok", "user_id": user_id, "role": payload.role}


# ── API tokens ───────────────────────────────────────────────────────────────


@router.get("/tokens", response_model=list[TokenStatusResponse])
def list_tokens(user=Depends(dependencies.require_superuser)):
    rows = (
        get_supabase()
        .table("api_tokens")
        .select("service, key_value, updated_at")
        .execute()
        .data
        or []
    )
    result = []
    for r in rows:
        val = r.get("key_value", "")
        masked = val[:7] + "…" + val[-4:] if len(val) > 11 else "***"
        result.append(
            TokenStatusResponse(name=r["service"], masked=masked, updated_at=r.get("updated_at"))
        )
    return result


@router.post("/tokens/openai")
def set_openai_key(
    payload: SetOpenAIKeyRequest,
    user=Depends(dependencies.require_superuser),
):
    from utils.llm_utils import clear_openai_key_cache

    key = payload.openai_api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")

    now = datetime.now(timezone.utc).isoformat()
    existing = (
        get_supabase()
        .table("api_tokens")
        .select("id")
        .eq("service", "openai")
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        get_supabase().table("api_tokens").update({"key_value": key, "updated_at": now}).eq(
            "service", "openai"
        ).execute()
    else:
        get_supabase().table("api_tokens").insert(
            {"service": "openai", "key_value": key, "updated_at": now}
        ).execute()

    clear_openai_key_cache()
    return {"status": "ok", "openai_api_key_set": True}


@router.post("/tokens/sam_gov")
def set_sam_gov_key(
    payload: SetSamGovKeyRequest,
    user=Depends(dependencies.require_superuser),
):
    key = payload.sam_gov_api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="SAM.gov API key cannot be empty")

    now = datetime.now(timezone.utc).isoformat()
    existing = (
        get_supabase()
        .table("api_tokens")
        .select("id")
        .eq("service", "sam_gov")
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        get_supabase().table("api_tokens").update({"key_value": key, "updated_at": now}).eq(
            "service", "sam_gov"
        ).execute()
    else:
        get_supabase().table("api_tokens").insert(
            {"service": "sam_gov", "key_value": key, "updated_at": now}
        ).execute()

    return {"status": "ok", "sam_gov_key_set": True}


@router.post("/tokens/brave_search")
def set_brave_search_key(
    payload: SetBraveSearchKeyRequest,
    user=Depends(dependencies.require_superuser),
):
    key = payload.brave_search_api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Brave Search API key cannot be empty")

    now = datetime.now(timezone.utc).isoformat()
    existing = (
        get_supabase()
        .table("api_tokens")
        .select("id")
        .eq("service", "brave_search")
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        get_supabase().table("api_tokens").update({"key_value": key, "updated_at": now}).eq(
            "service", "brave_search"
        ).execute()
    else:
        get_supabase().table("api_tokens").insert(
            {"service": "brave_search", "key_value": key, "updated_at": now}
        ).execute()

    return {"status": "ok", "brave_search_key_set": True}


@router.post("/tokens/candid")
def set_candid_key(
    payload: SetCandidKeyRequest,
    user=Depends(dependencies.require_superuser),
):
    """Phase 7: Save Candid Essentials API key (paid, optional source).

    Once set, the operator can flip the `candid` source toggle in
    /admin/discovery and CandidSource (already in registry.py) will start
    yielding grantmaker results.
    """
    key = payload.candid_api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Candid API key cannot be empty")

    now = datetime.now(timezone.utc).isoformat()
    existing = (
        get_supabase()
        .table("api_tokens")
        .select("id")
        .eq("service", "candid")
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        get_supabase().table("api_tokens").update({"key_value": key, "updated_at": now}).eq(
            "service", "candid"
        ).execute()
    else:
        get_supabase().table("api_tokens").insert(
            {"service": "candid", "key_value": key, "updated_at": now}
        ).execute()

    return {"status": "ok", "candid_key_set": True}
