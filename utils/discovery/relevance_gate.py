"""Relevance gate — Phase 6.

gate(candidate, profile) → Lane routes each candidate into one of three lanes:

  SCRAPE  — strong predicted match + verified grant pathway
  PENDING — verified pathway but ambiguous/borderline (pending_urls review queue)
  DROP    — hard mismatch, no pathway, or very low confidence

Stages (cheap-first order):
  1. Hard rules (free): state mismatch, deadline passed, invitation-only.
  2. Pathway check: opportunity candidates have a URL by definition; funder
     candidates need a sitemap or crawlable grants page.
  3. Tier routing using predicted_tier set by rerank_and_explain.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from enum import Enum
from typing import Callable, List, Optional

from utils.discovery.targeting import Candidate, TargetingProfile

logger = logging.getLogger(__name__)


class Lane(str, Enum):
    SCRAPE = "scrape"
    PENDING = "pending"
    DROP = "drop"


_SCRAPE_TIERS = {"highly_eligible", "eligible"}
_PENDING_TIERS = {"borderline"}


def _state_allowed(candidate: Candidate, profile: TargetingProfile) -> bool:
    if not profile.service_states:
        return True  # no geo filter — national scope
    if not candidate.state:
        return True  # unknown state — don't drop speculatively
    return candidate.state.upper() in {s.upper() for s in profile.service_states}


def _deadline_passed(candidate: Candidate) -> bool:
    if candidate.kind != "opportunity" or not candidate.close_date:
        return False
    try:
        close = datetime.strptime(candidate.close_date[:10], "%Y-%m-%d").date()
        return close < date.today()
    except ValueError:
        return False


def _is_invitation_only(candidate: Candidate) -> bool:
    if candidate.kind != "funder":
        return False
    from utils.discovery.foundation_crawler import is_invitation_only
    return is_invitation_only(candidate.grantee_purposes)


def _has_grant_pathway(
    candidate: Candidate,
    *,
    sitemap_fn: Optional[Callable] = None,
    crawler_fn: Optional[Callable] = None,
) -> bool:
    """True when we can locate a grant-application URL for the candidate.

    Opportunities already carry their URL — no additional check needed.
    Funders need sitemap lookup then homepage-crawl fallback. The candidate's
    url field is upgraded to the discovered grants-page URL when found.
    """
    if candidate.kind == "opportunity":
        return bool(candidate.url)

    if not candidate.url:
        return False

    if sitemap_fn is None:
        from utils.discovery.sitemap_map import find_funding_urls as sitemap_fn
    urls = sitemap_fn(candidate.url)
    if urls:
        candidate.url = urls[0]
        return True

    if crawler_fn is None:
        from utils.discovery.foundation_crawler import find_grants_page as crawler_fn
    result = crawler_fn(candidate.url)
    if result:
        grants_url, _reason = result
        candidate.url = grants_url
        return True

    return False


def gate(
    candidate: Candidate,
    profile: TargetingProfile,
    *,
    sitemap_fn: Optional[Callable] = None,
    crawler_fn: Optional[Callable] = None,
) -> Lane:
    """Route a single candidate into SCRAPE, PENDING, or DROP.

    sitemap_fn / crawler_fn are injection points for unit tests; leave
    as None in production (defaults to the real implementations).
    """
    # Stage 1 — hard rules (free, no I/O)
    if not _state_allowed(candidate, profile):
        logger.debug("gate DROP %s: state %s not in profile", candidate.name, candidate.state)
        return Lane.DROP

    if _deadline_passed(candidate):
        logger.debug("gate DROP %s: deadline passed (%s)", candidate.name, candidate.close_date)
        return Lane.DROP

    if _is_invitation_only(candidate):
        logger.debug("gate DROP %s: invitation-only", candidate.name)
        return Lane.DROP

    # Stage 2 — grant pathway verification (I/O)
    if not _has_grant_pathway(candidate, sitemap_fn=sitemap_fn, crawler_fn=crawler_fn):
        logger.debug("gate DROP %s: no grant pathway found", candidate.name)
        return Lane.DROP

    # Stage 3 — tier routing (set by rerank_and_explain)
    tier = candidate.predicted_tier or "borderline"
    if tier in _SCRAPE_TIERS:
        return Lane.SCRAPE
    if tier in _PENDING_TIERS:
        return Lane.PENDING
    return Lane.DROP
