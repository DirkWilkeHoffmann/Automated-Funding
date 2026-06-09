"""Client targeting profile for the match-quality engine.

Phase 3: derive AI-suggested targeting signals from an org mission, cache a
client embedding vector, and expose TargetingProfile — the single dataclass
consumed by Phase 4+ retrieve_candidates / rerank / gate.

All public functions take a TargetingProfile as a parameter (no hardcoded
single-org reads inside the new modules) — this is the multi-tenant seam.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.discovery.prefilter import OrgProfile
from utils.llm_utils import get_client

logger = logging.getLogger(__name__)

_DERIVE_SYSTEM = """You are a grant-targeting assistant for US nonprofits.
Given a mission statement, return ONLY a JSON object with these keys:

{
  "ntee_prefixes": ["P", "O"],
  "cfda_categories": ["ISS", "ELT"],
  "cause_keywords": ["workforce development", "youth employment"],
  "applicant_codes": ["12"],
  "notes": "brief rationale (1-2 sentences)"
}

NTEE single-letter prefixes: A=Arts, B=Education, C=Environment, D=Animal,
E=Health Care, F=Mental Health, G=Disease/Disorders, H=Medical Research,
I=Crime/Legal, J=Employment, K=Food/Agriculture, L=Housing, M=Public Safety,
N=Recreation/Sports, O=Youth Development, P=Human Services,
Q=International, R=Civil Rights, S=Community Improvement,
T=Philanthropy/Foundations, U=Science/Technology, V=Social Science,
W=Public/Societal Benefit, X=Religion, Y=Mutual Benefit, Z=Unknown.

Valid CFDA categories: ACA, AG, AR, BC, CD, CP, DPR, ED, ELT, EN, ENV, FN,
HL, HO, HU, IIJ, IS, ISS, LJL, NR, O, RA, RD, ST, T.

Grants.gov applicant codes: 01=county, 02=city/township, 04=special-district,
05=school-district, 06=public-higher-ed, 07=tribal-gov, 08=housing-authority,
10=tribal-org, 12=501(c)(3) nonprofit, 13=nonprofit-no-501c3,
20=private-higher-ed, 21=individuals, 22=for-profit, 23=small-business.

