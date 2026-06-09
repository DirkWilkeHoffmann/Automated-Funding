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
