"""Targeted discovery path — Phase 7.

run_targeted_path() is called by orchestrator.run_discovery() when
config["targeting_enabled"] is True. It replaces the source-rotation loop
with a demand-driven pipeline:

  Phase 4: vector search (retrieve_candidates)
  Phase 5: match scoring (rank_candidates)
  Phase 6a: LLM rerank (rerank_and_explain — top slice only)
  Phase 6b: relevance gate → 3-lane routing (SCRAPE / PENDING / DROP)

Returns (scrape_urls, pending_count, drop_count, cursor_state_patch, scrape_job_id)
so the orchestrator can merge cursor state and record run metrics using the
same completion path as the legacy source-rotation run.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from utils.db.client import get_supabase
from utils.db.pending_urls_store import upsert_targeting_pending
from utils.discovery.relevance_gate import Lane, gate
from utils.discovery.rerank import rerank_and_explain
from utils.discovery.scoring import rank_candidates
from utils.discovery.targeting import load_cursor, load_targeting_profile, retrieve_candidates
from utils.models import DiscoveryProgress

logger = logging.getLogger(__name__)

_RERANK_TOP_K = 30  # LLM-rerank only the highest-scored slice to cap cost


def _cursor_state(profile, cursor) -> Dict[str, Any]:
    """Build the discovery_state patch for the targeting cursor.

    Shape mirrors config_store.save_cursor / load_cursor so the orchestrator's
    top-level {**discovery_state, **new_state} merge writes it correctly.
    Note: the merge replaces the whole "targeting" key — safe for single-org;
    multi-tenant will need a deep-merge when org_id scoping lands.
    """
    return {
        "targeting": {
            profile.org_id: {
                "funder_offset": cursor.funder_offset,
                "opp_offset": cursor.opp_offset,
                "geo_broaden_level": cursor.geo_broaden_level,
            }
        }
    }


def run_targeted_path(
    config: Dict[str, Any],
    progress: DiscoveryProgress,
    throttle: Any,
    discovery_state: Dict[str, Any],
) -> Tuple[List[str], int, int, Dict[str, Any], Optional[str]]:
    """Execute one targeting-engine discovery cycle.

    Returns
    -------
    scrape_urls : ordered list of grant-page URLs for the scrape job
    pending_count : candidates sent to pending_urls review queue
    drop_count : candidates dropped at the gate
    cursor_patch : dict to merge into discovery_state before persisting
    scrape_job_id : ID of the spawned scrape job, or None
    """
    sb = get_supabase()
    progress.ensure_source("targeting_engine")
    progress.update_source("targeting_engine", status="running", current_action="loading profile")
    throttle.maybe_write(progress)

    profile = load_targeting_profile()
    cursor = load_cursor(profile)
    limit = int(config.get("max_per_source") or 100)

    if not profile.client_embedding:
        logger.info("Targeting path: no client_embedding — run targeting setup first")
        progress.update_source(
            "targeting_engine", status="completed",
            current_action="skipped: no client embedding configured",
        )
        throttle.maybe_write(progress, force=True)
        return [], 0, 0, {}, None

    # Phase 4 — vector search ─────────────────────────────────────────────────
    progress.update_source("targeting_engine", current_action="vector search")
    throttle.maybe_write(progress)

    candidate_set, new_cursor = retrieve_candidates(profile, cursor, limit=limit, sb=sb)
    all_candidates = candidate_set.all_sorted()
    progress.urls_discovered = len(all_candidates)
    progress.update_source(
        "targeting_engine", urls_found=len(all_candidates),
        current_action=f"retrieved {len(all_candidates)} candidates",
    )
    throttle.maybe_write(progress)

    if not all_candidates:
        logger.info("Targeting path: no candidates retrieved — pool may be empty")
        progress.update_source(
            "targeting_engine", status="completed", current_action="no candidates in pool",
        )
        throttle.maybe_write(progress, force=True)
        return [], 0, 0, _cursor_state(profile, new_cursor), None

    # Phase 5 — match scoring ─────────────────────────────────────────────────
    ranked = rank_candidates(all_candidates, profile)

    # Phase 6a — LLM rerank (top slice only) ──────────────────────────────────
    top_slice = ranked[:_RERANK_TOP_K]
    progress.update_source(
        "targeting_engine", current_action=f"reranking top {len(top_slice)} candidates",
    )
    throttle.maybe_write(progress)
    rerank_and_explain(profile, top_slice)

    # Phase 6b — relevance gate → 3-lane routing ──────────────────────────────
    scrape_candidates: List = []
    pending_candidates: List = []
    drop_count = 0

    progress.update_source("targeting_engine", current_action="relevance gate")
    for c in ranked:
        lane = gate(c, profile)
        if lane == Lane.SCRAPE:
            scrape_candidates.append(c)
        elif lane == Lane.PENDING:
            pending_candidates.append(c)
        else:
            drop_count += 1
            logger.debug(
                "gate DROP %s (tier=%s score=%.3f state=%s)",
                c.name, c.predicted_tier, c.match_score, c.state,
            )

    logger.info(
        "Targeting gate: %d SCRAPE %d PENDING %d DROP (of %d candidates)",
        len(scrape_candidates), len(pending_candidates), drop_count, len(all_candidates),
    )

    # Write PENDING candidates to the review queue ────────────────────────────
    if pending_candidates:
        upsert_targeting_pending(pending_candidates)

    # Spawn scrape job ────────────────────────────────────────────────────────
    scrape_urls = [c.url for c in scrape_candidates if c.url]
    scrape_job_id: Optional[str] = None

    if scrape_urls:
        from api.jobs import job_store
        url_metadata = {
            c.url: {
                "discovery_source": "targeting_engine",
                **({"fund_name": c.name} if c.name else {}),
            }
            for c in scrape_candidates
            if c.url
        }
        job = job_store.create(scrape_urls, url_metadata=url_metadata)
        scrape_job_id = job.id
        logger.info(
            "Targeting: spawned scrape job %s for %d URLs", scrape_job_id, len(scrape_urls),
        )

    progress.urls_new = len(scrape_urls)
    progress.update_source(
        "targeting_engine", status="completed", urls_new=len(scrape_urls),
        current_action=(
            f"{len(scrape_urls)} SCRAPE  "
            f"{len(pending_candidates)} PENDING  "
            f"{drop_count} DROP"
        ),
    )
    throttle.maybe_write(progress, force=True)

    return (
        scrape_urls,
        len(pending_candidates),
        drop_count,
        _cursor_state(profile, new_cursor),
        scrape_job_id,
    )