Return 2–5 NTEE prefixes, 2–5 CFDA categories, 5–10 cause keywords, and
whichever applicant codes apply. If unsure, omit rather than guess."""


@dataclass
class TargetingProfile:
    """OrgProfile + targeting-engine extras. The multi-tenant seam for Phases 4+.

    Every Phase 4+ function takes a TargetingProfile parameter — no org reads
    inside those modules. Pass org_id='default' until multi-tenancy lands.
    """

    org_id: str = "default"
    # org identity fields (denormalised from OrgProfile)
    mission: Optional[str] = None
    services: List[str] = field(default_factory=list)
    ntee_codes: List[str] = field(default_factory=list)
    service_states: List[str] = field(default_factory=list)
    cfda_categories: List[str] = field(default_factory=list)
    eligible_applicant_codes: List[str] = field(default_factory=list)
    applicant_types: List[str] = field(default_factory=list)
    accepts_unsolicited: bool = True
    can_cost_share: bool = True
    min_grant_size: Optional[int] = None
    max_grant_size: Optional[int] = None
    state: Optional[str] = None
    # targeting-engine extras
    cause_keywords: List[str] = field(default_factory=list)
    targeting_confirmed: bool = False
    client_embedding: Optional[List[float]] = None

    # ── constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_org_profile(
        cls,
        org: OrgProfile,
        *,
        org_id: str = "default",
        cause_keywords: Optional[List[str]] = None,
        targeting_confirmed: bool = False,
        client_embedding: Optional[List[float]] = None,
    ) -> "TargetingProfile":
        return cls(
            org_id=org_id,
            mission=org.mission,
            services=list(org.services),
            ntee_codes=list(org.ntee_codes),
            service_states=list(org.service_states),
            cfda_categories=list(org.cfda_categories),
            eligible_applicant_codes=list(org.eligible_applicant_codes),
            applicant_types=list(org.applicant_types),
            accepts_unsolicited=org.accepts_unsolicited,
            can_cost_share=org.can_cost_share,
            min_grant_size=org.min_grant_size,
            max_grant_size=org.max_grant_size,
            state=org.state,
            cause_keywords=list(cause_keywords or []),
            targeting_confirmed=targeting_confirmed,
            client_embedding=client_embedding,
        )

    @classmethod
    def from_org_row(cls, row: Optional[Dict[str, Any]]) -> "TargetingProfile":
        """Build from a raw organizations DB row (includes Phase 11 columns)."""
        org = OrgProfile.from_row(row)
        if not row:
            return cls.from_org_profile(org)
        return cls.from_org_profile(
            org,
            org_id=str(row.get("id") or "default"),
            cause_keywords=list(row.get("cause_keywords") or []),
            targeting_confirmed=bool(row.get("targeting_confirmed", False)),
            client_embedding=row.get("client_embedding"),
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def effective_states(self) -> List[str]:
        if self.service_states:
            return self.service_states
        if self.state:
            return [self.state.upper()]
        return []

    def embedding_input_text(self) -> str:
        """Concatenate signals for the client embedding."""
        parts: List[str] = []
        if self.mission:
            parts.append(self.mission.strip())
        if self.cause_keywords:
            parts.append(" ".join(self.cause_keywords))
        if self.services:
            parts.append(" ".join(self.services[:10]))
        return " | ".join(parts).strip()


# ── Core functions ────────────────────────────────────────────────────────────


def derive_targeting(
    mission: str,
    *,
    website: Optional[str] = None,
    ein: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask GPT-4o to suggest ntee_prefixes, cfda_categories, cause_keywords,
    applicant_codes from a mission statement.

    Does not write to DB — caller persists after operator confirmation.
    Returns a dict guaranteed to have all five keys.
    """
    _empty: Dict[str, Any] = {
        "ntee_prefixes": [],
        "cfda_categories": [],
        "cause_keywords": [],
        "applicant_codes": [],
        "notes": "",
    }

    client = get_client()
    if client is None:
        return {**_empty, "notes": "No OpenAI API key configured."}

    user_msg = f"Mission: {mission.strip()}"
    if website:
        user_msg += f"\nWebsite: {website}"
    if ein:
        user_msg += f"\nEIN: {ein}"

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _DERIVE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return {
            "ntee_prefixes": [str(x) for x in (data.get("ntee_prefixes") or [])],
            "cfda_categories": [str(x) for x in (data.get("cfda_categories") or [])],
            "cause_keywords": [str(x) for x in (data.get("cause_keywords") or [])],
            "applicant_codes": [
                str(x).zfill(2) for x in (data.get("applicant_codes") or [])
            ],
            "notes": str(data.get("notes") or ""),
        }
    except json.JSONDecodeError as exc:
        logger.warning("derive_targeting: JSON parse failed: %s", exc)
        return {**_empty, "notes": "Could not parse LLM response."}
    except Exception as exc:
        logger.warning("derive_targeting: LLM call failed: %s", exc)
        return {**_empty, "notes": f"LLM call failed: {exc}"}


def build_client_embedding(profile: TargetingProfile) -> Optional[List[float]]:
    """Embed mission + cause_keywords + services for a client profile."""
    from utils.discovery.embeddings import embed_text

    text = profile.embedding_input_text()
    if not text:
        return None
    return embed_text(text)


# ── Phase 4: retrieval dataclasses + helpers ──────────────────────────────────

