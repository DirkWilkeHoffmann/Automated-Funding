"""Discovery orchestrator — runs source queries and feeds new URLs into the scrape pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from utils.discovery.config_store import load_config, load_discovery_state, save_discovery_state
from utils.discovery.run_store import complete_run, create_run, fail_run
from utils.db.funds_store import get_processed_urls
from utils.utils_helpers import normalize_url

logger = logging.getLogger(__name__)

_DEFAULT_KEYWORDS = "workforce development employment training nonprofit"

# Full list of US states for ProPublica rotation (5 per run → 10 runs per full cycle)
_US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]
_STATES_PER_RUN = 5


@lru_cache(maxsize=1)
def _get_org_profile() -> dict:
    """Load org profile once per process; cleared on app restart."""
    try:
        from utils.db.client import get_supabase
        rows = (
            get_supabase()
            .table("organizations")
            .select("name, state, city, mission, services")
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else {}
    except Exception as exc:
        logger.warning("Could not load org profile for discovery: %s", exc)
        return {}


def _derive_keywords(config: dict) -> str:
    """Return search keywords: config list → org mission/services → built-in default."""
    keywords_list: List[str] = config.get("keywords") or []
    if keywords_list:
        return " ".join(keywords_list)

    org = _get_org_profile()
    parts: List[str] = []
    if org.get("mission"):
        parts.extend(org["mission"].split()[:8])
    if org.get("services"):
        services = org["services"]
        if isinstance(services, list) and services:
            parts.extend(str(services[0]).split()[:4])

    STOP = {"the", "a", "an", "and", "or", "to", "for", "of", "in", "is", "we", "our"}
    seen: set = set()
    filtered: List[str] = []
    for w in parts:
        wl = w.lower().strip(".,;:()")
        if len(wl) > 3 and wl not in STOP and wl not in seen:
            seen.add(wl)
            filtered.append(wl)

    return " ".join(filtered[:6]) if filtered else _DEFAULT_KEYWORDS


def _get_api_key(service: str) -> Optional[str]:
    """Read an API key from the api_tokens table. Returns None if not found."""
    try:
        from utils.db.client import get_supabase
        rows = (
            get_supabase()
            .table("api_tokens")
            .select("key_value")
            .eq("service", service)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0]["key_value"].strip() if rows else None
    except Exception as exc:
        logger.warning("Could not read API key for %s: %s", service, exc)
        return None


def run_discovery(*, trigger: str = "scheduled", run_id: str | None = None) -> str:
    """
    Full discovery cycle:
      1. Load config and per-source state.
      2. Collect URLs from each enabled source (passing state for date filtering / rotation).
      3. Diff against already-processed URLs.
      4. If new URLs exist, kick off a batch scrape job.
      5. Save updated source state and record run completion.
    Returns the run_id (empty string if skipped).
    """
    config = load_config()
    if not config.get("enabled") and trigger != "manual":
        logger.debug("Auto-discovery is disabled; skipping scheduled run")
        return ""

    if run_id is None:
        run_id = create_run(trigger, config)
    logger.info("Discovery run %s started (trigger=%s)", run_id, trigger)

    discovery_state: Dict[str, Any] = {}
    new_state: Dict[str, Any] = {}
    all_discovered: List[str] = []
    new_urls: List[str] = []
    scrape_job_id: str | None = None
    collection_failed = False

    try:
        discovery_state = load_discovery_state()
        url_to_source: Dict[str, str] = {}
        sources = config.get("sources") or {}

        if sources.get("propublica", True):
            urls, src_state = _collect_propublica(config, discovery_state.get("propublica", {}))
            for url, source in urls:
                url_to_source[url] = source
            new_state["propublica"] = src_state

        if sources.get("grants_gov", True):
            urls, src_state = _collect_grants_gov(config, discovery_state.get("grants_gov", {}))
            for url, source in urls:
                url_to_source[url] = source
            new_state["grants_gov"] = src_state

        # SAM.gov: run if toggled on in config, or automatically when a key exists
        if sources.get("sam_gov", False) or _get_api_key("sam_gov"):
            urls, src_state = _collect_sam_gov(config, discovery_state.get("sam_gov", {}))
            for url, source in urls:
                url_to_source[url] = source
            new_state["sam_gov"] = src_state

        if sources.get("web_search", True):
            urls, src_state = _collect_web_search(config, discovery_state.get("web_search", {}))
            for url, source in urls:
                url_to_source[url] = source
            new_state["web_search"] = src_state

        if sources.get("federal_register", True):
            urls, src_state = _collect_federal_register(config, discovery_state.get("federal_register", {}))
            for url, source in urls:
                url_to_source[url] = source
            new_state["federal_register"] = src_state

        all_discovered = list(url_to_source.keys())
        logger.info("Discovery found %d total URLs", len(all_discovered))

        processed = get_processed_urls(force_refresh=True)
        new_urls = [u for u in all_discovered if normalize_url(u) not in processed]
        logger.info("Discovery: %d new (unprocessed) URLs after dedup", len(new_urls))

        if new_urls:
            url_metadata = {u: {"discovery_source": url_to_source.get(u, "auto")} for u in new_urls}
            from api.jobs import job_store
            job = job_store.create(new_urls, url_metadata=url_metadata)
            scrape_job_id = job.id
            logger.info("Discovery spawned scrape job %s for %d URLs", scrape_job_id, len(new_urls))

    except Exception as exc:
        logger.error("Discovery run %s failed: %s", run_id, exc, exc_info=True)
        fail_run(run_id, str(exc))
        collection_failed = True

    # Always attempt to save per-source state — even on partial collection failure,
    # saving whatever progress was made prevents redundant re-queries next run.
    if new_state:
        try:
            save_discovery_state({**discovery_state, **new_state})
        except Exception as exc:
            logger.warning("Could not save discovery state for run %s: %s", run_id, exc)

    if not collection_failed:
        try:
            complete_run(
                run_id,
                urls_discovered=len(all_discovered),
                urls_new=len(new_urls),
                scrape_job_id=scrape_job_id,
            )
            logger.info("Discovery run %s completed", run_id)
        except Exception as exc:
            logger.warning("Could not record completion for run %s: %s", run_id, exc)

    return run_id


# ── Source collectors ─────────────────────────────────────────────────────────


def _collect_propublica(config: dict, state: dict) -> Tuple[List[tuple], Dict]:
    """
    Collect foundation URLs from ProPublica.

    If config has explicit states, searches those every run.
    Otherwise rotates through all 50 US states (5 per run) to progressively
    discover foundations across the country.
    """
    from utils.US_Grant_Discovery.prospector import foundations_to_scrape_urls, search_foundations

    max_per_source: int = int(config.get("max_per_source") or 100)
    keywords_str: Optional[str] = _derive_keywords(config) or None
    config_states = [s.upper() for s in (config.get("states") or []) if s]

    if config_states:
        states_to_query = config_states
        new_state = state  # don't advance rotation when explicit states are configured
    else:
        idx = int(state.get("next_state_idx", 0))
        states_to_query = [_US_STATES[(idx + i) % len(_US_STATES)] for i in range(_STATES_PER_RUN)]
        new_state = {"next_state_idx": (idx + _STATES_PER_RUN) % len(_US_STATES)}

    per_state_limit = max(10, max_per_source // max(len(states_to_query), 1))

    collected: List[tuple] = []
    for query_state in states_to_query:
        try:
            foundations = search_foundations(
                state=query_state,
                keywords=keywords_str,
                max_results=per_state_limit,
            )
            urls = foundations_to_scrape_urls(foundations)
            for url in urls:
                collected.append((url, "propublica"))
            logger.info("ProPublica: %d URLs for state=%s", len(urls), query_state)
        except Exception as exc:
            logger.warning("ProPublica search failed for state=%s: %s", query_state, exc)

    return collected, new_state


def _collect_grants_gov(config: dict, state: dict) -> Tuple[List[tuple], Dict]:
    """
    Collect federal grant URLs from Grants.gov.
    Uses the last-run date from state to only fetch grants posted since the previous run.
    On first run (no saved state), bootstraps with the last 30 days so we get a useful
    initial set rather than the static all-time top-100.
    """
    from datetime import timedelta

    from utils.US_Grant_Discovery.grants_gov_search import (
        federal_grants_to_scrape_urls,
        search_federal_grants,
    )

    max_per_source: int = int(config.get("max_per_source") or 100)
    keywords_str = _derive_keywords(config)
    today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()

    last_posted = state.get("last_posted_from")
    if not last_posted:
        # First run — bootstrap with last 30 days so results are fresh, not static
        last_posted = (today - timedelta(days=30)).isoformat()

    collected: List[tuple] = []
    try:
        grants = search_federal_grants(
            keywords=keywords_str,
            eligible_applicants=["12"],  # 501(c)(3) nonprofits
            posted_from=last_posted,
            max_results=max_per_source,
        )
        urls = federal_grants_to_scrape_urls(grants)
        for url in urls:
            collected.append((url, "grants_gov"))
        logger.info("Grants.gov: %d URLs (posted since %s)", len(urls), last_posted)
    except Exception as exc:
        logger.warning("Grants.gov search failed: %s", exc)

    return collected, {"last_posted_from": today_str}


def _collect_sam_gov(config: dict, state: dict) -> Tuple[List[tuple], Dict]:
    """
    Collect federal opportunity URLs from SAM.gov.
    Requires a SAM.gov API key in the api_tokens table.
    Uses the last-run date from state to only fetch recently posted notices.
    """
    from utils.discovery.sources.sam_gov import sam_gov_to_scrape_urls, search_sam_gov

    api_key = _get_api_key("sam_gov")
    if not api_key:
        logger.warning("SAM.gov: no API key found in api_tokens, skipping")
        return [], state

    last_posted = state.get("last_posted_from")
    today = datetime.now(timezone.utc).date().isoformat()
    max_per_source: int = int(config.get("max_per_source") or 100)
    keywords_str = _derive_keywords(config)

    collected: List[tuple] = []
    try:
        opportunities = search_sam_gov(
            keywords=keywords_str,
            api_key=api_key,
            posted_from=last_posted,
            max_results=max_per_source,
        )
        urls = sam_gov_to_scrape_urls(opportunities)
        for url in urls:
            collected.append((url, "sam_gov"))
        logger.info("SAM.gov: %d URLs (posted since %s)", len(urls), last_posted or "30 days default")
    except Exception as exc:
        logger.warning("SAM.gov search failed: %s", exc)

    return collected, {"last_posted_from": today}


def _collect_web_search(config: dict, state: dict) -> Tuple[List[tuple], Dict]:
    """
    Collect grant URLs via web search (Brave Search API or DuckDuckGo fallback).
    Rotates through 5 targeted queries across runs.
    """
    from utils.discovery.sources.web_search import search_web_for_grants

    brave_key = _get_api_key("brave_search")
    keywords_str = _derive_keywords(config)
    query_idx = int(state.get("query_idx", 0))
    today = datetime.now(timezone.utc).date().isoformat()

    org = _get_org_profile()
    org_state: Optional[str] = (org.get("state") or "").strip().upper() or None

    collected: List[tuple] = []
    next_idx = (query_idx + 1) % 5
    try:
        urls, next_idx = search_web_for_grants(
            keywords=keywords_str,
            brave_api_key=brave_key,
            query_idx=query_idx,
            org_state=org_state,
        )
        for url in urls:
            collected.append((url, "web_search"))
        logger.info("Web search: %d URLs (query_idx=%d)", len(urls), query_idx)
    except Exception as exc:
        logger.warning("Web search failed: %s", exc)

    return collected, {"query_idx": next_idx, "last_run_date": today}


def _collect_federal_register(config: dict, state: dict) -> Tuple[List[tuple], Dict]:
    """
    Collect grant notice URLs from the Federal Register.
    Uses the Federal Register public API (no key required) to find
    recently published NOFAs and funding competition notices.
    """
    from utils.discovery.sources.federal_register import (
        federal_register_to_scrape_urls,
        fetch_federal_register_grants,
    )

    since_date = state.get("last_posted_from")
    today = datetime.now(timezone.utc).date().isoformat()
    keywords_str = _derive_keywords(config)
    max_per_source: int = int(config.get("max_per_source") or 100)

    collected: List[tuple] = []
    try:
        docs = fetch_federal_register_grants(
            keywords=keywords_str,
            since_date=since_date,
            max_results=max_per_source,
        )
        urls = federal_register_to_scrape_urls(docs)
        for url in urls:
            collected.append((url, "federal_register"))
        logger.info("Federal Register: %d URLs (since %s)", len(urls), since_date or "30 days")
    except Exception as exc:
        logger.warning("Federal Register fetch failed: %s", exc)

    return collected, {"last_posted_from": today}
