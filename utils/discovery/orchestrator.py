"""Discovery orchestrator — runs sources in parallel and streams progress.

Phase 1 (parallel + streaming):
  - Each enabled source is wrapped as a DiscoverySource (see sources/registry.py)
    and runs concurrently in a ThreadPoolExecutor.
  - A shared DiscoveryProgress object is updated as sources yield results.
  - On every update a compact snapshot is persisted to
    discovery_runs.progress_snapshot so the UI can recover state after refresh.
  - Cancellation: POST /discovery/runs/{id}/cancel sets the cancel_token;
    sources check it between API pages.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.db.funds_store import get_processed_urls
from utils.discovery.config_store import (
    load_config,
    load_discovery_state,
    save_discovery_state,
)
from utils.discovery.progress_registry import progress_registry
from utils.discovery.run_store import (
    complete_run,
    create_run,
    fail_run,
    save_progress_snapshot,
)
from utils.discovery.document_fetcher import (
    DOCUMENTS_PER_RUN_DEFAULT,
    fetch_documents,
)
from utils.discovery.sources.base import DocumentRef, SourceContext, SourceResult
from utils.discovery.sources.registry import (
    CandidSource,
    FederalRegisterSource,
    GrantsGovDBSource,
    GrantsGovSource,
    IRS_BMF_Source,
    ProPublicaSource,
    SAMCFDASource,
    SamGovSource,
    StatePortalsSource,
)
from utils.models import DiscoveryProgress
from utils.utils_helpers import normalize_url

logger = logging.getLogger(__name__)

_DEFAULT_KEYWORDS = "workforce development employment training nonprofit"
_SNAPSHOT_MIN_INTERVAL_SECS = 1.0  # throttle DB writes; UI gets in-memory data anyway


def _get_effective_states(config: dict) -> List[str]:
    """Return the states to use for discovery.

    Priority:
      1. Operator-configured states (explicit intent wins)
      2. Org home state from the organizations table (avoids rotating through
         all 50 US states when the user hasn't configured anything, which
         means ProPublica surfaces foundations spread across the whole country
         and geographic matching tanks)
      3. Empty list → sources handle fallback internally
    """
    explicit = [s.upper() for s in (config.get("states") or []) if s]
    if explicit:
        return explicit
    org = _get_org_profile()
    home_state = (org.get("state") or "").strip().upper()
    if home_state:
        logger.info(
            "No discovery states configured — using org home state %s as default", home_state
        )
        return [home_state]
    return []


# ── Org / config helpers (unchanged) ──────────────────────────────────────────


@lru_cache(maxsize=1)
def _get_org_profile() -> dict:
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


_SMART_QUOTES = str.maketrans({
    "‘": "'", "’": "'",  # smart single quotes
    "“": '"', "”": '"',  # smart double quotes
    "–": "-", "—": "-",  # en/em dashes
    " ": " ",                  # non-breaking space
})


def _derive_keywords(config: dict) -> str:
    """Build a search query string from explicit config or the org profile.

    Priority:
      1. Operator-set config['keywords'] (explicit intent)
      2. Org's `services` list (structured, topical — best signal)
      3. First sentence of the org's mission (filtered for stopwords)
      4. _DEFAULT_KEYWORDS

    Always strips smart-quote / unicode punctuation so the result is safe to
    URL-encode for downstream search APIs (ProPublica was returning 404s on
    queries containing U+2019).
    """
    keywords_list: List[str] = config.get("keywords") or []
    if keywords_list:
        return " ".join(keywords_list).translate(_SMART_QUOTES).strip()

    org = _get_org_profile()
    parts: List[str] = []

    services = org.get("services")
    if isinstance(services, list) and services:
        # Take the first 3 services — they're already structured topical terms
        for svc in services[:3]:
            parts.extend(str(svc).split())

    # Fall back to the FIRST SENTENCE of the mission only — beyond that is
    # narrative text that pollutes the query
    if not parts and org.get("mission"):
        mission = str(org["mission"]).translate(_SMART_QUOTES)
        first_sentence = mission.split(".")[0]
        parts.extend(first_sentence.split()[:10])

    STOP = {
        "the", "a", "an", "and", "or", "to", "for", "of", "in", "is", "we", "our",
        "this", "that", "are", "be", "have", "with", "from", "by", "on", "as",
        "it", "its", "we're", "they", "their", "easy", "feel", "about",
    }
    seen: set = set()
    filtered: List[str] = []
    for w in parts:
        wl = w.lower().translate(_SMART_QUOTES).strip(".,;:()'\"-")
        # Reject anything that isn't plain alphabetic — kills URL-breaking chars
        if not wl.isalpha():
            continue
        if len(wl) <= 3 or wl in STOP or wl in seen:
            continue
        seen.add(wl)
        filtered.append(wl)

    return " ".join(filtered[:6]) if filtered else _DEFAULT_KEYWORDS


def _get_api_key(service: str) -> Optional[str]:
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


# ── Source assembly ──────────────────────────────────────────────────────────


def _build_enabled_sources(config: dict) -> List[Any]:
    """Return concrete DiscoverySource instances based on the config toggles."""
    sources_cfg = config.get("sources") or {}
    org = _get_org_profile()
    org_state = (org.get("state") or "").strip().upper() or None
    enabled: List[Any] = []

    if sources_cfg.get("propublica", True):
        enabled.append(ProPublicaSource())
    if sources_cfg.get("grants_gov", True):
        enabled.append(GrantsGovSource())
    # SAM.gov: only run when the toggle is explicitly on AND the key exists.
    # Earlier behaviour auto-enabled it whenever the key was present, which
    # surprised users who had deliberately turned it off in the admin UI.
    if sources_cfg.get("sam_gov", False):
        sam_key = _get_api_key("sam_gov")
        if sam_key:
            enabled.append(SamGovSource(api_key=sam_key))
        else:
            logger.info("SAM.gov enabled but no api_token configured — skipping")
    if sources_cfg.get("federal_register", True):
        enabled.append(FederalRegisterSource())
    if sources_cfg.get("state_portals", True):
        enabled.append(StatePortalsSource())
    # Candid: paid API; only enable if both toggled and a key is present
    candid_key = _get_api_key("candid")
    if sources_cfg.get("candid", False) and candid_key:
        enabled.append(CandidSource(api_key=candid_key, org_state=org_state))
    if sources_cfg.get("irs_bmf", True):
        enabled.append(IRS_BMF_Source())
    if sources_cfg.get("grants_gov_db", True):
        enabled.append(GrantsGovDBSource())
    if sources_cfg.get("sam_cfda_db", True):
        enabled.append(SAMCFDASource())

    return enabled


# ── Snapshot throttling ──────────────────────────────────────────────────────


class _SnapshotThrottle:
    """Limit progress_snapshot writes to ~1/sec but always write terminal states."""

    def __init__(self) -> None:
        self._last_write = 0.0
        self._lock = threading.Lock()

    def maybe_write(self, progress: DiscoveryProgress, *, force: bool = False) -> None:
        now = time.time()
        with self._lock:
            if not force and (now - self._last_write) < _SNAPSHOT_MIN_INTERVAL_SECS:
                return
            self._last_write = now
        save_progress_snapshot(progress.run_id, progress.to_snapshot())


# ── Per-source worker ────────────────────────────────────────────────────────


def _run_source(
    source: Any,
    config: dict,
    state_for_source: Dict[str, Any],
    progress: DiscoveryProgress,
    throttle: _SnapshotThrottle,
    keywords: str,
    effective_states: List[str],
) -> Tuple[str, List[Tuple[str, str, Optional[str]]], List[DocumentRef], Dict[str, Any]]:
    """Run a single source to completion in its worker thread.

    Returns: (source_name, [(url, source_name, funder_name)], [document_refs], new_state)
    """
    name = source.name
    progress.update_source(name, status="running", current_action="starting")
    throttle.maybe_write(progress)

    def progress_cb(_name: str, update: Dict[str, Any]) -> None:
        progress.update_source(_name, **update)
        throttle.maybe_write(progress)

    ctx = SourceContext(
        keywords=keywords,
        states=effective_states,
        max_per_source=int(config.get("max_per_source") or 100),
        state=state_for_source or {},
        progress_cb=progress_cb,
        cancel_token=progress.cancel_token,
    )

    collected: List[Tuple[str, str, Optional[str]]] = []
    documents: List[DocumentRef] = []
    error: Optional[str] = None
    try:
        for result in source.fetch(ctx):
            collected.append((result.url, name, result.funder_name))
            sp = progress.ensure_source(name)
            sp.urls_found = len(collected)
            if result.documents:
                # Tag each doc with its source so the fetcher can persist it
                for d in result.documents:
                    if not isinstance(d.extra, dict):
                        d.extra = {}
                    d.extra.setdefault("source", name)
                    documents.append(d)
                sp.documents_found = len(documents)
            throttle.maybe_write(progress)
    except Exception as exc:
        logger.warning("Source %s crashed: %s", name, exc, exc_info=True)
        error = str(exc)

    new_state = source.close_state()

    if progress.cancel_token.is_set():
        progress.update_source(name, status="cancelled", current_action="cancelled")
    elif error:
        progress.update_source(name, status="failed", error=error, current_action=f"failed: {error}")
    else:
        progress.update_source(name, status="completed")

    throttle.maybe_write(progress, force=True)
    logger.info("Source %s finished: %d URLs, %d documents", name, len(collected), len(documents))
    return name, collected, documents, new_state


# ── Main entry point ─────────────────────────────────────────────────────────


def run_discovery(*, trigger: str = "scheduled", run_id: str | None = None) -> str:
    """Full discovery cycle, parallel across sources with live progress."""
    config = load_config()
    if not config.get("enabled") and trigger != "manual":
        logger.debug("Auto-discovery is disabled; skipping scheduled run")
        return ""

    if run_id is None:
        run_id = create_run(trigger, config)
    logger.info("Discovery run %s started (trigger=%s)", run_id, trigger)

    # Register live progress so the frontend can poll /progress immediately.
    progress = progress_registry.create(run_id)
    throttle = _SnapshotThrottle()

    discovery_state: Dict[str, Any] = {}
    new_state: Dict[str, Any] = {}
    all_discovered: List[str] = []
    new_urls: List[str] = []
    scrape_job_id: str | None = None
    url_to_source: Dict[str, str] = {}
    url_to_funder: Dict[str, str] = {}
    all_documents: List[DocumentRef] = []
    failure: Optional[str] = None

    try:
        discovery_state = load_discovery_state()
        sources = _build_enabled_sources(config)
        keywords = _derive_keywords(config)
        effective_states = _get_effective_states(config)

        # Seed pending source slots so the UI shows the full grid from t=0
        for s in sources:
            progress.ensure_source(s.name)
        throttle.maybe_write(progress, force=True)

        max_workers = max(1, len(sources))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="disc") as pool:
            futures = {
                pool.submit(
                    _run_source,
                    s,
                    config,
                    discovery_state.get(s.name, {}),
                    progress,
                    throttle,
                    keywords,
                    effective_states,
                ): s.name
                for s in sources
            }
            for fut in as_completed(futures):
                src_name = futures[fut]
                try:
                    name, collected, docs, src_state = fut.result()
                    new_state[name] = src_state
                    for url, source_name, funder_name in collected:
                        if url and url not in url_to_source:
                            url_to_source[url] = source_name
                            if funder_name:
                                url_to_funder[url] = funder_name
                    all_documents.extend(docs)
                except Exception as exc:
                    logger.error("Source %s failed at top level: %s", src_name, exc, exc_info=True)
                    progress.update_source(src_name, status="failed", error=str(exc))

        all_discovered = list(url_to_source.keys())
        progress.urls_discovered = len(all_discovered)
        logger.info("Discovery found %d total URLs, %d documents", len(all_discovered), len(all_documents))
        throttle.maybe_write(progress, force=True)

        # Document fetching + LLM extraction (Phase 2)
        if all_documents and not progress.cancel_token.is_set():
            progress.status = "running_docs"
            doc_cap = int(config.get("documents_per_run") or DOCUMENTS_PER_RUN_DEFAULT)
            throttle.maybe_write(progress, force=True)

            def _doc_progress(update: Dict[str, Any]) -> None:
                # Lightweight per-document tick; orchestrator updates aggregates below
                pass

            doc_stats = fetch_documents(
                all_documents,
                cancel_token=progress.cancel_token,
                per_run_cap=doc_cap,
                progress_cb=_doc_progress,
            )
            progress.documents_submitted = doc_stats["submitted"]
            progress.documents_downloaded = doc_stats["downloaded"]
            progress.documents_extracted = doc_stats["extracted"]
            progress.documents_skipped_dedup = doc_stats["skipped_dedup"]
            progress.documents_errors = doc_stats["errors"]
            progress.status = "running"
            throttle.maybe_write(progress, force=True)

        if progress.cancel_token.is_set():
            failure = "cancelled"
        else:
            processed = get_processed_urls(force_refresh=True)
            new_urls = [u for u in all_discovered if normalize_url(u) not in processed]
            progress.urls_new = len(new_urls)
            logger.info("Discovery: %d new (unprocessed) URLs after dedup", len(new_urls))

            # Update per-source new-URL counts after global dedup
            per_source_new: Dict[str, int] = {}
            for u in new_urls:
                src = url_to_source.get(u, "")
                if src:
                    per_source_new[src] = per_source_new.get(src, 0) + 1
            for src_name, count in per_source_new.items():
                progress.update_source(src_name, urls_new=count)
            for u in new_urls[:50]:
                progress.add_result_preview({
                    "url": u,
                    "funder_name": url_to_funder.get(u, ""),
                    "source": url_to_source.get(u, ""),
                }, cap=50)
            throttle.maybe_write(progress, force=True)

            if new_urls:
                url_metadata = {
                    u: {
                        "discovery_source": url_to_source.get(u, "auto"),
                        **({"fund_name": url_to_funder[u]} if url_to_funder.get(u) else {}),
                    }
                    for u in new_urls
                }
                from api.jobs import job_store
                job = job_store.create(new_urls, url_metadata=url_metadata)
                scrape_job_id = job.id
                progress.scrape_job_id = scrape_job_id
                logger.info("Discovery spawned scrape job %s for %d URLs", scrape_job_id, len(new_urls))

    except Exception as exc:
        logger.error("Discovery run %s failed: %s", run_id, exc, exc_info=True)
        failure = str(exc)
        fail_run(run_id, failure)
        progress.error = failure
        progress.status = "failed"
        progress.finished_at = time.time()
        throttle.maybe_write(progress, force=True)

    # Always persist whatever per-source progress was made.
    if new_state:
        try:
            save_discovery_state({**discovery_state, **new_state})
        except Exception as exc:
            logger.warning("Could not save discovery state for run %s: %s", run_id, exc)

    if failure is None:
        try:
            complete_run(
                run_id,
                urls_discovered=len(all_discovered),
                urls_new=len(new_urls),
                scrape_job_id=scrape_job_id,
            )
            progress.status = "completed"
            progress.finished_at = time.time()
            throttle.maybe_write(progress, force=True)
            logger.info("Discovery run %s completed", run_id)
        except Exception as exc:
            logger.warning("Could not record completion for run %s: %s", run_id, exc)
    elif failure == "cancelled":
        progress.status = "cancelled"
        progress.finished_at = time.time()
        try:
            fail_run(run_id, "cancelled by user")
        except Exception:
            pass
        throttle.maybe_write(progress, force=True)

    return run_id
