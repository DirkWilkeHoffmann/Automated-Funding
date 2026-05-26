"""Stats endpoint — aggregated fund, discovery, and org data for the dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from api import dependencies
from utils.db.client import get_supabase

router = APIRouter(prefix="/stats", tags=["stats"])

_ELIGIBILITY_BUCKETS = [
    "Highly Eligible",
    "Eligible",
    "Possibly Eligible",
    "Low Match",
    "Not Eligible",
]


@router.get("")
def get_stats(user=Depends(dependencies.require_user)) -> dict:
    """Return aggregated stats across funds, discovery runs, and org profile."""
    supabase = get_supabase()

    # ── Funds ─────────────────────────────────────────────────────────────────
    try:
        resp = supabase.table("funds").select(
            "eligibility,grant_type,discovery_source,created_at"
        ).execute()
        fund_rows = resp.data or []
    except Exception:
        fund_rows = []

    by_eligibility: dict[str, int] = {k: 0 for k in _ELIGIBILITY_BUCKETS}
    by_grant_type: dict[str, int] = {}
    by_discovery_source: dict[str, int] = {}
    added_last_7d = 0
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    for r in fund_rows:
        elig = r.get("eligibility") or ""
        if elig in by_eligibility:
            by_eligibility[elig] += 1

        gt = r.get("grant_type") or "other"
        by_grant_type[gt] = by_grant_type.get(gt, 0) + 1

        ds = r.get("discovery_source") or ""
        if ds:
            by_discovery_source[ds] = by_discovery_source.get(ds, 0) + 1

        created = r.get("created_at") or ""
        if created >= week_ago:
            added_last_7d += 1

    funds_stats = {
        "total": len(fund_rows),
        "by_eligibility": by_eligibility,
        "by_grant_type": by_grant_type,
        "by_discovery_source": by_discovery_source,
        "added_last_7d": added_last_7d,
    }

    # ── Discovery runs ────────────────────────────────────────────────────────
    try:
        last_resp = (
            supabase.table("discovery_runs")
            .select("*")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        last_run_rows = last_resp.data or []
        last_run_row = last_run_rows[0] if last_run_rows else None
    except Exception:
        last_run_row = None

    try:
        all_runs_resp = (
            supabase.table("discovery_runs")
            .select("id,urls_new")
            .execute()
        )
        all_runs = all_runs_resp.data or []
        total_runs = len(all_runs)
        total_urls_found = sum(r.get("urls_new") or 0 for r in all_runs)
    except Exception:
        total_runs = 0
        total_urls_found = 0

    last_run_summary = None
    if last_run_row:
        last_run_summary = {
            "id": last_run_row.get("id", ""),
            "status": last_run_row.get("status", "unknown"),
            "urls_discovered": int(last_run_row.get("urls_discovered") or 0),
            "urls_new": int(last_run_row.get("urls_new") or 0),
            "started_at": last_run_row.get("started_at"),
            "trigger": last_run_row.get("trigger", "scheduled"),
        }

    discovery_stats = {
        "last_run": last_run_summary,
        "total_runs": total_runs,
        "total_urls_found": total_urls_found,
    }

    # ── Org profile ───────────────────────────────────────────────────────────
    try:
        org_resp = (
            supabase.table("organizations")
            .select("name,state,mission,services,city,ein")
            .limit(1)
            .execute()
        )
        org_rows = org_resp.data or []
        org = org_rows[0] if org_rows else None
    except Exception:
        org = None

    missing_fields: list[str] = []
    if org:
        if not org.get("name"):
            missing_fields.append("name")
        if not org.get("state"):
            missing_fields.append("state")
        if not org.get("mission"):
            missing_fields.append("mission")
        if not org.get("ein"):
            missing_fields.append("ein")
    else:
        missing_fields = ["name", "state", "mission", "ein"]

    org_stats = {
        "name": org.get("name") if org else None,
        "state": org.get("state") if org else None,
        "profile_complete": len(missing_fields) == 0,
        "missing_fields": missing_fields,
    }

    return {
        "funds": funds_stats,
        "discovery": discovery_stats,
        "org": org_stats,
    }
