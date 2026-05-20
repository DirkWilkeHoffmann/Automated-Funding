"""Supabase client singleton, initialised from runtime tool settings."""

from __future__ import annotations

import logging

from supabase import Client, create_client

from utils.config import get_settings

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_supabase() -> Client:
    """Return a cached Supabase service-role client.

    configure_tools() must have been called with supabase_url and
    supabase_service_key before the first call to this function.
    """
    global _client
    if _client is None:
        s = get_settings()
        if not s.supabase_url or not s.supabase_service_key:
            raise RuntimeError(
                "Supabase not configured. "
                "Call configure_tools(supabase_url=..., supabase_service_key=...) first."
            )
        _client = create_client(s.supabase_url, s.supabase_service_key)
        logger.info("Supabase client initialised")
    return _client


def reset_client() -> None:
    """Force the next get_supabase() call to create a fresh client.
    Useful in tests when credentials change between cases.
    """
    global _client
    _client = None
