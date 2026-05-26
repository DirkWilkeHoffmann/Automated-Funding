"""Discovery endpoints — superuser only."""

from __future__ import annotations

import threading
import time
import logging

from fastapi import APIRouter, Depends, HTTPException

from api import dependencies
from api.schemas import (
    DiscoveryConfigRequest,
    DiscoveryConfigResponse,
    DiscoveryImportStatusResponse,
    DiscoveryProgressResponse,
    DiscoveryRunResponse,
    DiscoverySourceProgress,
    ImportConfig,
)
from utils.discovery.config_store import load_config, save_config
from utils.discovery.progress_registry import progress_registry
from utils.discovery.run_store import get_run, list_runs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discovery", tags=["discovery"])


def _serialize_config(row: dict) -> DiscoveryConfigResponse:
    sources_raw = row.get("sources") or {}
    import_cfg_raw = row.get("import_config") or {}
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
            "web_search": bool(sources_raw.get("web_search", True)),
            "federal_register": bool(sources_raw.get("federal_register", True)),
            "state_portals": bool(sources_raw.get("state_portals", True)),
            "usaspending": bool(sources_raw.get("usaspending", False)),
            "candid": bool(sources_raw.get("candid", False)),
            "philanthropy_digest": bool(sources_raw.get("philanthropy_digest", False)),
            "irs_bmf": bool(sources_raw.get("irs_bmf", True)),
            "grants_gov_db": bool(sources_raw.get("grants_gov_db", True)),
        },
        max_per_source=int(row.get("max_per_source") or 100),
        documents_per_run=int(row.get("documents_per_run") or 200),
        import_config=ImportConfig(
            bmf_min_asset_code=int(import_cfg_raw.get("bmf_min_asset_code") or 7),
            bmf_ntee_prefixes=import_cfg_raw.get("bmf_ntee_prefixes") or [],
            bmf_batch_size=int(import_cfg_raw.get("bmf_batch_size") or 50),
            grants_gov_close_days=int(import_cfg_raw.get("grants_gov_close_days") or 90),
            bmf_last_imported_at=import_cfg_raw.get("bmf_last_imported_at"),
            grants_gov_last_imported_at=import_cfg_raw.get("grants_gov_last_imported_at"),
        ),
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
        progress_snapshot=row.get("progress_snapshot"),
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
    Returns immediately with a run_id; poll GET /discovery/runs/{run_id}/progress for live state.
    """
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


@router.get("/runs/{run_id}/scraped-funds")
def get_run_scraped_funds(
    run_id: str,
    user=Depends(dependencies.require_superuser),
):
    """Return funds in the DB that were scraped as part of this run's scrape job."""
    row = get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    scrape_job_id = row.get("scrape_job_id")
    if not scrape_job_id:
        return []

    from utils.db.client import get_supabase
    sb = get_supabase()
    try:
        job_rows = sb.table("scrape_jobs").select("urls").eq("id", scrape_job_id).limit(1).execute().data or []
        if not job_rows:
            return []
        urls = job_rows[0].get("urls") or []
        if not urls:
            return []

        funds: list = []
        for i in range(0, len(urls), 100):
            batch = urls[i : i + 100]
            rows = (
                sb.table("funds")
                .select("fund_url,funder_name,eligibility,grant_type,discovery_source")
                .in_("fund_url", batch)
                .execute()
                .data or []
            )
            funds.extend(rows)
        return funds
    except Exception as exc:
        logger.error("Could not fetch scraped funds for run %s: %s", run_id, exc)
        return []


# ── Live progress + cancel ───────────────────────────────────────────────────


@router.get("/runs/{run_id}/progress", response_model=DiscoveryProgressResponse)
def get_run_progress(
    run_id: str,
    user=Depends(dependencies.require_superuser),
):
    """Return live per-source progress for a discovery run.

    Reads from the in-memory registry while the run is in flight; falls back
    to the persisted progress_snapshot if the run has finished or the API
    process has restarted.
    """
    live = progress_registry.get(run_id)
    if live is not None:
        snap = live.to_snapshot()
        snap["live"] = True
        return _progress_from_snapshot(snap)

    row = get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    snap = row.get("progress_snapshot") or {}
    snap.setdefault("run_id", run_id)
    snap.setdefault("status", row.get("status", "unknown"))
    snap.setdefault("urls_discovered", row.get("urls_discovered", 0))
    snap.setdefault("urls_new", row.get("urls_new", 0))
    snap.setdefault("scrape_job_id", row.get("scrape_job_id"))
    snap["live"] = False
    return _progress_from_snapshot(snap)


