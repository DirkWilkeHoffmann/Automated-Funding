"""Discovery endpoints — superuser only."""

from __future__ import annotations

import threading
import logging

from fastapi import APIRouter, Depends, HTTPException

from api import dependencies
from api.schemas import (
    DiscoveryConfigRequest,
    DiscoveryConfigResponse,
    DiscoveryRunResponse,
)
from utils.discovery.config_store import load_config, save_config
from utils.discovery.run_store import get_run, list_runs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discovery", tags=["discovery"])


def _serialize_config(row: dict) -> DiscoveryConfigResponse:
    sources_raw = row.get("sources") or {}
    return DiscoveryConfigResponse(
        id=row.get("id"),
        enabled=bool(row.get("enabled", False)),
        cron_expression=row.get("cron_expression") or "0 2 * * 1",
        states=row.get("states") or [],
        keywords=row.get("keywords") or [],
        sources={
            "propublica": bool(sources_raw.get("propublica", True)),
            "grants_gov": bool(sources_raw.get("grants_gov", True)),
            "sam_gov": bool(sources_raw.get("sam_gov", False)),
        },
        max_per_source=int(row.get("max_per_source") or 100),
        updated_at=row.get("updated_at"),
    )


def _serialize_run(row: dict) -> DiscoveryRunResponse:
    return DiscoveryRunResponse(
        id=row.get("id", ""),
        started_at=row.get("started_at", ""),
        finished_at=row.get("finished_at"),
        status=row.get("status", "unknown"),
        trigger=row.get("trigger", "scheduled"),
        urls_discovered=int(row.get("urls_discovered") or 0),
        urls_new=int(row.get("urls_new") or 0),
        scrape_job_id=row.get("scrape_job_id"),
        error_message=row.get("error_message"),
    )


# ── Config ────────────────────────────────────────────────────────────────────


@router.get("/config", response_model=DiscoveryConfigResponse)
def get_config(user=Depends(dependencies.require_superuser)):
    """Return the current discovery configuration."""
    config = load_config()
    return _serialize_config(config)


@router.put("/config", response_model=DiscoveryConfigResponse)
def update_config(
    payload: DiscoveryConfigRequest,
    user=Depends(dependencies.require_superuser),
):
    """Save discovery config. Dynamically reschedules the APScheduler job if cron changed."""
    old_config = load_config()
    old_cron = old_config.get("cron_expression") or "0 2 * * 1"

    data = payload.model_dump()
    data["sources"] = payload.sources.model_dump()

    saved = save_config(data)

    new_cron = data.get("cron_expression") or "0 2 * * 1"
    if new_cron != old_cron:
        try:
            from utils.discovery.scheduler import reschedule_discovery
            reschedule_discovery(new_cron)
        except Exception as exc:
            logger.warning("Could not reschedule discovery job: %s", exc)

    return _serialize_config(saved)


# ── Manual trigger ────────────────────────────────────────────────────────────


@router.post("/run", response_model=DiscoveryRunResponse, status_code=202)
def trigger_run(user=Depends(dependencies.require_superuser)):
    """
    Kick off a manual discovery run in a background thread.
    Returns immediately with a run_id; poll GET /discovery/runs/{run_id} for status.
    """
    from utils.discovery.orchestrator import run_discovery
    from utils.discovery.run_store import create_run
    from utils.discovery.config_store import load_config as _load

    config = _load()

    # Pre-create the run record so we can return the ID immediately.
    run_id = create_run("manual", config)

    def _run_in_background() -> None:
        try:
            from utils.discovery.orchestrator import run_discovery as _rd
            _rd(trigger="manual", run_id=run_id)
        except Exception as exc:
            logger.error("Manual discovery run failed: %s", exc, exc_info=True)

    threading.Thread(target=_run_in_background, daemon=True).start()

    # Return a provisional response; the client should poll for updates.
    return DiscoveryRunResponse(
        id=run_id,
        started_at="",
        status="running",
        trigger="manual",
    )


# ── Run history ───────────────────────────────────────────────────────────────


@router.get("/runs", response_model=list[DiscoveryRunResponse])
def list_discovery_runs(
    limit: int = 20,
    user=Depends(dependencies.require_superuser),
):
    """Return recent discovery run records."""
    rows = list_runs(limit=limit)
    return [_serialize_run(r) for r in rows]


@router.get("/runs/{run_id}", response_model=DiscoveryRunResponse)
def get_discovery_run(
    run_id: str,
    user=Depends(dependencies.require_superuser),
):
    """Return a single discovery run by ID."""
    row = get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(row)
