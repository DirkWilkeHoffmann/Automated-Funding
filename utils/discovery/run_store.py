"""Persistence layer for discovery_runs audit log."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.db.client import get_supabase

logger = logging.getLogger(__name__)


def create_run(trigger: str, config_snapshot: Dict[str, Any]) -> str:
    """Insert a new discovery_runs row with status='running'. Returns run_id."""
    now = datetime.now(timezone.utc).isoformat()
    snapshot = config_snapshot.copy()
    snapshot.pop("id", None)
    snapshot.pop("updated_at", None)
    try:
        result = (
            get_supabase()
            .table("discovery_runs")
            .insert({
                "started_at": now,
                "status": "running",
                "trigger": trigger,
                "config_snapshot": snapshot,
            })
            .execute()
        )
        rows = result.data or []
        if rows:
            return rows[0]["id"]
    except Exception as exc:
        logger.error("Could not create discovery_run: %s", exc)
    return ""


def complete_run(
    run_id: str,
    *,
    urls_discovered: int,
    urls_new: int,
    scrape_job_id: Optional[str],
) -> None:
    """Update run to status='completed'."""
    if not run_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        get_supabase().table("discovery_runs").update({
            "finished_at": now,
            "status": "completed",
            "urls_discovered": urls_discovered,
            "urls_new": urls_new,
            "scrape_job_id": scrape_job_id,
        }).eq("id", run_id).execute()
    except Exception as exc:
        logger.error("Could not complete discovery_run %s: %s", run_id, exc)


def save_progress_snapshot(run_id: str, snapshot: Dict[str, Any]) -> None:
    """Persist the live DiscoveryProgress snapshot to discovery_runs.progress_snapshot.

    Best-effort: a failed write does not interrupt the run. The in-memory
    progress registry is the source of truth while a run is in flight; the
    snapshot lets the frontend recover state after a page refresh.
    """
    if not run_id:
        return
    try:
        get_supabase().table("discovery_runs").update({
            "progress_snapshot": snapshot,
        }).eq("id", run_id).execute()
    except Exception as exc:
        logger.warning("Could not save progress_snapshot for run %s: %s", run_id, exc)


def fail_run(run_id: str, error_message: str) -> None:
    """Update run to status='failed'."""
    if not run_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        get_supabase().table("discovery_runs").update({
            "finished_at": now,
            "status": "failed",
            "error_message": str(error_message)[:2000],
        }).eq("id", run_id).execute()
    except Exception as exc:
        logger.error("Could not fail discovery_run %s: %s", run_id, exc)


def list_runs(limit: int = 20) -> List[Dict[str, Any]]:
    """Return recent discovery_runs rows ordered by started_at DESC."""
    try:
        rows = (
            get_supabase()
            .table("discovery_runs")
            .select("*")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        return rows
    except Exception as exc:
        logger.error("Could not list discovery_runs: %s", exc)
        return []


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Return a single run row by ID."""
    if not run_id:
        return None
    try:
        rows = (
            get_supabase()
            .table("discovery_runs")
            .select("*")
            .eq("id", run_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception as exc:
        logger.error("Could not get discovery_run %s: %s", run_id, exc)
        return None