@router.post("/runs/{run_id}/cancel", response_model=DiscoveryProgressResponse)
def cancel_run(
    run_id: str,
    user=Depends(dependencies.require_superuser),
):
    """Request cancellation of an in-flight discovery run."""
    if not progress_registry.cancel(run_id):
        raise HTTPException(status_code=404, detail="No live run with that id (already finished?)")
    live = progress_registry.get(run_id)
    snap = live.to_snapshot() if live else {"run_id": run_id, "status": "cancelled"}
    snap["live"] = True
    return _progress_from_snapshot(snap)


def _progress_from_snapshot(snap: dict) -> DiscoveryProgressResponse:
    sources_dict = snap.get("sources") or {}
    sources = {
        name: DiscoverySourceProgress(**sp) if isinstance(sp, dict) else sp
        for name, sp in sources_dict.items()
    }
    started_at = snap.get("started_at")
    finished_at = snap.get("finished_at")
    if started_at:
        elapsed = int((finished_at or time.time()) - started_at)
    else:
        elapsed = 0
    return DiscoveryProgressResponse(
        run_id=snap.get("run_id", ""),
        status=snap.get("status", "unknown"),
        sources=sources,
        urls_discovered=int(snap.get("urls_discovered") or 0),
        urls_new=int(snap.get("urls_new") or 0),
        documents_submitted=int(snap.get("documents_submitted") or 0),
        documents_downloaded=int(snap.get("documents_downloaded") or 0),
        documents_extracted=int(snap.get("documents_extracted") or 0),
        documents_skipped_dedup=int(snap.get("documents_skipped_dedup") or 0),
        documents_errors=int(snap.get("documents_errors") or 0),
        scrape_job_id=snap.get("scrape_job_id"),
        latest_results=snap.get("latest_results") or [],
        started_at=started_at,
        finished_at=finished_at,
        error=snap.get("error"),
        elapsed_seconds=max(0, elapsed),
        live=bool(snap.get("live", False)),
    )


# ── Import triggers ───────────────────────────────────────────────────────────


@router.post("/import/bmf", status_code=202)
def trigger_bmf_import(user=Depends(dependencies.require_superuser)):
    """Trigger an IRS BMF import in a background thread. Returns immediately."""
    def _run() -> None:
        try:
            from utils.discovery.importers.irs_bmf import run_bmf_import
            run_bmf_import()
        except Exception as exc:
            logger.error("BMF import failed: %s", exc, exc_info=True)

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": "IRS BMF import started in background"}


@router.post("/import/grants-gov", status_code=202)
def trigger_grants_gov_import(user=Depends(dependencies.require_superuser)):
    """Trigger a Grants.gov XML import in a background thread. Returns immediately."""
    def _run() -> None:
        try:
            from utils.discovery.importers.grants_gov_xml import run_grants_gov_import
            run_grants_gov_import()
        except Exception as exc:
            logger.error("Grants.gov import failed: %s", exc, exc_info=True)

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": "Grants.gov XML import started in background"}


@router.get("/import/status", response_model=DiscoveryImportStatusResponse)
def get_import_status(user=Depends(dependencies.require_superuser)):
    """Return last import timestamps and row counts for BMF and Grants.gov databases."""
    from datetime import datetime, timezone
    from utils.db.client import get_supabase
    from utils.discovery.config_store import load_import_config

    import_cfg = load_import_config()
    today = datetime.now(timezone.utc).date().isoformat()

    try:
        bmf_total = (
            get_supabase().table("discovery_funders").select("ein", count="exact").execute().count or 0
        )
    except Exception:
        bmf_total = 0

    try:
        bmf_unscraped = (
            get_supabase()
            .table("discovery_funders")
            .select("ein", count="exact")
            .is_("scraped_at", "null")
            .execute()
            .count or 0
        )
    except Exception:
        bmf_unscraped = 0

    try:
        opp_total = (
            get_supabase().table("grant_opportunities").select("opportunity_id", count="exact").execute().count or 0
        )
    except Exception:
        opp_total = 0

    try:
        opp_open = (
            get_supabase()
            .table("grant_opportunities")
            .select("opportunity_id", count="exact")
            .gte("close_date", today)
            .execute()
            .count or 0
        )
    except Exception:
        opp_open = 0

    return DiscoveryImportStatusResponse(
        bmf_last_imported_at=import_cfg.get("bmf_last_imported_at"),
        grants_gov_last_imported_at=import_cfg.get("grants_gov_last_imported_at"),
        bmf_funders_total=bmf_total,
        bmf_funders_unscraped=bmf_unscraped,
        grant_opportunities_total=opp_total,
        grant_opportunities_open=opp_open,
    )
