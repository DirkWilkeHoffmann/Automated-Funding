"""Persistence layer for discovery_config (single-row config table)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict

from utils.db.client import get_supabase

logger = logging.getLogger(__name__)

_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "cron_expression": "0 2 * * 1",  # Monday 2am UTC
    "states": [],
    "keywords": [],
    "sources": {
        "propublica": True,
        "grants_gov": True,
        "sam_gov": False,
        "web_search": True,
        "federal_register": True,
    },
    "max_per_source": 100,
}


@lru_cache(maxsize=1)
def _load_config_cached() -> Dict[str, Any]:
    try:
        rows = (
            get_supabase()
            .table("discovery_config")
            .select("*")
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            row = rows[0]
            return {
                "id": row.get("id"),
                "enabled": bool(row.get("enabled", False)),
                "cron_expression": row.get("cron_expression") or _DEFAULTS["cron_expression"],
                "states": row.get("states") or [],
                "keywords": row.get("keywords") or [],
                "sources": row.get("sources") or _DEFAULTS["sources"],
                "max_per_source": int(row.get("max_per_source") or 100),
                "updated_at": row.get("updated_at"),
            }
    except Exception as exc:
        logger.warning("Could not load discovery_config: %s", exc)
    return dict(_DEFAULTS)


def load_config() -> Dict[str, Any]:
    """Return the current discovery config (cached)."""
    return _load_config_cached()


def clear_config_cache() -> None:
    """Invalidate the config cache."""
    _load_config_cached.cache_clear()


def load_discovery_state() -> Dict[str, Any]:
    """Read the discovery_state JSONB column (not cached — changes each run)."""
    try:
        rows = (
            get_supabase()
            .table("discovery_config")
            .select("discovery_state")
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows and rows[0].get("discovery_state"):
            return rows[0]["discovery_state"]
    except Exception as exc:
        logger.warning("Could not load discovery_state: %s", exc)
    return {}


def save_discovery_state(state: Dict[str, Any]) -> None:
    """Write back the full discovery_state JSONB column."""
    try:
        existing = (
            get_supabase()
            .table("discovery_config")
            .select("id")
            .limit(1)
            .execute()
            .data
            or []
        )
        if not existing:
            logger.warning("No discovery_config row — cannot save discovery_state")
            return
        get_supabase().table("discovery_config").update(
            {"discovery_state": state}
        ).eq("id", existing[0]["id"]).execute()
    except Exception as exc:
        logger.warning("Could not save discovery_state: %s", exc)


def save_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert the discovery_config row. Clears cache and returns the saved row."""
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "enabled": bool(data.get("enabled", False)),
        "cron_expression": data.get("cron_expression") or _DEFAULTS["cron_expression"],
        "states": data.get("states") or [],
        "keywords": data.get("keywords") or [],
        "sources": data.get("sources") or _DEFAULTS["sources"],
        "max_per_source": int(data.get("max_per_source") or 100),
        "updated_at": now,
    }
    try:
        existing = (
            get_supabase()
            .table("discovery_config")
            .select("id")
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            result = (
                get_supabase()
                .table("discovery_config")
                .update(payload)
                .eq("id", existing[0]["id"])
                .execute()
            )
            saved = result.data[0] if result.data else {**payload, "id": existing[0]["id"]}
        else:
            result = (
                get_supabase()
                .table("discovery_config")
                .insert(payload)
                .execute()
            )
            saved = result.data[0] if result.data else payload
    except Exception as exc:
        logger.error("Could not save discovery_config: %s", exc)
        saved = payload

    clear_config_cache()
    return saved
