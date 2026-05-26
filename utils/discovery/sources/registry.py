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
from typing import Any, Dict, Iterator, List, Optional

from utils.discovery.sources.base import DocumentRef, SourceContext, SourceResult

logger = logging.getLogger(__name__)


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
            try:
                xml_by_object_id = fetch_multiple_xmls(
                    (r["object_id"], r["batch_zip"], int(r["submission_year"]))
                    for r in ein_to_filing.values()
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

        # Pass 3: yield SourceResults with the richest available document.
        # Use the resolved actual website; fall back to ProPublica URL only when
        # a 990 document is attached (the 990 context makes the scrape worthwhile).
        # Skip entirely when only a ProPublica profile URL is available with no 990.
        urls_yielded = 0
        skipped_no_site = 0
        resolved_urls: set = set()
        for item in collected:
            if ctx.cancelled():
                return
            org = item["org"]
            ein = str(org.get("ein") or "").strip()

            documents: List[DocumentRef] = []
            filing_rec = ein_to_filing.get(ein)
            xml_text = xml_by_object_id.get(filing_rec["object_id"]) if filing_rec else None

            if xml_text:
                narrative = xml_to_narrative(xml_text)
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

            # Determine the URL to yield
            resolved = ein_to_website.get(ein, "")
            if resolved and resolved not in resolved_urls:
                url = resolved
            elif not resolved:
                if not documents:
                    # No real website AND no 990 context → skip (PropPublica profile is useless)
                    skipped_no_site += 1
                    continue
                # Have 990 context but no site → use PropPublica URL as anchor; 990 compensates
                url = item["url"]
            else:
                # resolved URL already yielded (duplicate across states) → skip
                continue

            resolved_urls.add(url)
            urls_yielded += 1
            yield SourceResult(
                url=url,
                funder_name=org.get("name", ""),
                source_metadata={
                    "source": self.name,
                    "state": item["state"],
                    "ein": ein,
                },
                documents=documents,
            )

        ctx.progress_cb(self.name, {
            "current_action": (
                f"done ({urls_yielded} URLs yielded, {skipped_no_site} skipped — no website found, "
                f"{sum(1 for it in collected if ein_to_filing.get(str(it['org'].get('ein') or '').strip()))} 990 lookups)"
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


# ── Web search ────────────────────────────────────────────────────────────────


class WebSearchSource:
    name = "web_search"

    def __init__(self, brave_api_key: Optional[str], org_state: Optional[str]) -> None:
        self._brave_api_key = brave_api_key
        self._org_state = org_state
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from utils.discovery.sources.web_search import search_web_for_grants

        query_idx = int(ctx.state.get("query_idx", 0))
        next_idx = (query_idx + 1) % 5
        today = datetime.now(timezone.utc).date().isoformat()

        ctx.progress_cb(self.name, {"current_action": f"querying (query #{query_idx})"})
        try:
            urls, next_idx = search_web_for_grants(
                keywords=ctx.keywords,
                brave_api_key=self._brave_api_key,
                query_idx=query_idx,
                org_state=self._org_state,
            )
            for url in urls:
                if ctx.cancelled():
                    return
                yield SourceResult(
                    url=url,
                    source_metadata={"source": self.name, "query_idx": query_idx},
                )
        except Exception as exc:
            logger.warning("Web search failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"failed: {exc}"})

        self._new_state = {"query_idx": next_idx, "last_run_date": today}

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


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


# ── USAspending.gov (Phase 3 — replaces defunct PND) ────────────────────────


class USAspendingSource:
    """USAspending.gov — federal awards spending API.

    Pulls recent grant-type awards to surface federal funders that are actively
    distributing money. Returns the recipient.recipient_url when present (the
    org's own website) or falls back to a USAspending recipient page URL.

    API docs: https://api.usaspending.gov/docs/endpoints
    """

    name = "usaspending"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        import requests

        today = datetime.now(timezone.utc).date()
        since_date = _lookback_since(ctx.state.get("last_run_date"), default_days=30)

        ctx.progress_cb(self.name, {"current_action": f"querying (since {since_date})"})

        # USAspending's `keywords` filter is OR-of-tokens treated as a phrase
        # by their backend — long auto-derived strings return 0 matches.
        # Use the keyword only if the operator gave us a short, focused term.
        kw = (ctx.keywords or "").strip()
        api_kws = [kw] if (kw and len(kw.split()) <= 2) else None

        body = {
            "filters": {
                "award_type_codes": ["02", "03", "04", "05"],  # grants & cooperative agreements
                "time_period": [{"start_date": since_date, "end_date": today.isoformat()}],
                "keywords": api_kws,
            },
            "fields": [
                "Award ID", "Recipient Name", "Awarding Agency",
                "Award Amount", "recipient_id", "generated_internal_id",
            ],
            "page": 1,
            "limit": min(ctx.max_per_source, 100),
            "sort": "Award Amount",
            "order": "desc",
        }
        # Drop None keys (API rejects null keywords)
        if body["filters"]["keywords"] is None:
            del body["filters"]["keywords"]

        try:
            resp = requests.post(
                "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                json=body,
                headers={"User-Agent": "automated-funding-bot/1.0", "Accept": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("USAspending API error: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"failed: {exc}"})
            self._new_state = {"last_run_date": today.isoformat()}
            return

        results = data.get("results") or []
        seen_recipients: set = set()
        for r in results:
            if ctx.cancelled():
                return
            recipient = (r.get("Recipient Name") or "").strip()
            if not recipient:
                continue
            key = recipient.lower()
            if key in seen_recipients:
                continue
            seen_recipients.add(key)

            # USAspending exposes a per-recipient detail page via generated_internal_id
            rec_id = r.get("generated_internal_id") or r.get("recipient_id")
            url = (
                f"https://www.usaspending.gov/recipient/{rec_id}/latest"
                if rec_id
                else f"https://www.usaspending.gov/search?keywords={recipient.replace(' ', '+')}"
            )
            yield SourceResult(
                url=url,
                funder_name=r.get("Awarding Agency") or "",
                source_metadata={
                    "source": self.name,
                    "recipient": recipient,
                    "award_amount": r.get("Award Amount"),
                },
            )

        self._new_state = {"last_run_date": today.isoformat()}

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


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


# ── Philanthropy News Digest (defunct as of 2026 — kept for compat) ──────────


class PhilanthropyDigestSource:
    name = "philanthropy_digest"

    def __init__(self) -> None:
        self._new_state: Dict[str, Any] = {}

    def fetch(self, ctx: SourceContext) -> Iterator[SourceResult]:
        from utils.discovery.sources.philanthropy_digest import fetch_pnd_grant_urls

        since_date = ctx.state.get("last_posted_from")
        today = datetime.now(timezone.utc).date().isoformat()

        ctx.progress_cb(self.name, {"current_action": f"fetching RSS (since {since_date or 'all'})"})
        try:
            urls = fetch_pnd_grant_urls(since_date=since_date)
            for url in urls[: ctx.max_per_source]:
                if ctx.cancelled():
                    return
                yield SourceResult(url=url, source_metadata={"source": self.name})
        except Exception as exc:
            logger.warning("PND RSS fetch failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"failed: {exc}"})

        self._new_state = {"last_posted_from": today}

    def close_state(self) -> Dict[str, Any]:
        return self._new_state


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
        states: List[str] = [s.upper() for s in (ctx.states or [])]

        ctx.progress_cb(self.name, {"current_action": "querying discovery_funders"})
        try:
            query = (
                sb.table("discovery_funders")
                .select("ein, name, city, state, website")
                .is_("scraped_at", "null")
                .gte("asset_code", min_asset_code)
            )
            if states:
                query = query.in_("state", states)
            rows = query.order("asset_code", desc=True).limit(batch_size * 3).execute().data or []
        except Exception as exc:
            logger.warning("IRS_BMF_Source: DB query failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"DB query failed: {exc}"})
            return

        if ntee_prefixes:
            rows = [
                r for r in rows
                if any((r.get("ntee_code") or "").startswith(p) for p in ntee_prefixes)
            ]

        batch = rows[:batch_size]
        if not batch:
            ctx.progress_cb(self.name, {"current_action": "no unscraped foundations found"})
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
        needs_990 = [r for r in batch if r["ein"] not in ein_to_website]
        if needs_990:
            ctx.progress_cb(self.name, {"current_action": f"looking up {len(needs_990)} EINs in IRS 990 index"})
            year_floor = datetime.now(timezone.utc).year - 3
            ein_to_filing: Dict[str, Dict[str, Any]] = {}
            try:
                for row in needs_990:
                    if ctx.cancelled():
                        break
                    ein = row["ein"]
                    filing_rows = (
                        sb.table("irs_990_index")
                        .select("object_id, batch_zip, submission_year, tax_year, return_type")
                        .eq("ein", ein)
                        .order("tax_year", desc=True)
                        .limit(1)
                        .execute()
                        .data or []
                    )
                    if filing_rows:
                        rec = filing_rows[0]
                        if int(rec.get("tax_year") or 0) >= year_floor:
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
                try:
                    xml_by_object_id = fetch_multiple_xmls(
                        (r["object_id"], r["batch_zip"], int(r["submission_year"]))
                        for r in ein_to_filing.values()
                    )
                except Exception as exc:
                    logger.warning("IRS_BMF_Source: 990 ZIP fetch failed: %s", exc)
                    xml_by_object_id = {}

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

        resolved_count = len(ein_to_website)
        ctx.progress_cb(self.name, {"current_action": f"yielding {resolved_count} URLs"})
        for row in batch:
            if ctx.cancelled():
                return
            website = ein_to_website.get(row["ein"])
            if not website:
                continue
            yield SourceResult(
                url=website,
                funder_name=row.get("name"),
                source_metadata={
                    "source": self.name,
                    "ein": row.get("ein"),
                    "city": row.get("city"),
                    "state": row.get("state"),
                },
            )

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

        _s = get_settings()
        sb = create_client(_s.supabase_url, _s.supabase_service_key)

        config = load_config()
        import_cfg = config.get("import_config") or {}
        close_days = int(import_cfg.get("grants_gov_close_days") or 90)

        today = datetime.now(timezone.utc).date()
        close_floor = today.isoformat()
        close_ceil = (today + timedelta(days=close_days)).isoformat()

        nonprofit_filter = bool(import_cfg.get("grants_gov_nonprofit_filter", True))
        _NONPROFIT_KEYWORDS = [
            "nonprofit", "non-profit", "501(c)(3)", "501(c)3",
            "community organization", "community-based organization",
            "charitable organization",
        ]

        ctx.progress_cb(self.name, {"current_action": "querying grant_opportunities"})
        try:
            rows = (
                sb.table("grant_opportunities")
                .select("opportunity_id, title, agency, url, close_date, eligibility_text")
                .gte("close_date", close_floor)
                .lte("close_date", close_ceil)
                .order("close_date")
                .limit(ctx.max_per_source * 4)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            logger.warning("GrantsGovDBSource: DB query failed: %s", exc)
            ctx.progress_cb(self.name, {"current_action": f"DB query failed: {exc}"})
            return

        if nonprofit_filter:
            def _is_nonprofit_eligible(row: Dict[str, Any]) -> bool:
                et = (row.get("eligibility_text") or "").lower()
                if not et:
                    return True  # No eligibility text — include; scraper will decide
                return any(kw in et for kw in _NONPROFIT_KEYWORDS)
            rows = [r for r in rows if _is_nonprofit_eligible(r)]

        try:
            processed = get_processed_urls()
        except Exception:
            processed = set()

        count = 0
        for row in rows:
            if ctx.cancelled():
                return
            url = row.get("url")
            if not url or url in processed:
                continue
            yield SourceResult(
                url=url,
                funder_name=row.get("title") or row.get("agency"),
                source_metadata={
                    "source": self.name,
                    "opportunity_id": row.get("opportunity_id"),
                    "title": row.get("title"),
                    "agency": row.get("agency"),
                    "close_date": row.get("close_date"),
                },
            )
            count += 1
            if count >= ctx.max_per_source:
                break

        ctx.progress_cb(self.name, {"urls_found": count})

    def close_state(self) -> Dict[str, Any]:
        return self._new_state
