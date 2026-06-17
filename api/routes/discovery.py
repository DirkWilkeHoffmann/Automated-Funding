"""Discovery endpoints — superuser only."""

from __future__ import annotations

import threading
import time
import logging

from fastapi import APIRouter, Depends, HTTPException

from api import dependencies
from api.schemas import (
    APIKeyHealth,
    DatasetBrowseResponse,
    DiscoveryConfigRequest,
    DiscoveryConfigResponse,
    DiscoveryHealthResponse,
    DiscoveryImportStatusResponse,
    DiscoveryProgressResponse,
    DiscoveryRunResponse,
    DiscoverySourceProgress,
    ImportConfig,
    PreFilterFunnel,
    PreFilterFunnelStage,
    PreFilterPreviewResponse,
    TargetingConfirmRequest,
    TargetingDeriveRequest,
    TargetingSuggestion,
    TargetingStatusResponse,
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
            "federal_register": bool(sources_raw.get("federal_register", True)),
            "state_portals": bool(sources_raw.get("state_portals", True)),
            "candid": bool(sources_raw.get("candid", False)),
            "irs_bmf": bool(sources_raw.get("irs_bmf", True)),
            "grants_gov_db": bool(sources_raw.get("grants_gov_db", True)),
            "sam_cfda_db": bool(sources_raw.get("sam_cfda_db", True)),
        },
        max_per_source=int(row.get("max_per_source") or 100),
        documents_per_run=int(row.get("documents_per_run") or 200),
        import_config=ImportConfig(
            bmf_min_asset_code=int(import_cfg_raw.get("bmf_min_asset_code") or 7),
            bmf_ntee_prefixes=import_cfg_raw.get("bmf_ntee_prefixes") or [],
            bmf_batch_size=int(import_cfg_raw.get("bmf_batch_size") or 50),
            grants_gov_close_days=int(import_cfg_raw.get("grants_gov_close_days") or 90),
            grants_gov_nonprofit_filter=bool(import_cfg_raw.get("grants_gov_nonprofit_filter", True)),
            bmf_cron=import_cfg_raw.get("bmf_cron") or "0 3 * * 0",
            irs_990_index_cron=import_cfg_raw.get("irs_990_index_cron") or "0 4 * * 0",
            grants_gov_cron=import_cfg_raw.get("grants_gov_cron") or "0 5 * * *",
            sam_cfda_cron=import_cfg_raw.get("sam_cfda_cron") or "0 6 * * 0",
            bmf_last_imported_at=import_cfg_raw.get("bmf_last_imported_at"),
            grants_gov_last_imported_at=import_cfg_raw.get("grants_gov_last_imported_at"),
            sam_cfda_last_imported_at=import_cfg_raw.get("sam_cfda_last_imported_at"),
            irs_990_index_last_imported_at=import_cfg_raw.get("irs_990_index_last_imported_at"),
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
    """Save discovery config. Dynamically reschedules the APScheduler jobs
    if any cron expression changed (discovery cron OR per-dataset import crons)."""
    old_config = load_config()
    old_cron = old_config.get("cron_expression") or "0 2 * * 1"
    old_import = old_config.get("import_config") or {}

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

    # Reschedule per-dataset import jobs if any of their cron expressions changed.
    new_import = data.get("import_config") or {}
    cron_keys = ("bmf_cron", "irs_990_index_cron", "grants_gov_cron", "sam_cfda_cron")
    if any(new_import.get(k) != old_import.get(k) for k in cron_keys):
        try:
            from utils.discovery.scheduler import reschedule_imports
            reschedule_imports()
        except Exception as exc:
            logger.warning("Could not reschedule import jobs: %s", exc)

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


@router.post("/import/irs-990-index", status_code=202)
def trigger_irs_990_index_import(user=Depends(dependencies.require_superuser)):
    """Trigger an IRS 990 e-file index refresh (current + previous year)."""
    def _run() -> None:
        try:
            from datetime import datetime, timezone
            from utils.discovery.sources.irs_990_index import refresh_index_for_year
            current_year = datetime.now(timezone.utc).year
            for year in (current_year - 1, current_year):
                try:
                    refresh_index_for_year(year, force=True)
                except Exception as exc:
                    logger.warning("990 index refresh for %s failed: %s", year, exc)
        except Exception as exc:
            logger.error("IRS 990 index import failed: %s", exc, exc_info=True)

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": "IRS 990 e-file index refresh started in background"}


@router.post("/import/sam-cfda", status_code=202)
def trigger_sam_cfda_import(user=Depends(dependencies.require_superuser)):
    """Trigger a SAM.gov Assistance Listings (CFDA) refresh in a background thread."""
    def _run() -> None:
        try:
            from utils.discovery.importers.sam_cfda import run_sam_cfda_import
            run_sam_cfda_import()
        except Exception as exc:
            logger.error("SAM.gov CFDA import failed: %s", exc, exc_info=True)

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "message": "SAM.gov CFDA import started in background"}


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

    try:
        sam_total = (
            get_supabase().table("sam_cfda_listings").select("program_number", count="exact").execute().count or 0
        )
    except Exception:
        # Table may not exist yet (Phase 1 migration deferred) — count of 0 is the right signal.
        sam_total = 0

    try:
        irs_total = (
            get_supabase().table("irs_990_index").select("ein", count="exact").execute().count or 0
        )
    except Exception:
        irs_total = 0

    return DiscoveryImportStatusResponse(
        bmf_last_imported_at=import_cfg.get("bmf_last_imported_at"),
        grants_gov_last_imported_at=import_cfg.get("grants_gov_last_imported_at"),
        sam_cfda_last_imported_at=import_cfg.get("sam_cfda_last_imported_at"),
        irs_990_index_last_imported_at=import_cfg.get("irs_990_index_last_imported_at"),
        bmf_funders_total=bmf_total,
        bmf_funders_unscraped=bmf_unscraped,
        grant_opportunities_total=opp_total,
        grant_opportunities_open=opp_open,
        sam_cfda_total=sam_total,
        irs_990_index_total=irs_total,
    )