# One-hop US state neighbours for geo broadening (level 1).
_ADJACENT: Dict[str, List[str]] = {
    "AL": ["FL","GA","MS","TN"],        "AK": [],
    "AZ": ["CA","CO","NM","NV","UT"],   "AR": ["LA","MO","MS","OK","TN","TX"],
    "CA": ["AZ","NV","OR"],              "CO": ["AZ","KS","NE","NM","OK","UT","WY"],
    "CT": ["MA","NY","RI"],              "DE": ["MD","NJ","PA"],
    "FL": ["AL","GA"],                   "GA": ["AL","FL","NC","SC","TN"],
    "HI": [],                            "ID": ["MT","NV","OR","UT","WA","WY"],
    "IL": ["IN","IA","KY","MO","WI"],   "IN": ["IL","KY","MI","OH"],
    "IA": ["IL","MN","MO","NE","SD","WI"], "KS": ["CO","MO","NE","OK"],
    "KY": ["IL","IN","MO","OH","TN","VA","WV"], "LA": ["AR","MS","TX"],
    "ME": ["NH"],                        "MD": ["DE","PA","VA","WV"],
    "MA": ["CT","NH","NY","RI","VT"],   "MI": ["IN","OH","WI"],
    "MN": ["IA","ND","SD","WI"],        "MS": ["AL","AR","LA","TN"],
    "MO": ["AR","IL","IA","KS","KY","NE","OK","TN"], "MT": ["ID","ND","SD","WY"],
    "NE": ["CO","IA","KS","MO","SD","WY"], "NV": ["AZ","CA","ID","OR","UT"],
    "NH": ["MA","ME","VT"],              "NJ": ["DE","NY","PA"],
    "NM": ["AZ","CO","OK","TX","UT"],   "NY": ["CT","MA","NJ","PA","VT"],
    "NC": ["GA","SC","TN","VA"],        "ND": ["MN","MT","SD"],
    "OH": ["IN","KY","MI","PA","WV"],   "OK": ["AR","CO","KS","MO","NM","TX"],
    "OR": ["CA","ID","NV","WA"],        "PA": ["DE","MD","NJ","NY","OH","WV"],
    "RI": ["CT","MA"],                   "SC": ["GA","NC"],
    "SD": ["IA","MN","MT","ND","NE","WY"], "TN": ["AL","AR","GA","KY","MO","MS","NC","VA"],
    "TX": ["AR","LA","NM","OK"],        "UT": ["AZ","CO","ID","NV","NM","WY"],
    "VT": ["MA","NH","NY"],              "VA": ["KY","MD","NC","TN","WV"],
    "WA": ["ID","OR"],                   "WV": ["KY","MD","OH","PA","VA"],
    "WI": ["IL","IA","MI","MN"],        "WY": ["CO","ID","MT","NE","SD","UT"],
}


@dataclass
class TargetingCursor:
    """Rotation state per org, persisted in discovery_state JSONB."""
    funder_offset: int = 0
    opp_offset: int = 0
    geo_broaden_level: int = 0


@dataclass
class Candidate:
    """A single ranked candidate from the vector search."""
    kind: str                               # "funder" | "opportunity"
    id: str                                 # ein or opportunity_id
    name: str
    url: Optional[str]
    state: Optional[str]
    similarity: float
    ntee_code: Optional[str] = None
    asset_amount: Optional[int] = None
    program_areas: Optional[List[str]] = None
    grantee_purposes: Optional[str] = None
    close_date: Optional[str] = None
    cfda_number: Optional[str] = None
    category: Optional[str] = None
    match_score: float = 0.0  # set by scoring.rank_candidates (Phase 5)


@dataclass
class CandidateSet:
    funders: List[Candidate] = field(default_factory=list)
    opportunities: List[Candidate] = field(default_factory=list)

    def all_sorted(self) -> List[Candidate]:
        return sorted(
            self.funders + self.opportunities,
            key=lambda c: c.similarity,
            reverse=True,
        )


def _states_for_level(base: List[str], level: int) -> Optional[List[str]]:
    """Return geo filter for the given broadening level.

    0 = exact base states; 1 = base + one-hop neighbours; 2+ = no filter.
    """
    if not base:
        return None
    if level <= 0:
        return list(base)
    if level == 1:
        expanded = set(base)
        for s in base:
            expanded.update(_ADJACENT.get(s, []))
        return sorted(expanded)
    return None  # level 2+ = national


def load_cursor(profile: TargetingProfile) -> TargetingCursor:
    """Read this org's rotation cursor from discovery_state JSONB."""
    try:
        from utils.discovery.config_store import load_discovery_state
        slot = (load_discovery_state().get("targeting") or {}).get(profile.org_id) or {}
        return TargetingCursor(
            funder_offset=int(slot.get("funder_offset", 0)),
            opp_offset=int(slot.get("opp_offset", 0)),
            geo_broaden_level=int(slot.get("geo_broaden_level", 0)),
        )
    except Exception as exc:
        logger.debug("load_cursor failed: %s", exc)
        return TargetingCursor()


def save_cursor(profile: TargetingProfile, cursor: TargetingCursor) -> None:
    """Persist this org's rotation cursor into discovery_state JSONB."""
    try:
        from utils.discovery.config_store import load_discovery_state, save_discovery_state
        state = load_discovery_state()
        state.setdefault("targeting", {})[profile.org_id] = {
            "funder_offset": cursor.funder_offset,
            "opp_offset": cursor.opp_offset,
            "geo_broaden_level": cursor.geo_broaden_level,
        }
        save_discovery_state(state)
    except Exception as exc:
        logger.warning("save_cursor failed: %s", exc)


