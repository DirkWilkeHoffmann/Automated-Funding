"""LLM reranking pass — Phase 6.

rerank_and_explain(profile, candidates) runs a batched cheap-LLM call per
candidate, confirming funder-mission fit and flagging past-grantee overlap
(the "Highly Eligible" signal). Mutates each candidate's match_reason,
past_grantee_overlap, and predicted_tier fields in-place.

Opportunities (federal grants) skip the LLM and receive a tier derived
from their match_score — they carry no program_areas / grantee signal.
"""

from __future__ import annotations

import json
import logging
from typing import List

from utils.discovery.targeting import Candidate, TargetingProfile
from utils.llm_utils import _MODEL_FAST, get_client

logger = logging.getLogger(__name__)

_BATCH_SIZE = 5  # candidates per LLM call — balances latency vs cost
_TIERS = {"highly_eligible", "eligible", "borderline", "not_eligible"}

_RERANK_SYSTEM = (
    "You are a grant-targeting assistant for US nonprofits. "
    "For each funder candidate, assess whether their historical giving aligns "
    "with the client's mission. Reply with strict JSON only."
)


def _build_batch_prompt(profile: TargetingProfile, batch: List[Candidate]) -> str:
    mission = (profile.mission or "").strip() or "(not provided)"
    keywords = ", ".join(profile.cause_keywords) if profile.cause_keywords else "(none)"
    lines = [
        f"CLIENT MISSION: {mission}",
        f"CAUSE KEYWORDS: {keywords}",
        "",
        "FUNDER CANDIDATES (assess each for mission alignment):",
    ]
    for i, c in enumerate(batch):
        areas = ", ".join(c.program_areas or []) or "(unknown)"
        purposes = (c.grantee_purposes or "")[:300] or "(unknown)"
        lines.append(
            f"{i+1}. name={c.name!r}  ntee={c.ntee_code or 'n/a'}"
            f"  program_areas={areas}  grantee_purposes={purposes!r}"
        )
    lines += [
        "",
        "Return JSON with EXACTLY this shape (one item per candidate, same order):",
        '{"results": [',
        '  {"match_confirmed": true,',
        '   "match_reason": "1-sentence reason",',
        '   "past_grantee_overlap": false,',
        '   "predicted_tier": "highly_eligible|eligible|borderline|not_eligible"},',
        "  ...",
        "]}",
        "",
        "Rules:",
        "- past_grantee_overlap=true only when the funder's known grantees/purposes clearly describe "
        "organisations similar to the client (strong evidence, not inference).",
        "- predicted_tier: highly_eligible when overlap=true; eligible when confirmed, no overlap; "
        "borderline when plausible but unclear; not_eligible otherwise.",
    ]
    return "\n".join(lines)


def _apply_batch_results(batch: List[Candidate], raw_results: list) -> None:
    for i, candidate in enumerate(batch):
        if i >= len(raw_results):
            break
        item = raw_results[i]
        if not isinstance(item, dict):
            continue
        candidate.match_reason = str(item.get("match_reason") or "")[:500]
        candidate.past_grantee_overlap = bool(item.get("past_grantee_overlap"))
        tier = str(item.get("predicted_tier") or "borderline")
        candidate.predicted_tier = tier if tier in _TIERS else "borderline"


def _default_opp_tier(candidate: Candidate) -> str:
    if candidate.match_score >= 0.75:
        return "eligible"
    if candidate.match_score >= 0.55:
        return "borderline"
    return "not_eligible"


def rerank_and_explain(
    profile: TargetingProfile,
    candidates: List[Candidate],
) -> List[Candidate]:
    """Mutate match_reason / past_grantee_overlap / predicted_tier; return candidates.

    Funder candidates get LLM assessment. Opportunity candidates get a
    score-derived tier (no program_areas / grantee signal to assess).
    If the OpenAI client is unavailable, funders default to 'borderline'.
    """
    funders = [c for c in candidates if c.kind == "funder"]
    opps = [c for c in candidates if c.kind != "funder"]

    for c in opps:
        if not c.predicted_tier:
            c.predicted_tier = _default_opp_tier(c)

    client = get_client()
    if not funders or client is None:
        for c in funders:
            if not c.predicted_tier:
                c.predicted_tier = "borderline"
        return candidates

    for start in range(0, len(funders), _BATCH_SIZE):
        batch = funders[start : start + _BATCH_SIZE]
        prompt = _build_batch_prompt(profile, batch)
        try:
            resp = client.chat.completions.create(
                model=_MODEL_FAST,
                messages=[
                    {"role": "system", "content": _RERANK_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
                timeout=30,
            )
            data = json.loads(resp.choices[0].message.content)
            _apply_batch_results(batch, data.get("results") or [])
        except Exception as exc:
            logger.warning("rerank_and_explain batch (start=%d) failed: %s", start, exc)
            for c in batch:
                if not c.predicted_tier:
                    c.predicted_tier = "borderline"

    return candidates