# ── Health: API-key status + org-profile completeness ───────────────────────


def _api_key_status(service: str, *, validate_fn=None) -> APIKeyHealth:
    """Look up an api_tokens row + optionally cheap-test the key."""
    from utils.db.client import get_supabase
    try:
        rows = (
            get_supabase()
            .table("api_tokens")
            .select("key_value, updated_at")
            .eq("service", service)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        return APIKeyHealth(name=service, status="unknown", detail=str(exc))
    if not rows or not (rows[0].get("key_value") or "").strip():
        return APIKeyHealth(name=service, status="missing")
    key = rows[0]["key_value"]
    if validate_fn is None:
        return APIKeyHealth(name=service, status="ok")
    try:
        ok, detail = validate_fn(key)
        return APIKeyHealth(name=service, status="ok" if ok else "invalid", detail=detail)
    except Exception as exc:
        return APIKeyHealth(name=service, status="invalid", detail=str(exc))


def _validate_openai(key: str):
    """Cheap probe — list the first model. 401 = invalid; anything else = ok."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        # /models is one of the cheapest authenticated endpoints.
        next(iter(client.models.list()), None)
        return True, None
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "Incorrect API key" in msg or "invalid_api_key" in msg:
            return False, "Authentication failed (401)"
        # Network errors etc. — don't claim invalid, just unknown
        return True, f"Could not fully validate: {msg[:80]}"


@router.get("/health", response_model=DiscoveryHealthResponse)
def get_discovery_health(user=Depends(dependencies.require_superuser)):
    """API key + org-profile completeness check. Cheap auth-probes per key."""
    keys = [
        _api_key_status("openai", validate_fn=_validate_openai),
        _api_key_status("brave_search"),
        _api_key_status("sam_gov"),
        _api_key_status("candid"),
    ]

    # Org-profile completeness — which Phase 3 fields are missing?
    from utils.db.client import get_supabase
    missing: list[str] = []
    org_complete = False
    try:
        rows = get_supabase().table("organizations").select("*").limit(1).execute().data or []
        org = rows[0] if rows else {}
        if not org.get("service_states") and not org.get("state"):
            missing.append("service_states")
        if not org.get("ntee_codes"):
            missing.append("ntee_codes")
        if "accepts_unsolicited" not in org or org.get("accepts_unsolicited") is None:
            missing.append("accepts_unsolicited")
        if not org.get("applicant_types"):
            missing.append("applicant_types")
        org_complete = not missing
    except Exception as exc:
        logger.debug("org-profile completeness check failed: %s", exc)

    return DiscoveryHealthResponse(
        keys=keys,
        org_profile_complete=org_complete,
        org_profile_missing=missing,
    )


# ── Pre-filter preview ──────────────────────────────────────────────────────


@router.get("/prefilter-preview", response_model=PreFilterPreviewResponse)
def get_prefilter_preview(user=Depends(dependencies.require_superuser)):
    """Run the same filter pipeline the orchestrator uses, but return only the
    funnel counts. Lets the UI tell the user how many candidates a discovery
    run would actually consider before they hit "Run now"."""
    from supabase import create_client
    from utils.config import get_settings
    from utils.discovery.prefilter import (
        filter_funders, filter_opportunities, load_org_profile,
    )
    _s = get_settings()
    sb = create_client(_s.supabase_url, _s.supabase_service_key)

    cfg = load_config()
    ic = cfg.get("import_config") or {}
    org = load_org_profile()
    explicit_states = [s.upper() for s in (cfg.get("states") or [])]
    if explicit_states:
        org.service_states = explicit_states

    funder = filter_funders(
        sb, org,
        min_asset_code=int(ic.get("bmf_min_asset_code") or 7),
        ntee_prefixes=ic.get("bmf_ntee_prefixes") or [],
        limit=int(ic.get("bmf_batch_size") or 50),
        only_unscraped=True,
    )
    opp = filter_opportunities(
        sb, org,
        close_days=int(ic.get("grants_gov_close_days") or 90),
        nonprofit_filter=bool(ic.get("grants_gov_nonprofit_filter", True)),
        limit=int(cfg.get("max_per_source") or 100),
    )

    def to_funnel(t) -> PreFilterFunnel:
        return PreFilterFunnel(
            name=t.name,
            stages=[PreFilterFunnelStage(label=s["label"], count=s["count"]) for s in t.stages],
        )
    return PreFilterPreviewResponse(
        funders=to_funnel(funder.telemetry),
        opportunities=to_funnel(opp.telemetry),
    )


# ── Dataset browse views ────────────────────────────────────────────────────


_BROWSE_TABLES = {
    "discovery-funders":   ("discovery_funders",   "ein",            "asset_amount"),
    "grant-opportunities": ("grant_opportunities", "opportunity_id", "close_date"),
    "irs-990-index":       ("irs_990_index",       "ein",            "tax_year"),
    "sam-cfda":            ("sam_cfda_listings",   "program_number", "program_title"),
}


@router.get("/datasets/{name}", response_model=DatasetBrowseResponse)
def browse_dataset(
    name: str,
    limit: int = 25,
    offset: int = 0,
    state: str | None = None,
    user=Depends(dependencies.require_superuser),
):
    """Paginated read-only browse for the 4 bulk datasets.

    Supports optional `state` filter on the BMF table. Other filters can be
    added later; this is the v1 surface for the dataset explorer pages.
    """
    if name not in _BROWSE_TABLES:
        raise HTTPException(status_code=404, detail=f"Unknown dataset {name!r}")
    table, pk, sort_col = _BROWSE_TABLES[name]
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    from utils.db.client import get_supabase
    sb = get_supabase()

    q = sb.table(table).select("*", count="exact")
    if state and table == "discovery_funders":
        q = q.eq("state", state.upper())
    # Descending on numeric/date columns, ascending on text titles
    if sort_col in ("asset_amount", "close_date", "tax_year"):
        q = q.order(sort_col, desc=True, nullsfirst=False)
    else:
        q = q.order(sort_col)
    try:
        res = q.range(offset, offset + limit - 1).execute()
        rows = res.data or []
        total = res.count or 0
    except Exception as exc:
        logger.warning("dataset browse failed for %s: %s", name, exc)
        rows, total = [], 0

    return DatasetBrowseResponse(
        dataset=name,
        rows=rows,
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Targeting profile (Phase 11) ──────────────────────────────────────────────


def _targeting_row_to_status(row: dict) -> TargetingStatusResponse:
    return TargetingStatusResponse(
        targeting_confirmed=bool(row.get("targeting_confirmed", False)),
        targeting_updated_at=row.get("targeting_updated_at"),
        client_embedding_set=row.get("client_embedding") is not None,
        ntee_prefixes=list(row.get("ntee_codes") or []),
        cfda_categories=list(row.get("cfda_categories") or []),
        cause_keywords=list(row.get("cause_keywords") or []),
        applicant_codes=list(row.get("eligible_applicant_codes") or []),
    )


@router.get("/targeting", response_model=TargetingStatusResponse)
def get_targeting(user=Depends(dependencies.require_superuser)):
    """Return the current targeting profile state for the single org."""
    from utils.db.client import get_supabase
    try:
        rows = get_supabase().table("organizations").select("*").limit(1).execute().data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    if not rows:
        return TargetingStatusResponse()
    return _targeting_row_to_status(rows[0])


@router.post("/targeting/derive", response_model=TargetingSuggestion)
def derive_targeting_endpoint(
    payload: TargetingDeriveRequest,
    user=Depends(dependencies.require_superuser),
):
    """Ask GPT-4o to suggest NTEE/CFDA/keyword targeting from a mission. No DB write."""
    from utils.discovery.targeting import derive_targeting
    result = derive_targeting(
        payload.mission,
        website=payload.website,
        ein=payload.ein,
    )
    return TargetingSuggestion(**result)


@router.put("/targeting", response_model=TargetingStatusResponse)
def confirm_targeting(
    payload: TargetingConfirmRequest,
    user=Depends(dependencies.require_superuser),
):
    """Persist confirmed targeting fields, compute client embedding, mark confirmed."""
    from datetime import datetime, timezone
    from utils.db.client import get_supabase
    from utils.discovery.targeting import TargetingProfile, build_client_embedding

    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    update: dict = {
        "ntee_codes": payload.ntee_prefixes,
        "cfda_categories": payload.cfda_categories,
        "cause_keywords": payload.cause_keywords,
        "eligible_applicant_codes": payload.applicant_codes,
        "targeting_confirmed": True,
        "targeting_updated_at": now,
    }

    # Build + store the client embedding.
    try:
        rows = sb.table("organizations").select("*").limit(1).execute().data or []
        row = rows[0] if rows else {}
        profile = TargetingProfile.from_org_row({**row, **update})
        vec = build_client_embedding(profile)
        if vec is not None:
            update["client_embedding"] = vec
    except Exception as exc:
        logger.warning("Could not build client embedding: %s", exc)

    try:
        rows = sb.table("organizations").select("id").limit(1).execute().data or []
        if not rows:
            raise HTTPException(status_code=404, detail="No organisation record found")
        org_id = rows[0]["id"]
        updated = (
            sb.table("organizations").update(update).eq("id", org_id).execute().data or []
        )
        row = updated[0] if updated else {**rows[0], **update}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB update failed: {exc}")

    return _targeting_row_to_status(row)
