"""Pre-scrape match scoring and candidate prioritisation (Phase 5).

match_score() is a pure, unit-testable function that blends vector
cosine similarity with three structured boosts:

  base   = candidate.similarity          (0–1, from pgvector)
  +NTEE  = +0.15 if funder NTEE prefix matches any of profile.ntee_codes
  +KW    = +0.05 per cause keyword found in grantee_purposes   (cap 0.20)
  +ASSET = +0.05 if asset_amount implies the funder is in-range

Final score is clamped to [0, 1].

rank_candidates() mutates each Candidate's match_score field in-place
and returns the list sorted descending — the order in which URLs are
handed to the scrape job.

scored_urls() extracts the top-K scrape-ready URLs from a ranked list.
"""

from __future__ import annotations

import re
from typing import List, Optional

from utils.discovery.targeting import Candidate, TargetingProfile

# ── Boost constants (tune empirically in Phase 5 follow-up) ──────────────────

NTEE_BOOST = 0.15
KEYWORD_BOOST_PER = 0.05
KEYWORD_BOOST_MAX = 0.20
ASSET_BOOST = 0.05

# Funders whose assets fall below this are unlikely to make meaningful grants.
_ASSET_FLOOR = 500_000          # $500K
# Above this the funder is likely a mega-foundation with restricted processes.
_ASSET_CEILING = 2_000_000_000  # $2B


def _ntee_matches(ntee_code: Optional[str], profile_codes: List[str]) -> bool:
    """True if ntee_code starts with any prefix in profile_codes."""
    if not ntee_code or not profile_codes:
        return False
    code = ntee_code.upper()
    return any(code.startswith(p.upper()) for p in profile_codes)


def _keyword_hits(grantee_purposes: Optional[str], cause_keywords: List[str]) -> int:
    """Count how many cause keywords appear in the grantee_purposes text."""
    if not grantee_purposes or not cause_keywords:
        return 0
    text = grantee_purposes.lower()
    count = 0
    for kw in cause_keywords:
        # Match the keyword as a word boundary so "youth" doesn't match "youthful"
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, text):
            count += 1
    return count


def _asset_in_range(
    asset_amount: Optional[int],
    min_grant_size: Optional[int],
    max_grant_size: Optional[int],
) -> bool:
    """True if the funder's asset_amount is plausibly in-range for the org.

    Foundations typically grant ~1–5 % of assets per year. We use 2% as a
    rough proxy: asset * 0.02 must cover at least min_grant_size. We also
    skip funders well below the floor or above the ceiling.
    """
    if asset_amount is None:
        return False
    if asset_amount < _ASSET_FLOOR or asset_amount > _ASSET_CEILING:
        return False
    if min_grant_size:
        implied_grant = asset_amount * 0.02
        if implied_grant < min_grant_size:
            return False
    return True


def match_score(candidate: Candidate, profile: TargetingProfile) -> float:
    """Compute a match score in [0, 1] for a single candidate.

    Pure function — reads candidate and profile fields only, no I/O.
    """
    score = candidate.similarity  # base from vector search

    if candidate.kind == "funder":
        if _ntee_matches(candidate.ntee_code, profile.ntee_codes):
            score += NTEE_BOOST

        hits = _keyword_hits(candidate.grantee_purposes, profile.cause_keywords)
        score += min(hits * KEYWORD_BOOST_PER, KEYWORD_BOOST_MAX)

        if _asset_in_range(candidate.asset_amount, profile.min_grant_size, profile.max_grant_size):
            score += ASSET_BOOST

    return min(score, 1.0)


def rank_candidates(
    candidates: List[Candidate],
    profile: TargetingProfile,
) -> List[Candidate]:
    """Score each candidate, set its match_score field, return sorted descending.

    Mutates the match_score field in place so callers can inspect it later.
    """
    for c in candidates:
        c.match_score = match_score(c, profile)
    return sorted(candidates, key=lambda c: c.match_score, reverse=True)


def scored_urls(
    candidates: List[Candidate],
    profile: TargetingProfile,
    limit: int,
) -> List[str]:
    """Rank candidates and return the top-limit scrape-ready URLs.

    Candidates without a URL are dropped. The list order is the priority
    order for the scrape job: index 0 is scraped first.
    """
    ranked = rank_candidates(candidates, profile)
    urls: List[str] = []
    for c in ranked:
        if c.url and len(urls) < limit:
            urls.append(c.url)
    return urls
