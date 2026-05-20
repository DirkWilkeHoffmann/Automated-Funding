"""Admin endpoints — superuser only."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api import dependencies
from api.schemas import (
    CreateUserRequest,
    CreateUserResponse,
    OrgProfileRequest,
    OrgProfileResponse,
    SetBraveSearchKeyRequest,
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
