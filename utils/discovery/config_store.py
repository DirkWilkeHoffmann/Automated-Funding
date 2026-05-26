"""Persistence layer for discovery_config (single-row config table)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Optional

from utils.db.client import get_supabase

logger = logging.getLogger(__name__)

_IMPORT_CONFIG_DEFAULTS: Dict[str, Any] = {
    "bmf_min_asset_code": 7,    # 7 = $1M+; range 1–9
    "bmf_ntee_prefixes": [],    # e.g. ["T"] for philanthropy; empty = all
    "bmf_batch_size": 50,       # foundations to process per discovery run
    "grants_gov_close_days": 90,  # only import opportunities closing within N days
    "grants_gov_nonprofit_filter": True,  # pre-filter to grants that mention nonprofits in eligibility text
    "bmf_last_imported_at": None,
    "grants_gov_last_imported_at": None,
}

_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "cron_expression": "0 2 * * 1",  # Monday 2am UTC
    "states": [],
    "keywords": [],
    "sources": {
        "irs_bmf": True,        # IRS BMF private foundations (DB-backed, monthly import)
        "grants_gov_db": True,  # Grants.gov XML extract (DB-backed, daily import)
        "propublica": True,
        "grants_gov": True,
        "sam_gov": False,
        "web_search": True,
        "federal_register": True,
        "philanthropy_digest": False,  # defunct — site folded into Candid (no public feed)
        "state_portals": True,
        # usaspending returns recipient-org pages, not grant opportunities — off by default
        "usaspending": False,
        "candid": False,  # gated on paid API key in api_tokens
    },
    "max_per_source": 100,
    "documents_per_run": 200,
    "import_config": _IMPORT_CONFIG_DEFAULTS,
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
            import_config_raw = row.get("import_config") or {}
            import_config = {**_IMPORT_CONFIG_DEFAULTS, **import_config_raw}
            return {
                "id": row.get("id"),
                "enabled": bool(row.get("enabled", False)),
                "cron_expression": row.get("cron_expression") or _DEFAULTS["cron_expression"],
                "states": row.get("states") or [],
                "keywords": row.get("keywords") or [],
                "sources": {**_DEFAULTS["sources"], **(row.get("sources") or {})},
                "max_per_source": int(row.get("max_per_source") or 100),
                "documents_per_run": int(row.get("documents_per_run") or 200),
                "import_config": import_config,
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


def load_import_config() -> Dict[str, Any]:
    """Return the import_config sub-dict (BMF/Grants.gov settings)."""
    config = load_config()
    return config.get("import_config") or dict(_IMPORT_CONFIG_DEFAULTS)


def update_import_timestamps(
    bmf_at: Optional[str] = None,
    grants_gov_at: Optional[str] = None,
) -> None:
    """Persist the last-imported timestamps back into discovery_config.import_config."""
    try:
        existing = (
            get_supabase()
            .table("discovery_config")
            .select("id, import_config")
            .limit(1)
            .execute()
            .data
            or []
        )
        if not existing:
            logger.warning("No discovery_config row — cannot update import timestamps")
            return
        row = existing[0]
        current = dict(row.get("import_config") or {})
        if bmf_at is not None:
            current["bmf_last_imported_at"] = bmf_at
        if grants_gov_at is not None:
            current["grants_gov_last_imported_at"] = grants_gov_at
        get_supabase().table("discovery_config").update(
            {"import_config": current}
        ).eq("id", row["id"]).execute()
        _load_config_cached.cache_clear()
    except Exception as exc:
        logger.warning("Could not update import timestamps: %s", exc)


def save_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert the discovery_config row. Clears cache and returns the saved row."""
    now = datetime.now(timezone.utc).isoformat()
    import_config_in = data.get("import_config") or {}
    import_config = {**_IMPORT_CONFIG_DEFAULTS, **import_config_in}
    # Never overwrite last-imported timestamps via config save (only importers write those)
    import_config.pop("bmf_last_imported_at", None)
    import_config.pop("grants_gov_last_imported_at", None)

    payload = {
        "enabled": bool(data.get("enabled", False)),
        "cron_expression": data.get("cron_expression") or _DEFAULTS["cron_expression"],
        "states": data.get("states") or [],
        "keywords": data.get("keywords") or [],
        "sources": data.get("sources") or _DEFAULTS["sources"],
        "max_per_source": int(data.get("max_per_source") or 100),
        "documents_per_run": int(data.get("documents_per_run") or 200),
        "import_config": import_config,
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