def retrieve_candidates(
    profile: TargetingProfile,
    cursor: TargetingCursor,
    limit: int = 50,
    *,
    sb=None,
) -> "tuple[CandidateSet, TargetingCursor]":
    """Vector-search funders + opportunities ranked by mission similarity.

    Implements rotation (funder_offset / opp_offset) so consecutive runs
    surface different candidates from the same pool.  Graceful broadening:
    if the tight geo filter yields fewer than limit//2 funders, the geo
    filter is widened (add adjacent states → no filter) and geo_broaden_level
    is persisted so the next run starts at the broader scope.

    Returns (CandidateSet, updated_cursor). Caller must call save_cursor()
    after the run if it wants rotation to persist.
    """
    if not profile.client_embedding:
        logger.debug("retrieve_candidates: no client_embedding — skipping vector search")
        return CandidateSet(), TargetingCursor(
            funder_offset=cursor.funder_offset,
            opp_offset=cursor.opp_offset,
            geo_broaden_level=cursor.geo_broaden_level,
        )

    if sb is None:
        from utils.db.client import get_supabase
        sb = get_supabase()

    vec = profile.client_embedding
    base_states = profile.effective_states()
    funder_limit = max(limit * 3 // 4, 1)
    opp_limit = max(limit - funder_limit, 1)

    # ── Funder search with broadening ─────────────────────────────────────
    funder_rows: List[Dict[str, Any]] = []
    final_level = cursor.geo_broaden_level

    for level in range(cursor.geo_broaden_level, 3):
        states = _states_for_level(base_states, level)
        params: Dict[str, Any] = {
            "query_embedding": vec,
            "match_count": funder_limit,
            "funder_offset": cursor.funder_offset,
            "min_asset_code": 1,
        }
        if states:
            params["filter_states"] = states
        try:
            funder_rows = sb.rpc("match_funders", params).execute().data or []
        except Exception as exc:
            logger.warning("match_funders RPC failed (level=%d): %s", level, exc)
            funder_rows = []
        final_level = level
        if len(funder_rows) >= limit // 2:
            break

    # ── Opportunity search ─────────────────────────────────────────────────
    opp_rows: List[Dict[str, Any]] = []
    try:
        opp_rows = (
            sb.rpc("match_opportunities", {
                "query_embedding": vec,
                "match_count": opp_limit,
                "opp_offset": cursor.opp_offset,
            }).execute().data or []
        )
    except Exception as exc:
        logger.warning("match_opportunities RPC failed: %s", exc)

    # ── Build candidate objects ────────────────────────────────────────────
    funders = [
        Candidate(
            kind="funder",
            id=str(r.get("ein") or ""),
            name=str(r.get("name") or ""),
            url=r.get("website"),
            state=r.get("state"),
            similarity=float(r.get("similarity") or 0.0),
            ntee_code=r.get("ntee_code"),
            asset_amount=r.get("asset_amount"),
            program_areas=r.get("program_areas"),
            grantee_purposes=r.get("grantee_purposes"),
        )
        for r in funder_rows
    ]
    opportunities = [
        Candidate(
            kind="opportunity",
            id=str(r.get("opportunity_id") or ""),
            name=str(r.get("title") or ""),
            url=r.get("url"),
            state=None,
            similarity=float(r.get("similarity") or 0.0),
            close_date=r.get("close_date"),
            cfda_number=r.get("cfda_number"),
            category=r.get("category"),
        )
        for r in opp_rows
    ]

    # ── Advance rotation cursors (reset to 0 when pool exhausted) ─────────
    new_cursor = TargetingCursor(
        funder_offset=cursor.funder_offset + len(funder_rows) if funder_rows else 0,
        opp_offset=cursor.opp_offset + len(opp_rows) if opp_rows else 0,
        geo_broaden_level=final_level,
    )
    return CandidateSet(funders=funders, opportunities=opportunities), new_cursor


def load_targeting_profile() -> TargetingProfile:
    """Load targeting profile from the single org row. Falls back to empty profile."""
    try:
        from utils.db.client import get_supabase
        rows = (
            get_supabase().table("organizations").select("*").limit(1).execute().data
            or []
        )
        return TargetingProfile.from_org_row(rows[0] if rows else None)
    except Exception as exc:
        logger.warning("Could not load targeting profile: %s", exc)
        return TargetingProfile()
