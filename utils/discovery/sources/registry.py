"""Source adapters — wrap each existing source as a DiscoverySource.

Each class is a thin adapter over the underlying fetcher function:
  - sets up per-source rotation / cursor state
  - yields SourceResult instances incrementally
  - checks ctx.cancelled() between API pages
  - reports progress via ctx.progress_cb

All adapters use the existing API helper functions unchanged; the wrapping
exists purely to give the orchestrator a uniform parallel-execution surface.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from utils.discovery.sources.base import DocumentRef, SourceContext, SourceResult

logger = logging.getLogger(__name__)


# ── Foundation pipeline gate (Phase 3 rebuild) ───────────────────────────────


def _persist_foundation_gate(
    sb,
    ein: str,
    *,
    accepts_unsolicited: Optional[bool] = None,
    grants_page_url: Optional[str] = None,
    no_grants_page: bool = False,
    gate_reason: str = "",
) -> None:
    """Cache the foundation gate decision on discovery_funders.

    Defensive against missing columns — wrapped in try/except so a fresh
    schema-not-yet-migrated DB doesn't crash the discovery run.
    """
    if not ein:
        return
    update: Dict[str, Any] = {
        "gate_reason": gate_reason or None,
        "gate_evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    if accepts_unsolicited is not None:
        update["accepts_unsolicited"] = accepts_unsolicited
    if grants_page_url is not None:
        update["grants_page_url"] = grants_page_url
    if no_grants_page:
        update["no_grants_page"] = True
    try:
        sb.table("discovery_funders").update(update).eq("ein", ein).execute()
    except Exception as exc:
        # Missing column? Log once and move on — the gate runs in-memory anyway.
        logger.debug("foundation_gate: persist failed for ein=%s: %s", ein, exc)


def _apply_foundation_gate(
    homepage_url: str,
    *,
    narrative_text: Optional[str],
    org_mission_keywords: List[str],
    program_areas: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str], str]:
    """Run the Phase 3 foundation gates on a single foundation candidate.

    Returns (passed, resolved_grants_page_url, reason_code).
      - passed = False → caller should DROP this foundation (don't yield)
      - resolved_grants_page_url is the URL to scrape (None if passed=False)
      - reason_code is one of:
          'invitation_only', 'no_program_overlap', 'no_grants_page',
          'accepted_keyword', 'accepted_llm'

    Gates (cheapest first to minimise LLM cost on drops):
      1. 990 application_process invitation-only regex → drop
      2. Program-area overlap with org mission keywords → drop if zero overlap
         (only enforced when both lists are non-empty)
      3. foundation_crawler.find_grants_page → drop if None
    """
    from utils.discovery.foundation_crawler import find_grants_page, is_invitation_only

    # Gate 1 — Invitation-only (free, regex on text we already have)
    if narrative_text and is_invitation_only(narrative_text):
        return False, None, "invitation_only"

    # Gate 2 — Program area overlap with org mission
    # Only run when we have both signals; absent program_areas means we don't
    # know the funder's focus and should not pre-drop.
    if program_areas and org_mission_keywords:
        prog_text = " ".join(str(p).lower() for p in program_areas)
        if not any(kw in prog_text for kw in org_mission_keywords):
            return False, None, "no_program_overlap"

    # Gate 3 — Find an actual grants-application page
    result = find_grants_page(homepage_url)
    if not result:
        return False, None, "no_grants_page"
    grants_url, source = result
    return True, grants_url, f"accepted_{source.split('_')[0]}"


def _current_filing_year_floor() -> int:
    """Skip 990s older than this floor.

    IRS Form 990s lag the fiscal year by 1-2 years (e.g. in mid-2026 the most
    recent available 990 is typically FY2023 or FY2024). We default to a 3-year
    window so the latest filing per org passes the filter regardless of lag,
    while still skipping ancient filings that ProPublica sometimes surfaces.
    """
    today = datetime.now(timezone.utc).date()
    return today.year - 3


def _lookback_since(stored_cursor: Optional[str], default_days: int = 7) -> str:
    """Convert a stored cursor into a sensible since-date.

    Sources that incrementally pull "everything since last run" stop returning
    data when the user triggers multiple same-day runs (the cursor is today,
    so the API returns 0). Floor every cursor to `default_days` ago so each
    run always pulls *something*. If stored_cursor is None or earlier than the
    floor we use it as-is — we never want to look further back than what the
    operator's already requested.
    """
    today = datetime.now(timezone.utc).date()
    floor = today - timedelta(days=default_days)
    if not stored_cursor:
        return floor.isoformat()
    try:
        cursor_date = date.fromisoformat(stored_cursor[:10])
    except (ValueError, TypeError):
        return floor.isoformat()
    return min(cursor_date, floor).isoformat()


# Full list of US states for ProPublica rotation (5 per run → 10 runs per full cycle)
_US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]
_STATES_PER_RUN = 5


# ── ProPublica ────────────────────────────────────────────────────────────────


class ProPublicaSource:
    name = "propublica"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from utils.US_Grant_Discovery.prospector import (
            foundations_to_scrape_urls,
            search_foundations,
        )
        from utils.discovery.sources.irs_990_index import (
            ensure_recent_indexes,
            lookup_filing,
        )
        from utils.discovery.sources.irs_990_zips import fetch_multiple_xmls
        from utils.discovery.sources.irs_990_parser import xml_to_narrative

        # Pick which states to query this run.
        # • No explicit states → rotate through all 50 in batches of 5.
        # • Single explicit state → just query it (no rotation makes sense).
        # • Multi explicit states → rotate within the configured list so
        #   same-day re-runs still return different data.
        if ctx.states:
            user_states = [s.upper() for s in ctx.states]
            if len(user_states) <= 1:
                states_to_query = user_states
                self._new_state = ctx.state
            else:
                idx = int(ctx.state.get("next_state_idx", 0)) % len(user_states)
                step = min(_STATES_PER_RUN, len(user_states))
                states_to_query = [
                    user_states[(idx + i) % len(user_states)] for i in range(step)
                ]
                self._new_state = {"next_state_idx": (idx + step) % len(user_states)}
        else:
            idx = int(ctx.state.get("next_state_idx", 0)) % len(_US_STATES)
            states_to_query = [
                _US_STATES[(idx + i) % len(_US_STATES)] for i in range(_STATES_PER_RUN)
            ]
            self._new_state = {"next_state_idx": (idx + _STATES_PER_RUN) % len(_US_STATES)}

        per_state_limit = max(10, ctx.max_per_source // max(len(states_to_query), 1))
        # Deliberately do NOT pass a keyword to ProPublica's API: state-only
        # search returns far more grantmaking foundations. The org-derived
        # keyword is narrative-shaped, not foundation-shaped, and ProPublica
        # returns 404 on queries with smart quotes or weird tokens. The downstream
        # IRS index lookup + LLM extract still surface relevance.
        keywords = None
        year_floor = _current_filing_year_floor()

        # Pass 1: search ProPublica across all states, dedup by EIN.
        # (Different states can surface the same foundation if it has offices
        # in multiple places; the IRS XML lookup is keyed on EIN.)
        collected: List[Dict[str, Any]] = []  # ordered, [(url, org, state), ...]
        seen_urls: set = set()
        for query_state in states_to_query:
            if ctx.cancelled():
                return
            ctx.progress_cb(self.name, {"current_action": f"searching state={query_state}"})
            try:
                foundations = search_foundations(
                    state=query_state,
                    keywords=keywords,
                    max_results=per_state_limit,
                )
            except Exception as exc:
                logger.warning("ProPublica search failed for state=%s: %s", query_state, exc)
                ctx.progress_cb(self.name, {"current_action": f"state={query_state} failed: {exc}"})
                continue
            for f in foundations:
                site = f.get("website") or f.get("propublica_url") or ""
                if not site or site in seen_urls:
                    continue
                seen_urls.add(site)
                collected.append({"url": site, "org": f, "state": query_state})
            ctx.progress_cb(self.name, {"urls_found": len(collected)})

        # Pass 2: bulk-lookup latest IRS filings via cached index, then
        # batch-download the ZIPs (each ZIP holds thousands of filings, so
        # we only pay one HTTP per batch even if many orgs land in the same
        # batch).
        ctx.progress_cb(self.name, {"current_action": "loading IRS 990 index"})
        try:
            ensure_recent_indexes(years_back=2)
        except Exception as exc:
            logger.warning("IRS index refresh failed (continuing without): %s", exc)

        ein_to_filing: Dict[str, Dict[str, Any]] = {}
        for item in collected:
            if ctx.cancelled():
                return
            ein = str(item["org"].get("ein") or "").strip()
            if not ein:
                continue
            rec = lookup_filing(ein)
            if rec and int(rec.get("tax_year") or 0) >= year_floor:
                ein_to_filing[ein] = rec

        # Group + fetch ZIPs in batch
        if ein_to_filing:
            unique_batches = sorted({(r["batch_zip"], int(r["submission_year"])) for r in ein_to_filing.values()})
            ctx.progress_cb(self.name, {
                "current_action": (
                    f"fetching IRS XMLs for {len(ein_to_filing)} orgs "
                    f"({len(unique_batches)} batch{'es' if len(unique_batches)!=1 else ''})"
                ),
            })

            def _zip_progress(msg: str) -> None:
                # Stream IRS ZIP download status into the source's progress UI.
                # Lets the operator see "downloading X (Y/ZMB, P%)" instead of
                # a frozen "fetching IRS XMLs" line for 5-15 minutes.
                ctx.progress_cb(self.name, {"current_action": msg})

            try:
                xml_by_object_id = fetch_multiple_xmls(
                    ((r["object_id"], r["batch_zip"], int(r["submission_year"]))
                     for r in ein_to_filing.values()),
                    progress_cb=_zip_progress,
                )
            except Exception as exc:
                logger.warning("IRS ZIP fetch failed: %s", exc)
                xml_by_object_id = {}
        else:
            xml_by_object_id = {}

        # Pass 2.5: resolve each org's actual website.
        # Priority: ProPublica search result → IRS 990 XML → ProPublica detail API.
        # Orgs that end up with only a propublica.org profile URL AND no 990 documents
        # are skipped — the profile page has no grantmaking info and produces garbage results.
        from utils.discovery.sources.irs_990_parser import extract_website_from_xml
        from utils.US_Grant_Discovery.prospector import resolve_org_website
        from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _ac

        ein_to_website: Dict[str, str] = {}
        for item in collected:
            ein = str(item["org"].get("ein") or "").strip()
            # Already resolved by ProPublica search result
            ws = item["org"].get("website") or ""
            if ws and not ws.startswith("https://projects.propublica.org"):
                ein_to_website[ein] = ws
                continue
            # Try to extract website from the IRS 990 XML (no extra HTTP calls)
            filing_rec = ein_to_filing.get(ein)
            if filing_rec:
                xml = xml_by_object_id.get(filing_rec.get("object_id", ""))
                if xml:
                    ws = extract_website_from_xml(xml)
                    if ws:
                        ein_to_website[ein] = ws

        # Batch-call ProPublica detail API for the remaining orgs (5 threads in parallel)
        eins_still_missing = [
            str(item["org"].get("ein") or "").strip()
            for item in collected
            if str(item["org"].get("ein") or "").strip()
            and str(item["org"].get("ein") or "").strip() not in ein_to_website
        ]
        if eins_still_missing:
            ctx.progress_cb(self.name, {
                "current_action": (
                    f"resolving {len(eins_still_missing)} org websites via ProPublica detail API"
                ),
            })
            with _TPE(max_workers=5) as pool:
                fut_to_ein = {pool.submit(resolve_org_website, ein): ein for ein in eins_still_missing}
                for fut in _ac(fut_to_ein):
                    if ctx.cancelled():
                        break
                    ein_r = fut_to_ein[fut]
                    try:
                        ws = fut.result()
                    except Exception:
                        ws = ""
                    if ws:
                        ein_to_website[ein_r] = ws

        # Phase 3 (foundation pipeline rebuild) — load org for gates
        from utils.discovery.prefilter import load_org_profile
        try:
            _org_prof = load_org_profile()
            org_mission_kws = _org_prof.mission_keywords()
        except Exception:
            org_mission_kws = []
        # Local supabase handle for persisting gate decisions
        try:
            from supabase import create_client
            from utils.config import get_settings
            _s = get_settings()
            _sb = create_client(_s.supabase_url, _s.supabase_service_key)
        except Exception:
            _sb = None

        # Pass 3 — build candidate list, then run the Phase 3 foundation gate
        # in parallel (Phase 8). Pre-pass 3a does the heavy 990 narrative parse
        # + DocumentRef construction + homepage resolution serially so the
        # gate worker only does HTTP/LLM work.
        urls_yielded = 0
        skipped_no_site = 0
        dropped_invitation = 0
        dropped_no_grants_page = 0
        resolved_urls: set = set()

        # Phase 3a — build candidate list (cheap, sequential)
        gate_candidates: List[Dict[str, Any]] = []
        bypass_candidates: List[Dict[str, Any]] = []  # ProPublica-fallback URLs skip the gate
        seen_for_dedup: set = set()
        for item in collected:
            if ctx.cancelled():
                return
            org = item["org"]
            ein = str(org.get("ein") or "").strip()

            documents: List[DocumentRef] = []
            filing_rec = ein_to_filing.get(ein)
            xml_text = xml_by_object_id.get(filing_rec["object_id"]) if filing_rec else None
            narrative = ""

            if xml_text:
                narrative = xml_to_narrative(xml_text) or ""
                if narrative:
                    documents.append(DocumentRef(
                        url=(
                            f"https://apps.irs.gov/pub/epostcard/990/xml/"
                            f"{filing_rec['submission_year']}/{filing_rec['object_id']}_public.xml"
                        ),
                        kind="form_990",
                        source_url=item["url"],
                        filing_year=int(filing_rec["tax_year"]),
                        extra={
                            "source": self.name,
                            "ein": ein,
                            "object_id": filing_rec["object_id"],
                            "irs_source": "bulk_zip",
                            "return_type": filing_rec.get("return_type", ""),
                        },
                        prefetched_text=narrative,
                    ))

            # Determine the homepage URL we have on hand
            resolved = ein_to_website.get(ein, "")
            if resolved and resolved not in seen_for_dedup:
                homepage = resolved
                seen_for_dedup.add(homepage)
            elif not resolved:
                if not documents:
                    skipped_no_site += 1
                    continue
                homepage = item["url"]  # ProPublica profile fallback
            else:
                continue  # duplicate across states

            is_real_site = homepage and not homepage.startswith("https://projects.propublica.org")
            payload = {
                "item": item, "org": org, "ein": ein,
                "documents": documents, "narrative": narrative,
                "homepage": homepage, "is_real_site": is_real_site,
            }
            if is_real_site:
                gate_candidates.append(payload)
            else:
                bypass_candidates.append(payload)

        # Phase 3b — yield bypass candidates immediately (no gate, 990 context compensates)
        for c in bypass_candidates:
            if ctx.cancelled():
                return
            url = c["homepage"]
            resolved_urls.add(url)
            urls_yielded += 1
            yield SourceResult(
                url=url,
                funder_name=c["org"].get("name", ""),
                source_metadata={
                    "source": self.name,
                    "state": c["item"]["state"],
                    "ein": c["ein"],
                    "homepage_url": "",
                },
                documents=c["documents"],
            )

        # Phase 3c — run gate in parallel (Phase 8 fix)
        if gate_candidates:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            total = len(gate_candidates)
            ctx.progress_cb(self.name, {
                "current_action": f"foundation gate ({total} sites, parallel x5)",
            })
            completed_count = 0
            with ThreadPoolExecutor(max_workers=5, thread_name_prefix="ppub-gate") as pool:
                fut_to_cand = {
                    pool.submit(
                        _apply_foundation_gate,
                        c["homepage"],
                        narrative_text=c["narrative"],
                        org_mission_keywords=org_mission_kws,
                        program_areas=None,
                    ): c
                    for c in gate_candidates
                }
                for fut in as_completed(fut_to_cand):
                    if ctx.cancelled():
                        break
                    c = fut_to_cand[fut]
                    ein = c["ein"]
                    homepage = c["homepage"]
                    try:
                        passed, grants_url, reason = fut.result()
                    except Exception as exc:
                        logger.warning("foundation_gate raised for ein=%s: %s", ein, exc)
                        passed, grants_url, reason = False, None, "gate_error"

                    completed_count += 1
                    if completed_count % 5 == 0 or completed_count == total:
                        ctx.progress_cb(self.name, {
                            "current_action": (
                                f"gate {completed_count}/{total}: "
                                f"{urls_yielded - len(bypass_candidates)} accepted, "
                                f"{dropped_invitation} invitation-only, "
                                f"{dropped_no_grants_page} no grants page"
                            ),
                        })

                    if not passed:
                        if _sb is not None:
                            if reason == "invitation_only":
                                dropped_invitation += 1
                                _persist_foundation_gate(_sb, ein, accepts_unsolicited=False, gate_reason=reason)
                            elif reason == "no_grants_page":
                                dropped_no_grants_page += 1
                                _persist_foundation_gate(_sb, ein, no_grants_page=True, gate_reason=reason)
                            else:
                                _persist_foundation_gate(_sb, ein, gate_reason=reason)
                        continue

                    url = grants_url or homepage
                    if _sb is not None:
                        _persist_foundation_gate(
                            _sb, ein,
                            accepts_unsolicited=True,
                            grants_page_url=grants_url,
                            gate_reason=reason,
                        )
                    resolved_urls.add(url)
                    urls_yielded += 1
                    yield SourceResult(
                        url=url,
                        funder_name=c["org"].get("name", ""),
                        source_metadata={
                            "source": self.name,
                            "state": c["item"]["state"],
                            "ein": ein,
                            "homepage_url": homepage,
                        },
                        documents=c["documents"],
                    )

        ctx.progress_cb(self.name, {
            "current_action": (
                f"done ({urls_yielded} yielded, {skipped_no_site} no-site, "
                f"{dropped_invitation} invitation-only, "
                f"{dropped_no_grants_page} no grants page)"
            ),
        })

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


# ── Grants.gov ────────────────────────────────────────────────────────────────


class GrantsGovSource:
    name = "grants_gov"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from utils.US_Grant_Discovery.grants_gov_search import (
            federal_grants_to_scrape_urls,
            search_federal_grants,
        )

        today = datetime.now(timezone.utc).date()
        # Floor the cursor to last week so same-day re-runs still return data
        last_posted = _lookback_since(ctx.state.get("last_posted_from"), default_days=14)

        ctx.progress_cb(self.name, {"current_action": f"querying (posted since {last_posted})"})
        try:
            # Grants.gov treats `keyword` as an exact phrase match — passing
            # the derived multi-word string returns 0 hits. We pass it only
            # if the operator set an explicit single-keyword override.
            # The `eligibilities` filter also zeros out almost every result
            # (Grants.gov publishers rarely tag with code 12), so we drop it.
            kw = (ctx.keywords or "").strip()
            api_kw = kw if (kw and len(kw.split()) <= 2) else ""
            grants = search_federal_grants(
                keywords=api_kw,
                eligible_applicants=None,
                posted_from=last_posted,
                max_results=ctx.max_per_source,
            )
            urls = federal_grants_to_scrape_urls(grants)
            url_to_title: Dict[str, str] = {
                g["opportunity_url"]: g.get("opportunity_title", "")
                for g in grants
                if g.get("opportunity_url")
            }
            for url in urls:
                if ctx.cancelled():
                    return
                yield SourceResult(
                    url=url,
                    funder_name=url_to_title.get(url, ""),
                    source_metadata={"source": self.name, "posted_since": last_posted},
                )
        except Exception as exc:
            logger.warning("Grants.gov search failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"failed: {exc}"})

        self._new_state = {"last_posted_from": today.isoformat()}

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


# ── SAM.gov ───────────────────────────────────────────────────────────────────


class SamGovSource:
    name = "sam_gov"

    def __init__(self, api_key: Optional[str]) -> None:
        self._api_key = api_key
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from utils.discovery.sources.sam_gov import sam_gov_to_scrape_urls, search_sam_gov

        if not self._api_key:
            ctx.progress_cb(self.name, {"current_action": "skipped (no API key)"})
            self._new_state = ctx.state
            return

        last_posted = _lookback_since(ctx.state.get("last_posted_from"), default_days=14)
        today = datetime.now(timezone.utc).date().isoformat()

        ctx.progress_cb(self.name, {"current_action": f"querying (posted since {last_posted})"})
        try:
            opportunities = search_sam_gov(
                keywords=ctx.keywords,
                api_key=self._api_key,
                posted_from=last_posted,
                max_results=ctx.max_per_source,
            )
            urls = sam_gov_to_scrape_urls(opportunities)
            url_to_opp: Dict[str, Dict[str, Any]] = {
                o["opportunity_url"]: o for o in opportunities if o.get("opportunity_url")
            }
            for url in urls:
                if ctx.cancelled():
                    return
                opp = url_to_opp.get(url, {})
                documents: List[DocumentRef] = []

                # Build prefetched_text from API data so the LLM can evaluate
                # even if the sam.gov SPA page can't be scraped (JS-rendered).
                summary_lines = [
                    f"SAM.gov Grant Opportunity: {opp.get('title', '')}",
                    f"Federal Agency: {opp.get('agency_name', '')}",
                    f"Posted: {opp.get('posted_date', '')}",
                    f"Closes: {opp.get('close_date', '')}",
                    f"Opportunity URL: {url}",
                ]
                if opp.get("description"):
                    summary_lines.append(f"Description: {opp['description']}")
                if opp.get("set_aside_type"):
                    summary_lines.append(f"Set-Aside Type: {opp['set_aside_type']}")
                documents.append(DocumentRef(
                    url=f"sam_gov_api://{opp.get('notice_id', '')}",
                    kind="rfp",
                    source_url=url,
                    extra={"source": self.name, "notice_id": opp.get("notice_id", "")},
                    prefetched_text="\n".join(summary_lines),
                ))

                for link in opp.get("resource_links") or []:
                    if isinstance(link, str) and link.startswith("http"):
                        documents.append(DocumentRef(
                            url=link,
                            kind="attachment",
                            source_url=url,
                        ))
                yield SourceResult(
                    url=url,
                    funder_name=opp.get("title", ""),
                    source_metadata={"source": self.name, "agency": opp.get("agency_name", "")},
                    documents=documents,
                )
        except Exception as exc:
            logger.warning("SAM.gov search failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"failed: {exc}"})

        self._new_state = {"last_posted_from": today}

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


# Cut 2026-05-29 (Phase 4): WebSearchSource removed — web search returned
# generic listicles / dead links / aggregator pages with poor signal-to-noise.
# Replaced with structured directories (Grants.gov DB, IRS BMF, federal
# register, state portals).


# ── Federal Register ──────────────────────────────────────────────────────────


class FederalRegisterSource:
    name = "federal_register"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from utils.discovery.sources.federal_register import (
            federal_register_to_scrape_urls,
            fetch_federal_register_grants,
        )

        since_date = _lookback_since(ctx.state.get("last_posted_from"), default_days=14)
        today = datetime.now(timezone.utc).date().isoformat()

        ctx.progress_cb(self.name, {"current_action": f"querying (since {since_date})"})
        try:
            # Same phrase-match issue as Grants.gov — Federal Register's
            # `conditions[term]` is an exact-phrase filter, so passing 6+
            # derived words returns 0. Use single-word override only.
            kw = (ctx.keywords or "").strip()
            api_kw = kw if (kw and len(kw.split()) <= 2) else ""
            docs = fetch_federal_register_grants(
                keywords=api_kw,
                since_date=since_date,
                max_results=ctx.max_per_source,
            )
            urls = federal_register_to_scrape_urls(docs)
            url_to_doc: Dict[str, Dict[str, Any]] = {
                d["html_url"]: d for d in docs if d.get("html_url")
            }
            for url in urls:
                if ctx.cancelled():
                    return
                doc = url_to_doc.get(url, {})
                documents: List[DocumentRef] = []
                if doc.get("pdf_url"):
                    documents.append(DocumentRef(
                        url=doc["pdf_url"],
                        kind="notice",
                        source_url=url,
                        extra={"publication_date": doc.get("publication_date", "")},
                    ))
                yield SourceResult(
                    url=url,
                    funder_name=doc.get("title", ""),
                    source_metadata={"source": self.name},
                    documents=documents,
                )
        except Exception as exc:
            logger.warning("Federal Register fetch failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"failed: {exc}"})

        self._new_state = {"last_posted_from": today}

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


# ── State portals (Phase 3) ──────────────────────────────────────────────────


class StatePortalsSource:
    """Fan-out source that runs every registered state-portal adapter in parallel.

    Each adapter (see utils/discovery/sources/state_portals/) returns a list
    of grant dicts. We yield each as a SourceResult tagged with the state.
    Adapters that fail are logged but don't fail the whole source.
    """

    name = "state_portals"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from utils.discovery.sources.state_portals import STATE_ADAPTERS

        today = datetime.now(timezone.utc).date().isoformat()
        since_date = ctx.state.get("last_run_date")
        # Split the per-source budget evenly across adapters
        per_state_limit = max(20, ctx.max_per_source // max(len(STATE_ADAPTERS), 1))

        ctx.progress_cb(self.name, {
            "current_action": f"fanning out to {len(STATE_ADAPTERS)} state adapters",
        })

        # Most state portals do free-text matching against full grant titles
        # only; passing the long derived org keyword filters out 99% of
        # opportunities. Drop the keyword unless the operator gave us a
        # short, focused override.
        kw = (ctx.keywords or "").strip()
        adapter_kw = kw if (kw and len(kw.split()) <= 2) else ""

        def _run_adapter(state_code: str, adapter):
            if ctx.cancelled():
                return state_code, []
            try:
                return state_code, adapter(
                    keywords=adapter_kw,
                    since_date=since_date,
                    max_results=per_state_limit,
                )
            except Exception as exc:
                logger.warning("State adapter %s crashed: %s", state_code, exc)
                return state_code, []

        with ThreadPoolExecutor(max_workers=min(len(STATE_ADAPTERS) or 1, 5)) as pool:
            futures = [pool.submit(_run_adapter, s, a) for s, a in STATE_ADAPTERS.items()]
            for fut in as_completed(futures):
                if ctx.cancelled():
                    return
                state_code, records = fut.result()
                ctx.progress_cb(self.name, {
                    "current_action": f"{state_code}: {len(records)} records",
                })
                for rec in records:
                    if ctx.cancelled():
                        return
                    url = (rec.get("url") or "").strip()
                    if not url:
                        continue
                    yield SourceResult(
                        url=url,
                        funder_name=rec.get("title") or rec.get("agency", ""),
                        source_metadata={
                            "source": self.name,
                            "state": state_code,
                            "agency": rec.get("agency", ""),
                            "deadline": rec.get("deadline", ""),
                            "applicant_types": rec.get("applicant_types", ""),
                            "funding_amount": rec.get("funding_amount", ""),
                            "categories": rec.get("categories", ""),
                        },
                    )

        self._new_state = {"last_run_date": today}

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


# Cut 2026-05-29 (Phase 4): USAspendingSource removed — usaspending.gov/recipient/*
# pages show who RECEIVED federal money, not how to apply for it. Wrong target
# for grant discovery. Grants.gov + Federal Register cover the open-opportunity
# side of federal funding.


# ── Candid (paid API, gated on key) ──────────────────────────────────────────


class CandidSource:
    """Candid Essentials search — gated on a paid API key in api_tokens."""

    name = "candid"

    def __init__(self, api_key: Optional[str], org_state: Optional[str]) -> None:
        self._api_key = api_key
        self._org_state = org_state
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from utils.discovery.sources.candid import search_candid_funders

        if not self._api_key:
            ctx.progress_cb(self.name, {"current_action": "skipped (no API key)"})
            return

        ctx.progress_cb(self.name, {"current_action": "querying Candid Essentials"})
        try:
            funders = search_candid_funders(
                api_key=self._api_key,
                keywords=ctx.keywords,
                state=self._org_state,
                max_results=ctx.max_per_source,
            )
        except Exception as exc:
            logger.warning("Candid query failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"failed: {exc}"})
            return

        for f in funders:
            if ctx.cancelled():
                return
            website = f.get("website") or ""
            if not website:
                continue
            yield SourceResult(
                url=website,
                funder_name=f.get("name", ""),
                source_metadata={
                    "source": self.name,
                    "ein": f.get("ein", ""),
                    "city": f.get("city", ""),
                    "state": f.get("state", ""),
                    "classification": f.get("classification", ""),
                },
            )

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


# Cut 2026-05-29 (Phase 4): PhilanthropyDigestSource removed — PND was
# acquired by Candid in 2026 and its public RSS feeds are no longer maintained.


# ── IRS BMF (private foundations database) ───────────────────────────────────


class IRS_BMF_Source:
    name = "irs_bmf"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from supabase import create_client
        from utils.config import get_settings
        from utils.discovery.config_store import load_config
        from utils.discovery.prefilter import (
            emit_telemetry,
            filter_funders,
            load_org_profile,
        )
        from utils.US_Grant_Discovery.prospector import resolve_org_website
        from utils.discovery.sources.irs_990_zips import fetch_multiple_xmls
        from utils.discovery.sources.irs_990_parser import extract_website_from_xml

        _s = get_settings()
        sb = create_client(_s.supabase_url, _s.supabase_service_key)

        config = load_config()
        import_cfg = config.get("import_config") or {}
        min_asset_code = int(import_cfg.get("bmf_min_asset_code") or 7)
        batch_size = int(import_cfg.get("bmf_batch_size") or 50)
        ntee_prefixes: List[str] = import_cfg.get("bmf_ntee_prefixes") or []
        explicit_states: List[str] = [s.upper() for s in (ctx.states or [])]

        org = load_org_profile()
        # If discovery_config.states is set, it overrides the org's service_states
        # (operator's explicit per-run intent wins).
        if explicit_states:
            org.service_states = explicit_states

        ctx.progress_cb(self.name, {"current_action": "applying org-profile pre-filter"})
        result = filter_funders(
            sb,
            org,
            min_asset_code=min_asset_code,
            ntee_prefixes=ntee_prefixes,
            limit=batch_size,
            only_unscraped=True,
        )
        emit_telemetry(ctx.progress_cb, self.name, result.telemetry)
        batch = result.rows

        if not batch:
            ctx.progress_cb(self.name, {"current_action": "pre-filter produced no candidates"})
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        all_eins: List[str] = [r["ein"] for r in batch]

        # Pre-populate websites from already-resolved DB values
        ein_to_website: Dict[str, str] = {}
        for row in batch:
            ws = row.get("website") or ""
            if ws:
                ein_to_website[row["ein"]] = ws

        # Phase 1: IRS 990 index lookup (uses local sb — no singleton race)
        ein_to_filing: Dict[str, Dict[str, Any]] = {}
        xml_by_object_id: Dict[str, str] = {}
        needs_990 = [r for r in batch if r["ein"] not in ein_to_website]
        if needs_990:
            ctx.progress_cb(self.name, {"current_action": f"looking up {len(needs_990)} EINs in IRS 990 index"})
            year_floor = datetime.now(timezone.utc).year - 3
            try:
                ein_list = [r["ein"] for r in needs_990]
                # Single bulk query instead of N individual round-trips
                all_filings = (
                    sb.table("irs_990_index")
                    .select("ein, object_id, batch_zip, submission_year, tax_year, return_type")
                    .in_("ein", ein_list)
                    .order("tax_year", desc=True)
                    .execute()
                    .data or []
                )
                # Keep only the most recent filing per EIN (already ordered desc)
                for rec in all_filings:
                    ein = rec["ein"]
                    if ein not in ein_to_filing and int(rec.get("tax_year") or 0) >= year_floor:
                        ein_to_filing[ein] = rec
            except Exception as exc:
                logger.warning("IRS_BMF_Source: 990 index lookup failed: %s", exc)

            if ein_to_filing:
                unique_batches = sorted({
                    (r["batch_zip"], int(r["submission_year"]))
                    for r in ein_to_filing.values()
                })
                ctx.progress_cb(self.name, {
                    "current_action": (
                        f"fetching 990 XMLs for {len(ein_to_filing)} foundations "
                        f"({len(unique_batches)} batch{'es' if len(unique_batches) != 1 else ''})"
                    ),
                })

                def _zip_progress(msg: str) -> None:
                    ctx.progress_cb(self.name, {"current_action": msg})

                try:
                    xml_by_object_id = fetch_multiple_xmls(
                        ((r["object_id"], r["batch_zip"], int(r["submission_year"]))
                         for r in ein_to_filing.values()),
                        progress_cb=_zip_progress,
                    )
                except Exception as exc:
                    logger.warning("IRS_BMF_Source: 990 ZIP fetch failed: %s", exc)

                for ein, rec in ein_to_filing.items():
                    xml = xml_by_object_id.get(rec.get("object_id", ""))
                    if xml:
                        ws = extract_website_from_xml(xml)
                        if ws:
                            ein_to_website[ein] = ws

        # Phase 2: ProPublica API fallback for EINs without a website yet
        still_missing = [r for r in batch if r["ein"] not in ein_to_website]
        if still_missing:
            ctx.progress_cb(self.name, {
                "current_action": f"resolving {len(still_missing)} websites via ProPublica",
            })

            def _resolve(row: Dict[str, Any]) -> Optional[str]:
                try:
                    return resolve_org_website(row["ein"])
                except Exception:
                    return None

            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {pool.submit(_resolve, row): row for row in still_missing}
                for future in as_completed(futures):
                    if ctx.cancelled():
                        break
                    row = futures[future]
                    website = future.result()
                    if website:
                        ein_to_website[row["ein"]] = website
                        try:
                            sb.table("discovery_funders").update(
                                {"website": website, "website_resolved_at": now_iso}
                            ).eq("ein", row["ein"]).execute()
                        except Exception as exc:
                            logger.debug("Could not persist website for %s: %s", row["ein"], exc)

        # Mark all processed funders as scraped_at = now (even without website,
        # so we don't keep retrying unresolvable foundations every run)
        try:
            sb.table("discovery_funders").update(
                {"scraped_at": now_iso}
            ).in_("ein", all_eins).execute()
        except Exception as exc:
            logger.warning("IRS_BMF_Source: could not update scraped_at: %s", exc)

        # Phase 3 — extract 990 narrative text for invitation-only gate.
        # Reuses the XMLs already fetched above (no extra HTTP).
        from utils.discovery.sources.irs_990_parser import xml_to_narrative
        ein_to_narrative: Dict[str, str] = {}
        for ein, rec in ein_to_filing.items():
            xml = xml_by_object_id.get(rec.get("object_id", ""))
            if xml:
                try:
                    txt = xml_to_narrative(xml) or ""
                    if txt:
                        ein_to_narrative[ein] = txt
                except Exception:
                    pass

        # Phase 3 — derived org-mission keywords for program-area overlap gate
        org_kws = org.mission_keywords()

        # Build the candidate list ONCE so we can parallelise the gate.
        # Rows with no resolved homepage are pre-filtered (nothing to crawl).
        candidates: List[Dict[str, Any]] = []
        for row in batch:
            ein = row["ein"]
            homepage = ein_to_website.get(ein)
            if not homepage:
                continue
            candidates.append({
                "row": row,
                "ein": ein,
                "homepage": homepage,
                "narrative": ein_to_narrative.get(ein),
            })

        resolved_count = len(candidates)
        ctx.progress_cb(self.name, {
            "current_action": f"applying foundation gates to {resolved_count} candidates (parallel)",
        })

        # Phase 8 — parallelise the foundation gate.
        # Each candidate does 1 HTTP fetch (homepage) + maybe 1 LLM call. Five
        # concurrent workers caps download bandwidth and OpenAI RPS while
        # cutting wall-clock from ~5 min to ~1 min on a 50-candidate batch.
        yielded = 0
        dropped_invitation = 0
        dropped_no_grants_page = 0
        completed_count = 0
        if candidates:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=5, thread_name_prefix="bmf-gate") as pool:
                fut_to_cand = {
                    pool.submit(
                        _apply_foundation_gate,
                        c["homepage"],
                        narrative_text=c["narrative"],
                        org_mission_keywords=org_kws,
                        program_areas=None,
                    ): c
                    for c in candidates
                }
                for fut in as_completed(fut_to_cand):
                    if ctx.cancelled():
                        break
                    c = fut_to_cand[fut]
                    ein = c["ein"]
                    homepage = c["homepage"]
                    row = c["row"]
                    try:
                        passed, grants_url, reason = fut.result()
                    except Exception as exc:
                        logger.warning("foundation_gate raised for ein=%s: %s", ein, exc)
                        passed, grants_url, reason = False, None, "gate_error"

                    completed_count += 1
                    # Live progress so the UI shows the gate making progress
                    if completed_count % 5 == 0 or completed_count == resolved_count:
                        ctx.progress_cb(self.name, {
                            "current_action": (
                                f"gate {completed_count}/{resolved_count}: "
                                f"{yielded} accepted, {dropped_invitation} invitation-only, "
                                f"{dropped_no_grants_page} no grants page"
                            ),
                        })

                    if not passed:
                        if reason == "invitation_only":
                            dropped_invitation += 1
                            _persist_foundation_gate(
                                sb, ein, accepts_unsolicited=False, gate_reason=reason
                            )
                        elif reason == "no_grants_page":
                            dropped_no_grants_page += 1
                            _persist_foundation_gate(
                                sb, ein, no_grants_page=True, gate_reason=reason
                            )
                        else:
                            _persist_foundation_gate(sb, ein, gate_reason=reason)
                        continue

                    _persist_foundation_gate(
                        sb, ein,
                        accepts_unsolicited=True,
                        grants_page_url=grants_url,
                        gate_reason=reason,
                    )
                    yielded += 1
                    yield SourceResult(
                        url=grants_url or homepage,
                        funder_name=row.get("name"),
                        source_metadata={
                            "source": self.name,
                            "ein": ein,
                            "city": row.get("city"),
                            "state": row.get("state"),
                            "homepage_url": homepage,
                            "gate_reason": reason,
                        },
                    )

        ctx.progress_cb(self.name, {
            "current_action": (
                f"gate: {yielded} accepted, {dropped_invitation} invitation-only, "
                f"{dropped_no_grants_page} no grants page"
            ),
        })

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


# ── SAM CFDA DB (program listings from monthly import) ───────────────────────


class SAMCFDASource:
    """Yields federal program website URLs from the sam_cfda_listings table.

    Each CFDA program row has a website_address pointing to the federal agency's
    description page for that grant program — a richer target than the SAM.gov
    opportunity listing. The program objectives and eligibility text are injected
    as prefetched_text so the LLM can evaluate without scraping JS-heavy pages.
    """

    name = "sam_cfda_db"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from supabase import create_client
        from utils.config import get_settings
        from utils.db.funds_store import get_processed_urls

        _s = get_settings()
        sb = create_client(_s.supabase_url, _s.supabase_service_key)

        ctx.progress_cb(self.name, {"current_action": "querying sam_cfda_listings"})
        try:
            rows = (
                sb.table("sam_cfda_listings")
                .select(
                    "program_number, program_title, federal_agency, objectives, "
                    "applicant_eligibility, website_address"
                )
                .not_.is_("website_address", "null")
                .limit(ctx.max_per_source * 3)
                .execute()
                .data or []
            )
        except Exception as exc:
            logger.warning("SAMCFDASource: query failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"failed: {exc}"})
            return

        try:
            processed = get_processed_urls()
        except Exception:
            processed = set()

        count = 0
        for row in rows:
            if ctx.cancelled():
                return
            url = (row.get("website_address") or "").strip()
            if not url or not url.startswith("http"):
                continue
            if url in processed:
                continue

            lines = [
                f"CFDA Program: {row.get('program_title', '')} ({row.get('program_number', '')})",
                f"Federal Agency: {row.get('federal_agency', '')}",
            ]
            if row.get("objectives"):
                lines.append(f"Objectives: {row['objectives']}")
            if row.get("applicant_eligibility"):
                lines.append(f"Applicant Eligibility: {row['applicant_eligibility']}")

            yield SourceResult(
                url=url,
                funder_name=row.get("federal_agency") or row.get("program_title", ""),
                source_metadata={
                    "source": self.name,
                    "program_number": row.get("program_number", ""),
                    "program_title": row.get("program_title", ""),
                },
                documents=[
                    DocumentRef(
                        url=f"sam_cfda://{row.get('program_number', '')}",
                        kind="rfp",
                        source_url=url,
                        extra={"source": self.name, "cfda_number": row.get("program_number", "")},
                        prefetched_text="\n".join(lines),
                    )
                ],
            )
            count += 1
            if count >= ctx.max_per_source:
                break

        ctx.progress_cb(self.name, {"urls_found": count})

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


# ── Grants.gov DB (from daily XML import) ────────────────────────────────────


class GrantsGovDBSource:
    name = "grants_gov_db"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from supabase import create_client
        from utils.config import get_settings
        from utils.db.funds_store import get_processed_urls
        from utils.discovery.config_store import load_config
        from utils.discovery.prefilter import (
            emit_telemetry,
            filter_opportunities,
            load_org_profile,
        )

        _s = get_settings()
        sb = create_client(_s.supabase_url, _s.supabase_service_key)

        config = load_config()
        import_cfg = config.get("import_config") or {}
        close_days = int(import_cfg.get("grants_gov_close_days") or 90)
        nonprofit_filter = bool(import_cfg.get("grants_gov_nonprofit_filter", True))

        org = load_org_profile()

        ctx.progress_cb(self.name, {"current_action": "applying org-profile pre-filter"})
        result = filter_opportunities(
            sb,
            org,
            close_days=close_days,
            nonprofit_filter=nonprofit_filter,
            limit=ctx.max_per_source,
        )
        emit_telemetry(ctx.progress_cb, self.name, result.telemetry)
        rows = result.rows

        try:
            processed = get_processed_urls()
        except Exception:
            processed = set()

        # Pre-fetch CFDA enrichment in bulk: collect distinct cfda_numbers and
        # one round-trip to sam_cfda_listings. Costs nothing when the table is
        # empty (Phase 1 deferred), so this is safe today.
        cfda_numbers = sorted({r.get("cfda_number") for r in rows if r.get("cfda_number")})
        cfda_lookup: Dict[str, Dict[str, Any]] = {}
        if cfda_numbers:
            try:
                cfda_rows = (
                    sb.table("sam_cfda_listings")
                    .select(
                        "program_number, program_title, federal_agency, objectives, "
                        "applicant_eligibility, range_and_average_assistance, "
                        "examples_of_funded_projects, website_address"
                    )
                    .in_("program_number", cfda_numbers)
                    .execute()
                    .data
                    or []
                )
                cfda_lookup = {row["program_number"]: row for row in cfda_rows}
                if cfda_lookup:
                    ctx.progress_cb(self.name, {
                        "current_action": f"CFDA enrichment: matched {len(cfda_lookup)} programs",
                    })
            except Exception as exc:
                # Table absent or query failed — discovery continues without enrichment.
                logger.debug("GrantsGovDBSource: CFDA lookup skipped: %s", exc)

        count = 0
        for row in rows:
            if ctx.cancelled():
                return
            url = row.get("url")
            if not url or url in processed:
                continue

            documents: List[DocumentRef] = []
            cfda_no = row.get("cfda_number")
            program = cfda_lookup.get(cfda_no) if cfda_no else None
            if program:
                # Inject CFDA program context as a "document" with prefetched_text;
                # the document fetcher will run the LLM doc-extractor on this and
                # the scrape_worker will append the summary to the page context.
                lines = [
                    f"=== CFDA Program Context: {program.get('program_title','')} ({cfda_no}) ===",
                ]
                if program.get("federal_agency"):
                    lines.append(f"Federal Agency: {program['federal_agency']}")
                if program.get("objectives"):
                    lines.append(f"Objectives: {program['objectives']}")
                if program.get("applicant_eligibility"):
                    lines.append(f"Applicant Eligibility: {program['applicant_eligibility']}")
                if program.get("range_and_average_assistance"):
                    lines.append(f"Range and Average of Financial Assistance: {program['range_and_average_assistance']}")
                if program.get("examples_of_funded_projects"):
                    lines.append(f"Examples of Funded Projects: {program['examples_of_funded_projects']}")
                if program.get("website_address"):
                    lines.append(f"Program website: {program['website_address']}")
                documents.append(DocumentRef(
                    url=f"sam_cfda://{cfda_no}",
                    kind="rfp",
                    source_url=url,
                    extra={"source": self.name, "cfda_number": cfda_no},
                    prefetched_text="\n".join(lines),
                ))

            yield SourceResult(
                url=url,
                funder_name=row.get("title") or row.get("agency"),
                source_metadata={
                    "source": self.name,
                    "opportunity_id": row.get("opportunity_id"),
                    "title": row.get("title"),
                    "agency": row.get("agency"),
                    "agency_code": row.get("agency_code"),
                    "close_date": row.get("close_date"),
                    "award_ceiling": row.get("award_ceiling"),
                    "cfda_number": cfda_no,
                    "funding_instrument_type": row.get("funding_instrument_type"),
                    "cost_sharing_required": row.get("cost_sharing_or_matching_required"),
                },
                documents=documents,
            )
            count += 1
            if count >= ctx.max_per_source:
                break

        ctx.progress_cb(self.name, {"urls_found": count})

    def close_state(self) -> Dict[str, Any]:
        return self._new_state
