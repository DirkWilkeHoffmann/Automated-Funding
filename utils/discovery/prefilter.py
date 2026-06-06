"""Org-profile-driven pre-filter for discovery sources.

Before IRS_BMF_Source and GrantsGovDBSource ask Supabase for candidates, this
module turns the operator's organisation profile (states served, NTEE focus,
applicant types, grant-size window, cost-share posture) into:

  * server-side Supabase query predicates (state IN, ntee_code LIKE, etc.)
  * client-side Python predicates that can't be expressed in PostgREST easily
    (TEXT[] code intersection, NTEE prefix array matching)
  * a telemetry funnel so the UI can show how many candidates each stage
    removed

The goal is to send a few hundred truly relevant rows into the LLM extractor
instead of churning through a million-row table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from utils.discovery.grants_gov_codes import applies_to_org

logger = logging.getLogger(__name__)

# Community-foundation-style NTEE codes that typically only fund invitees.
# We drop these from BMF results when the org has accepts_unsolicited=False.
_INVITATION_ONLY_NTEE_PREFIXES: List[str] = ["T20", "T21", "T22", "T31"]


@dataclass
class OrgProfile:
    """Subset of the organizations row used by the pre-filter."""

    state: Optional[str] = None
    ntee_codes: List[str] = field(default_factory=list)
    service_states: List[str] = field(default_factory=list)
    applicant_types: List[str] = field(default_factory=list)
    accepts_unsolicited: bool = True
    can_cost_share: bool = True
    min_grant_size: Optional[int] = None
    max_grant_size: Optional[int] = None
    # Phase 5 — RFP topic filter
    cfda_categories: List[str] = field(default_factory=list)
    eligible_applicant_codes: List[str] = field(default_factory=list)
    # Phase 3 — foundation pipeline (mission text + extracted keywords)
    mission: Optional[str] = None
    services: List[str] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: Dict[str, Any] | None) -> "OrgProfile":
        if not row:
            return cls()
        # services may be either a TEXT[] or a comma-separated TEXT depending on
        # how the org profile was saved. Normalise to list[str].
        svcs_raw = row.get("services")
        if isinstance(svcs_raw, str):
            services = [s.strip() for s in svcs_raw.split(",") if s.strip()]
        elif isinstance(svcs_raw, list):
            services = [str(s).strip() for s in svcs_raw if str(s).strip()]
        else:
            services = []
        return cls(
            state=(row.get("state") or None),
            ntee_codes=list(row.get("ntee_codes") or []),
            service_states=[s.upper() for s in (row.get("service_states") or [])],
            applicant_types=list(row.get("applicant_types") or []),
            accepts_unsolicited=bool(row.get("accepts_unsolicited", True)),
            can_cost_share=bool(row.get("can_cost_share", True)),
            min_grant_size=row.get("min_grant_size"),
            max_grant_size=row.get("max_grant_size"),
            cfda_categories=[c.upper() for c in (row.get("cfda_categories") or []) if c],
            eligible_applicant_codes=[
                str(c).zfill(2) for c in (row.get("eligible_applicant_codes") or []) if str(c).strip()
            ],
            mission=row.get("mission"),
            services=services,
        )

    def mission_keywords(self) -> List[str]:
        """Topical keywords derived from mission + services for foundation matching.

        Used by Phase 3 foundation pipeline to check program_areas overlap.
        Returns a deduplicated lowercase list of meaningful tokens (>3 chars,
        no stopwords).
        """
        STOP = {
            "the", "and", "for", "with", "from", "our", "are", "this", "that",
            "their", "they", "have", "has", "been", "into", "what", "when",
            "where", "which", "while", "your", "you", "any", "all", "but",
            "not", "out", "more", "than", "such", "also", "about", "well",
            "non", "nonprofit", "501c3", "organization",
        }
        parts: List[str] = []
        if self.mission:
            parts.extend(self.mission.split())
        for svc in self.services[:10]:
            parts.extend(svc.split())
        seen: set = set()
        out: List[str] = []
        for w in parts:
            wl = "".join(c for c in w.lower() if c.isalpha())
            if len(wl) <= 3 or wl in STOP or wl in seen:
                continue
            seen.add(wl)
            out.append(wl)
        return out

    def effective_states(self) -> List[str]:
        """States the org actively serves — `service_states` overrides HQ state."""
        if self.service_states:
            return self.service_states
        if self.state:
            return [self.state.upper()]
        return []


def load_org_profile() -> OrgProfile:
    """Load the single org profile (cached upstream by org_store)."""
    try:
        from utils.db.org_store import _get_org_cached  # type: ignore[attr-defined]
        row = _get_org_cached()
        return OrgProfile.from_row(row)
    except Exception as exc:
        logger.warning("Could not load org profile for prefilter: %s", exc)
        return OrgProfile()


# ── Telemetry ────────────────────────────────────────────────────────────────


@dataclass
class FilterTelemetry:
    """Per-stage counts so the orchestrator can render a funnel."""

    name: str
    stages: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, label: str, count: int) -> None:
        self.stages.append({"label": label, "count": count})

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "stages": list(self.stages)}


# ── BMF funder filter ────────────────────────────────────────────────────────


@dataclass
class FunderFilterResult:
    rows: List[Dict[str, Any]]
    telemetry: FilterTelemetry


def filter_funders(
    sb,
    org: OrgProfile,
    *,
    min_asset_code: int = 7,
    ntee_prefixes: Optional[List[str]] = None,
    limit: int = 200,
    only_unscraped: bool = True,
) -> FunderFilterResult:
    """Query discovery_funders applying org-profile-aware predicates.

    Predicate order (server-side first, then client-side):
      1. asset_code >= min_asset_code          [server]
      2. state ∈ org.effective_states()        [server, if set]
      3. ntee_code LIKE ANY (ntee_prefixes ∪ org.ntee_codes)  [server, prefix OR]
      4. scraped_at IS NULL                    [server, if only_unscraped]
      5. drop community-foundation NTEEs if org.accepts_unsolicited=False  [client]

    Returns sorted by asset_amount DESC.
    """
    tel = FilterTelemetry(name="discovery_funders")

    # Stage 0: full universe baseline (cheap count, exact)
    try:
        baseline = sb.table("discovery_funders").select("ein", count="exact", head=True).execute().count or 0
    except Exception:
        baseline = 0
    tel.record("all 501(c)(3) in BMF", baseline)

    q = sb.table("discovery_funders").select(
        "ein, name, city, state, zip, ntee_code, foundation_type, subsection, "
        "asset_code, asset_amount, income_amount, revenue_amount, website, "
        "website_resolved_at, scraped_at"
    )

    # Stage 1: state
    states = org.effective_states()
    if states:
        q = q.in_("state", states)
        tel.record(f"in states {','.join(states)}", _safe_head_count(q))

    # Stage 2: NTEE prefix OR (PostgREST `or=` filter with multiple `like` clauses)
    all_prefixes: List[str] = []
    all_prefixes += [p for p in (ntee_prefixes or []) if p]
    all_prefixes += [p for p in org.ntee_codes if p]
    all_prefixes = sorted(set(all_prefixes))
    if all_prefixes:
        # supabase-py expects an OR-filter expressed as a single string:
        #   "or=(ntee_code.like.B*,ntee_code.like.P*)"
        or_clauses = ",".join(f"ntee_code.like.{p}*" for p in all_prefixes)
        q = q.or_(or_clauses)
        tel.record(f"NTEE prefixes {','.join(all_prefixes)}", _safe_head_count(q))

    # Stage 3: minimum asset code
    q = q.gte("asset_code", min_asset_code)
    tel.record(f"asset_code >= {min_asset_code}", _safe_head_count(q))

    # Stage 4: only unscraped
    if only_unscraped:
        q = q.is_("scraped_at", "null")
        tel.record("not yet scraped", _safe_head_count(q))

    # Order + limit. Apply a generous over-fetch so client-side dedup has headroom.
    overfetch = max(limit * 2, 100)
    q = q.order("asset_amount", desc=True).limit(overfetch)

    try:
        rows = q.execute().data or []
    except Exception as exc:
        logger.warning("filter_funders query failed: %s", exc)
        rows = []

    # Stage 5: client-side — drop invitation-only NTEE codes if org won't pursue
    if not org.accepts_unsolicited:
        before = len(rows)
        rows = [
            r for r in rows
            if not any(
                (r.get("ntee_code") or "").startswith(p)
                for p in _INVITATION_ONLY_NTEE_PREFIXES
            )
        ]
        tel.record("accepts_unsolicited filter", len(rows))

    # Stage 6: enforce final limit
    rows = rows[:limit]
    tel.record(f"final limit ({limit})", len(rows))

    return FunderFilterResult(rows=rows, telemetry=tel)


# ── Grants.gov opportunity filter ────────────────────────────────────────────


@dataclass
class OpportunityFilterResult:
    rows: List[Dict[str, Any]]
    telemetry: FilterTelemetry


_NONPROFIT_KEYWORDS = (
    "nonprofit", "non-profit", "501(c)(3)", "501(c)3",
    "community organization", "community-based organization", "charitable organization",
)


def filter_opportunities(
    sb,
    org: OrgProfile,
    *,
    close_days: int = 90,
    nonprofit_filter: bool = True,
    limit: int = 200,
) -> OpportunityFilterResult:
    """Query grant_opportunities applying org-profile-aware predicates.

    Predicate order:
      1. close_date BETWEEN today AND today+close_days       [server]
      2. cost_sharing dropped if org.can_cost_share=False    [server]
      3. award_ceiling >= org.min_grant_size                 [server, when set]
      4. eligibility_text contains nonprofit-ish keyword     [client, when on]
      5. eligible_applicants[] intersects org.applicant_types [client]

    Returns sorted by close_date ASC (most urgent first).
    """
    from datetime import datetime, timedelta, timezone

    tel = FilterTelemetry(name="grant_opportunities")
    today = datetime.now(timezone.utc).date()
    close_floor = today.isoformat()
    close_ceil = (today + timedelta(days=close_days)).isoformat()

    try:
        baseline = (
            sb.table("grant_opportunities")
            .select("opportunity_id", count="exact", head=True)
            .execute()
            .count or 0
        )
    except Exception:
        baseline = 0
    tel.record("all open opportunities", baseline)

    q = sb.table("grant_opportunities").select(
        "opportunity_id, title, agency, agency_code, url, close_date, posted_date, "
        "award_ceiling, award_floor, cfda_number, category, opportunity_category, "
        "funding_instrument_type, eligible_applicants, eligibility_text, "
        "cost_sharing_or_matching_required, description"
    )

    # Stage 1: close-date window
    q = q.gte("close_date", close_floor).lte("close_date", close_ceil)
    tel.record(f"closing within {close_days}d", _safe_head_count(q))

    # Stage 1.5 (Phase 5): CFDA category whitelist
    # Server-side filter on `grant_opportunities.category`. The defense-grant
    # problem (DSCU research grants surfacing for workforce-dev orgs) was
    # because there was no topic gate here. With this in place, an org whose
    # cfda_categories = ['ELT','ISS','ED'] will never see category='ST' grants.
    if org.cfda_categories:
        q = q.in_("category", org.cfda_categories)
        tel.record(
            f"in CFDA categories {','.join(org.cfda_categories)}",
            _safe_head_count(q),
        )

    # Stage 2: cost-share
    if not org.can_cost_share:
        q = q.or_(
            "cost_sharing_or_matching_required.eq.false,"
            "cost_sharing_or_matching_required.is.null"
        )
        tel.record("no cost-share required", _safe_head_count(q))

    # Stage 3: minimum grant size on award_ceiling
    if org.min_grant_size:
        # Keep nulls — many opportunities don't publish ceilings
        q = q.or_(
            f"award_ceiling.gte.{org.min_grant_size},award_ceiling.is.null"
        )
        tel.record(f"ceiling >= ${org.min_grant_size:,}", _safe_head_count(q))

    overfetch = max(limit * 2, 100)
    q = q.order("close_date").limit(overfetch)

    try:
        rows = q.execute().data or []
    except Exception as exc:
        logger.warning("filter_opportunities query failed: %s", exc)
        rows = []

    # Stage 4: nonprofit keyword check (client-side, on eligibility_text)
    if nonprofit_filter:
        def _is_np(r: Dict[str, Any]) -> bool:
            et = (r.get("eligibility_text") or "").lower()
            if not et:
                return True  # unknown — let it through; LLM decides
            return any(kw in et for kw in _NONPROFIT_KEYWORDS)
        rows = [r for r in rows if _is_np(r)]
        tel.record("nonprofit-eligible (keyword)", len(rows))

    # Stage 5: structured applicant-type match
    if org.applicant_types:
        rows = [
            r for r in rows
            if applies_to_org(r.get("eligible_applicants") or [], org.applicant_types)
        ]
        tel.record("applicant-type intersect", len(rows))

    # Stage 5.5 (Phase 5): strict eligible_applicant_codes intersection
    # The defense grant in the May logs listed eligible_applicants only as FFRDCs,
    # academic institutions, and security cooperation workforce — none of which
    # include 501(c)(3) (code '12'). With this gate, the defense grant is dropped
    # because the org's eligible_applicant_codes (e.g. ['12','25']) doesn't
    # intersect the grant's codes.
    if org.eligible_applicant_codes:
        wanted = set(org.eligible_applicant_codes)
        # Grants.gov codes "00", "11", "25", "99" are catch-alls / unrestricted —
        # always pass through (a grant explicitly open to anyone shouldn't be filtered).
        CATCHALL = {"00", "11", "25", "99"}

        def _code_match(r: Dict[str, Any]) -> bool:
            grant_codes = {
                str(c).zfill(2) for c in (r.get("eligible_applicants") or []) if str(c).strip()
            }
            if not grant_codes:
                # Grants with no structured codes fall through to text filter — keep.
                return True
            if grant_codes & CATCHALL:
                return True
            return bool(grant_codes & wanted)

        rows = [r for r in rows if _code_match(r)]
        tel.record(
            f"strict applicant codes {','.join(sorted(wanted))}",
            len(rows),
        )

    # Stage 6: cap at final limit
    rows = rows[:limit]
    tel.record(f"final limit ({limit})", len(rows))

    return OpportunityFilterResult(rows=rows, telemetry=tel)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _safe_head_count(q) -> int:
    """Try to get an exact count for an in-progress query. Returns 0 on failure.

    PostgREST allows a `head=True, count="exact"` request that returns headers
    only — cheap, no data transfer. We re-execute the query in count mode and
    fall back gracefully if it can't be expressed (e.g. after an `.or_(...)`).
    """
    try:
        # PostgREST count="exact" works on most queries; failure modes are rare
        # but include malformed `or` filters. Don't crash the discovery run.
        result = q.execute()
        return result.count if result.count is not None else len(result.data or [])
    except Exception:
        return 0


def emit_telemetry(progress_cb: Callable[[str, Dict[str, Any]], None], source: str, tel: FilterTelemetry) -> None:
    """Emit a pre-filter funnel to the orchestrator's progress callback."""
    try:
        progress_cb(source, {"current_action": _format_funnel(tel)})
    except Exception:
        pass


def _format_funnel(tel: FilterTelemetry) -> str:
    """Compact one-line representation for the progress UI."""
    if not tel.stages:
        return "no candidates"
    arrow = " → "
    return arrow.join(f"{s['count']:,} ({s['label']})" for s in tel.stages)
