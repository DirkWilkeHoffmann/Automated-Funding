"""Supabase JWT verification for FastAPI."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gotrue.types import User

from utils.db.client import get_supabase

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> User:
    """Decode and verify the Supabase access token. Raises 401 on failure."""
    token = credentials.credentials
    try:
        response = get_supabase().auth.get_user(token)
        if not response or not response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return response.user
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Auth failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_user_role(user_id: str) -> str:
    """Return the user's role from user_profiles. Defaults to 'user'."""
    try:
        rows = (
            get_supabase()
            .table("user_profiles")
            .select("role")
            .eq("id", user_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0].get("role", "user") if rows else "user"
    except Exception as exc:
        logger.warning("Could not fetch user role for %s: %s", user_id, exc)
        return "user"
