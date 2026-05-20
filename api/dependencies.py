"""Shared FastAPI dependencies."""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Depends, HTTPException
from gotrue.types import User

from api.auth.middleware import get_current_user, get_user_role
from api.config import settings
from utils import tools

_CONFIGURED = False


def ensure_configured() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    tools.configure_tools(
        openai_api_key=settings.openai_api_key,
        supabase_url=settings.supabase_url,
        supabase_service_key=settings.supabase_service_key,
        log_callback=_log_callback,
    )
    logging.getLogger(__name__).info("Tools configured")
    _CONFIGURED = True


def _log_callback(level: str, message: str) -> None:
    logger = logging.getLogger("tools")
    log_fn: Callable[[str], None] | None = getattr(logger, level, None)
    if callable(log_fn):
        log_fn(message)
    else:
        logger.info(message)


def get_tools_module() -> tools:
    ensure_configured()
    return tools


def get_settings():
    return settings


def require_user(user: User = Depends(get_current_user)) -> User:
    return user


def require_superuser(user: User = Depends(get_current_user)) -> User:
    role = get_user_role(str(user.id))
    if role != "superuser":
        raise HTTPException(status_code=403, detail="Superuser access required")
    return user
