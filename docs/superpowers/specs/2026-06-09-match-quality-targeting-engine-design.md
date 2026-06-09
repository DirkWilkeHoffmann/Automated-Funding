# Match-Quality & Targeting Engine — Process Plan

**Date:** 2026-06-09
**Branch base:** `feature/auto-discovery`
**Status:** Approved design → ready for implementation planning
**Scope:** Sub-project A of the larger "multi-tenant funding-discovery SaaS" effort (B = multi-tenancy substrate, C = client experience — both deferred).

---

## 0. Read this first (orientation for any agent)

This plan changes **how Auto Discovery chooses what to scrape**. It does **not** change the LLM extraction or eligibility scoring that happens after scraping — that part already works correctly.

Before touching code, read these files to understand the current pipeline:

| File | What it does |
|------|--------------|
| `utils/discovery/orchestrator.py` | `run_discovery()` — the conductor. Builds sources, runs them in parallel, dedups, spawns a scrape job. |
| `utils/discovery/prefilter.py` | `OrgProfile`, `filter_funders()`, `filter_opportunities()` — org-profile DB filtering (only used by 2 sources today). |
| `utils/discovery/sources/registry.py` | All source adapters. `ProPublicaSource` and `IRS_BMF_Source` contain the foundation flow + the foundation gate. |
| `utils/discovery/foundation_crawler.py` | `find_grants_page()`, `is_invitation_only()` — the existing (HTTP-only) grant-page detector. |
| `utils/discovery/document_fetcher.py` | `fetch_documents()` — downloads + LLM-extracts 990s/RFPs into the `documents` table. |
| `utils/discovery/sources/irs_990_parser.py` | `xml_to_narrative()`, `extract_website_from_xml()` — 990 XML parsing. |
| `utils/scrape_worker.py` | `process_single_fund()`, `start_background_scrape()` — the scrape job. |
| `utils/llm_utils.py` | `call_llm_extract()` (2-stage), `_tier_from_rubric()`. Models: `_MODEL_FAST="gpt-4o"`, `_MODEL_FULL="gpt-4.1"`. **DO NOT CHANGE the scoring.** |
| `utils/scraping.py` | `fetch_page()` (HTTP), `playwright_fetch()` (JS — coded but browser not installed), `prioritized_crawl()`. |
| `utils/db/pending_urls_store.py` | The "maybe bucket" store — `upsert_pending_urls()`, `list_pending()`, `approve_batch()`. Built, but discovery does not write to it yet. |
| `config/schema.sql` | All table definitions. Migrations live in `config/migration_phase*.sql`. |

**Deployment constraints (hard):** Backend runs on Azure Container Apps at **0.5 vCPU / 1 GiB RAM** (`containerapp-backup.yaml`), Docker image from `Dockerfile`. Headless Chromium must be **concurrency-capped** or it will OOM. Supabase (Postgres) is the only datastore.

---

## 1. Problem statement

Auto Discovery is **supply-driven**: it sweeps broad sources (rotating 5 US states per run, pulling whole federal datasets), then applies an org-profile filter to only **2 of ~8 sources**. The result of a real run: 223 URLs found, 88 sent to scrape, **0 scored Eligible/Highly Eligible** — because the scrape budget is spent on funders that are genuinely irrelevant to the org (wrong cause/geography/type). The scoring is correct; the *inputs* are wrong.

The business need: this is becoming a **multi-tenant service**. When a client (e.g. a children's charity) signs, every run must surface **Eligible / Highly Eligible** funders matched to *that client's* mission and geography.

## 2. Goal

Make discovery **demand-driven**: each client's mission drives a **vector search** over a **funder knowledge base** enriched with each funder's *actual past giving*, ranks candidates by match quality, and spends the scrape budget on the best-predicted matches first. Designed **profile-parameterized** so it generalizes to multi-tenancy (Sub-project B) without rework.

### Success criteria
1. A run for a given org profile returns a ranked list where the top candidates are topically + geographically matched to the org.
2. At least some candidates per run reach **Eligible / Highly Eligible** after scraping (assuming the funder pool for that cause/geo is non-empty).
3. "Highly Eligible" verdicts cite **past-grantee evidence** ("funded 3 similar youth organisations").
4. The expensive scrape runs only on gate-approved, high-predicted-match candidates; borderline ones land in `pending_urls` for human review.
5. JS-heavy funder sites render instead of silently failing.
6. All new logic accepts a **profile object as a parameter** (no hardcoded single-org reads in the new modules).

### Non-goals (explicitly out of scope for Sub-project A)
- Multi-tenant auth, per-client `org_id` data scoping, RLS (that's Sub-project B).
- Client-facing dashboards / notifications (Sub-project C).
- Changing the 2-stage LLM extraction or the 8-dimension rubric in `llm_utils.py`.
- Replacing the existing source adapters or importers (they are reused).

---

## 3. Target architecture

```
                    ┌──────────────────────────────────────────────────────┐
                    │  CLIENT TARGETING PROFILE (per org)                    │
                    │  mission → AI-suggested NTEE/CFDA/keywords → confirm   │
                    │  → cached client embedding vector                      │
                    └───────────────────────────┬──────────────────────────┘
                                                 │ client vector
                                                 ▼
  FUNDER KNOWLEDGE BASE                  ┌─────────────────────┐
  discovery_funders + 990 enrichment ──► │ 1. VECTOR SEARCH     │  cheap, ranks pool
  (program_areas, grantees, embedding)   │   top-K, geo-filtered │
  grant_opportunities + embedding        │   + cursor rotation   │
                                         └──────────┬───────────┘
                                                    │ ranked candidates + match score
                                                    ▼
                                         ┌─────────────────────┐
                                         │ 2. LLM RERANK        │  cheap LLM, "why it matches"
                                         │   + past-grantee      │  + Highly-Eligible signal
                                         │     evidence          │
                                         └──────────┬───────────┘
                                                    ▼
                                         ┌─────────────────────┐
                                         │ 3. RELEVANCE GATE    │  hard rules → sitemap map →
                                         │   3-lane router       │  grant-page verify (Playwright capped)
                                         └───┬─────────┬────────┘
                                  scrape lane │  pending │ drop (logged)
                                             ▼         ▼
                              prioritized scrape   pending_urls (review UI)
                              (best match first)
                                             ▼
                              EXISTING 2-stage LLM extraction + rubric  ── UNCHANGED
                                             ▼
                                          funds table → /results
```

The funnel is **cheap → expensive**: vector search (≈free) ranks the whole pool, a cheap LLM reranks only the top slice, and the expensive crawl+scrape+extract runs only on gate survivors.

---

## 4. Data model changes

All changes go in a new migration file: `config/migration_phase11_targeting_engine.sql`. Mirror the existing migration style (idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`). Also reflect them into `config/schema.sql`.

### 4.1 Enable pgvector
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```
> Verify Supabase project allows the `vector` extension (Dashboard → Database → Extensions). If a dimension is needed, use **1536** (`text-embedding-3-small`).

### 4.2 Funder knowledge base enrichment (`discovery_funders`)
```sql
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS program_areas      TEXT[];
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS top_grantees       JSONB;   -- [{name, amount, purpose}]
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS grantee_purposes   TEXT;    -- concatenated purpose text for embedding
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS embedding          vector(1536);
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS enriched_at        TIMESTAMPTZ;  -- 990 parsed + fields set
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS embedded_at        TIMESTAMPTZ;  -- embedding computed
```
Index for vector search (HNSW or IVFFlat — HNSW preferred for recall):
```sql
CREATE INDEX IF NOT EXISTS discovery_funders_embedding_idx
  ON discovery_funders USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS discovery_funders_enrich_queue_idx
  ON discovery_funders (enriched_at) WHERE enriched_at IS NULL;
```

### 4.3 Federal opportunity embeddings (`grant_opportunities`)
```sql
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS embedding   vector(1536);
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS grant_opportunities_embedding_idx
  ON grant_opportunities USING hnsw (embedding vector_cosine_ops);
```

### 4.4 Client targeting profile (`organizations`)
`mission`, `services`, `ntee_codes`, `service_states`, `cfda_categories`, `applicant_types`, grant-size already exist (added in earlier phases). Add:
```sql
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cause_keywords       TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS targeting_confirmed  BOOLEAN DEFAULT FALSE;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS client_embedding     vector(1536);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS targeting_updated_at TIMESTAMPTZ;
```

### 4.5 Targeting run cursor (rotation state)
Store the "where did we get to in the ranked list" cursor per org in the existing `discovery_state` JSONB (see `config_store.load_discovery_state`/`save_discovery_state`) under a `targeting` key — no new table needed. Shape:
```json
{ "targeting": { "<org_id_or_'default'>": { "funder_offset": 120, "opp_offset": 40, "geo_broaden_level": 0 } } }
```

### 4.6 `pending_urls` (already exists — minor additions)
```sql
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS funder_name      TEXT;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS discovery_source TEXT;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS match_score      REAL;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS match_reason     TEXT;
```

---

## 5. New / changed modules

| Module | New? | Responsibility |
|--------|------|----------------|
| `utils/discovery/embeddings.py` | NEW | Thin wrapper around OpenAI `text-embedding-3-small`. `embed_text(str) -> list[float]`, `embed_batch(list[str])`. Reads key the same way `llm_utils` does (api_tokens → env). Caps batch size; retries. |
| `utils/discovery/funder_enrichment.py` | NEW | Background job: pick unenriched `discovery_funders` rows in target geographies, look up 990 via `irs_990_index`, parse with `irs_990_parser`, persist `program_areas`/`top_grantees`/`grantee_purposes`, then embed and set `embedded_at`. Runs on a cron (added to `scheduler.py`). |
| `utils/discovery/targeting.py` | NEW | `derive_targeting(mission, website?, ein?) -> TargetingSuggestion` (LLM-suggests NTEE/CFDA/keywords). `build_client_embedding(profile) -> vector`. `retrieve_candidates(profile, cursor, limit) -> list[Candidate]` (pgvector search + geo filter + rotation + graceful broadening). |
| `utils/discovery/rerank.py` | NEW | `rerank_and_explain(profile, candidates) -> list[ScoredCandidate]`. Cheap LLM (`gpt-4o`/mini) confirms match, writes `match_reason`, flags past-grantee overlap → `predicted_tier` hint. |
| `utils/discovery/relevance_gate.py` | NEW | `gate(candidate, profile) -> Lane` where Lane ∈ {SCRAPE, PENDING, DROP}. Stage 1 hard rules (reuse `prefilter` predicates), Stage 2 sitemap map, Stage 3 grant-page verify. |
| `utils/discovery/sitemap_map.py` | NEW | `find_funding_urls(homepage) -> list[ranked_url]`. Fetch `/robots.txt` → sitemaps, fetch `/sitemap.xml`, keyword-rank URLs for grant/apply/funding intent. Pure HTTP+XML, no browser. |
| `utils/discovery/foundation_crawler.py` | CHANGE | `find_grants_page()` gains: (1) try `sitemap_map` first, (2) use a JS-capable fetch (Playwright, capped) when HTTP yields too little. Keep existing keyword scorer + LLM fallback. |
| `utils/scraping.py` | CHANGE | Add a global Playwright semaphore (cap 1–2). Ensure `fetch_page` can opt into JS render. |
| `utils/discovery/orchestrator.py` | CHANGE | New targeted path: when targeting enabled, replace blind source rotation with `targeting.retrieve_candidates()` → `rerank` → `relevance_gate` → 3-lane routing. Prioritize scrape job by match score. Keep old path behind a config flag for fallback. |
| `Dockerfile` | CHANGE | Install Playwright Chromium + system deps. |
| `api/routes/discovery.py` + admin UI | CHANGE | Onboarding endpoint: `POST /discovery/targeting/derive` (mission → suggestions), `PUT /discovery/targeting` (confirm). Surface in `frontend/app/admin/discovery`. |

---

## 6. Implementation phases

Each phase is independently shippable and has explicit acceptance criteria. Build in order; later phases depend on earlier ones. Put the whole effort behind a config flag `discovery_config.targeting_enabled` (default FALSE) so the existing pipeline keeps working until the new path is proven.

### Phase 0 — Infra prerequisites *(no behavior change; unblocks everything)*
**Do:**
1. `Dockerfile`: after `pip install`, add `RUN playwright install --with-deps chromium`. Verify the slim image gets the required apt libs (Playwright's `--with-deps` handles most; on `python:3.11-slim` you may need `apt-get install -y` for fonts/libnss3/libatk etc. — test the built image).
2. `utils/scraping.py`: add a module-level `threading.BoundedSemaphore(int(os.getenv("PLAYWRIGHT_MAX_CONCURRENCY", "1")))`; wrap `playwright_fetch` body in `with _PW_SEM:`.
3. Enable `vector` extension in Supabase; run a no-op `SELECT '[1,2,3]'::vector;` to confirm.
4. Add `text-embedding-3-small` usage path; confirm the OpenAI key resolution works for embeddings.

**Acceptance:** built Docker image can launch headless Chromium (add a one-off test route or script `scripts/check_playwright.py`); `SELECT` against a `vector` column works; a unit test embeds a string and gets a 1536-float vector.

**Risk/watch:** image size grows ~300–400 MB; Container App cold start slower. Acceptable.

---

### Phase 1 — Funder knowledge base enrichment
**Goal:** populate `program_areas`, `top_grantees`, `grantee_purposes` on `discovery_funders` from 990s.

**Do:**
1. Apply migration 4.1–4.2.
2. Create `utils/discovery/funder_enrichment.py`:
   - `select_enrichment_batch(limit, states)` — `discovery_funders WHERE enriched_at IS NULL` (optionally filtered to states the configured org(s) serve), ordered by `asset_amount DESC`.
   - For each: `irs_990_index` lookup → `irs_990_zips.fetch_multiple_xmls` (reuse existing batching) → `irs_990_parser.xml_to_narrative` + a 990 grant-signal extract (reuse `document_fetcher`'s `_FORM_990_USER_PROMPT` logic to get `program_areas`, `top_grantees`).
   - Persist fields; set `enriched_at`.
3. Build `grantee_purposes` as the concatenation of grantee `purpose` strings + `program_areas` (this is the text we embed in Phase 2).
4. Add a cron `funder_enrichment` to `utils/discovery/scheduler.py` (follow the existing 5-job pattern; default e.g. nightly, batch-capped).

**Acceptance:** running the job on a small state populates the new columns for N funders; idempotent (re-run skips `enriched_at IS NOT NULL`); failures are logged and skip, never crash the batch.

**Note (cold-start):** enrichment is progressive and **geo-scoped to the org(s) you actually have** — do not attempt to enrich all 1M rows. Embed-from-available in Phase 2 so funders are usable before full 990 enrichment completes.

---

### Phase 2 — Embeddings
**Goal:** every relevant funder + opportunity has an embedding; vector search is possible.

**Do:**
1. Create `utils/discovery/embeddings.py` (`embed_text`, `embed_batch`, key resolution, retry/backoff, batch cap ~100).
2. Extend `funder_enrichment.py`: after enrichment, embed `grantee_purposes || program_areas || name || ntee_label`; set `embedding`, `embedded_at`. For funders without a 990, embed `name || ntee_label || city/state` so they are still searchable (lower-signal).
3. Add an opportunity-embedding pass (can live in `funder_enrichment.py` or a sibling): embed `title || description || eligibility_text` for `grant_opportunities WHERE embedded_at IS NULL`.
4. Migration 4.3 indexes.

**Acceptance:** a SQL `ORDER BY embedding <=> '<vec>'::vector LIMIT 10` returns sensible nearest funders; embedding columns populate incrementally; cost per 1k embeddings is logged.

---

### Phase 3 — Client targeting profile (hybrid onboarding)
**Goal:** operator pastes a mission, gets AI-suggested targeting, confirms; a client embedding is cached.

**Do:**
1. Migration 4.4.
2. `utils/discovery/targeting.py`:
   - `derive_targeting(mission, website=None, ein=None)` → LLM (`gpt-4o`) returns suggested `ntee_prefixes`, `cfda_categories`, `cause_keywords`, `applicant_codes`. If `ein` given, enrich from the org's own BMF row.
   - `build_client_embedding(profile)` → embed `mission || cause_keywords || services`.
3. API (`api/routes/discovery.py`): `POST /discovery/targeting/derive` (returns suggestions, no write), `PUT /discovery/targeting` (persists confirmed fields, sets `targeting_confirmed=TRUE`, recomputes `client_embedding`, sets `targeting_updated_at`).
4. Admin UI (`frontend/app/admin/discovery`): a "Targeting" panel — paste mission → show suggestions → edit chips → Save.
5. Define a single source-of-truth `TargetingProfile` dataclass (extend `prefilter.OrgProfile` or wrap it) that **carries an org identity + embedding** and is passed into all new functions. This is the multi-tenant seam.

**Acceptance:** pasting a children's-charity mission yields youth/education NTEE prefixes (P, O, B*) and relevant keywords; confirming writes the row + a non-null `client_embedding`; the profile object is the only input the targeting query needs.

---

### Phase 4 — Targeting query engine
**Goal:** given a profile, return a ranked candidate list, fresh each run.

**Do:** in `utils/discovery/targeting.py`:
- `retrieve_candidates(profile, cursor, limit)`:
  1. Vector search `discovery_funders` by `client_embedding`, **filtered server-side** by `state IN profile.effective_states()`, asset window, `scraped_at IS NULL`.
  2. Apply `funder_offset` from cursor (rotation) → return the next `limit` slice.
  3. **Graceful broadening:** if fewer than `limit` remain at the tight filter, increment `geo_broaden_level` (add adjacent states / drop the geo filter / widen NTEE) and re-query.
  4. Parallel: vector search `grant_opportunities` for federal matches.
- Persist the updated cursor via `save_discovery_state` (section 4.5).

**Acceptance:** two consecutive runs for the same profile return **different** candidates (rotation works); a niche cause still returns candidates via broadening; geo filter is honored.

---

### Phase 5 — Pre-scrape match score & prioritization
**Goal:** scrape the best-predicted matches first within the run budget.

**Do:**
1. Define `match_score` = blend of cosine similarity + structured boosts (NTEE exact match, grantee-purpose keyword overlap, asset-size fit). Pure function, unit-tested.
2. Attach `match_score` to each candidate; sort descending.
3. When spawning the scrape job (`job_store.create`), pass candidates **in ranked order** and ensure `process_single_fund` ordering / the job's URL list preserves priority (the worker already pulls from the list — keep it ordered).

**Acceptance:** given a candidate set, the scrape order matches descending `match_score`; capping the run at K scrapes the top-K.

---

### Phase 6 — Rerank + relevance gate (the funnel)
**Goal:** confirm matches cheaply, verify a real funding pathway, route into 3 lanes.

**Do:**
1. `utils/discovery/rerank.py`: `rerank_and_explain(profile, top_candidates)` — one cheap LLM call per candidate (or batched) using the funder's `program_areas` + `top_grantees` + the client mission → `{match_confirmed, match_reason, past_grantee_overlap, predicted_tier}`. Past-grantee overlap is the **Highly Eligible** signal; `match_reason` is stored for the UI.
2. `utils/discovery/sitemap_map.py`: `find_funding_urls(homepage)` — robots.txt → sitemaps → `/sitemap.xml`; keyword-rank URLs with the `foundation_crawler._GRANT_PAGE_PATTERNS` regex. Return ranked funding URLs (empty list = no pathway).
3. `utils/discovery/foundation_crawler.py`: `find_grants_page()` calls `sitemap_map` first; falls back to homepage link-scan; uses capped Playwright fetch when HTTP returns thin content; keeps LLM fallback.
4. `utils/discovery/relevance_gate.py`: `gate(candidate, profile) -> Lane`:
   - **Stage 1 hard rules** (free): reuse `prefilter` predicates — wrong state, CFDA category not in set, applicant-code exclusion, closed deadline → `DROP`.
   - **Stage 2 sitemap/grant-page**: no funding pathway found → `DROP`.
   - **Stage 3 routing**: strong match + verified grants page → `SCRAPE`; verified-but-ambiguous or rerank `match_confirmed=false but plausible` → `PENDING`; else `DROP`.
5. Write `PENDING` candidates via `pending_urls_store.upsert_pending_urls` with `funder_name`, `discovery_source`, `match_score`, `match_reason`.
6. Log every `DROP` with its reason into the existing progress telemetry (`emit_telemetry` / progress `current_action`) so the funnel is visible in the UI.

**Acceptance:** for a set of candidates, hard mismatches drop for free; funders with no sitemap/grants page drop; borderline ones appear in the pending-review UI with a reason; only strong matches reach the scrape lane.

---

### Phase 7 — Orchestrator integration
**Goal:** wire the new path into `run_discovery()` behind the flag.

**Do:**
1. In `orchestrator.run_discovery()`, when `config.targeting_enabled`:
   - Load the `TargetingProfile`.
   - `candidates = retrieve_candidates(profile, cursor, limit)`.
   - `scored = rerank_and_explain(profile, candidates)`.
   - For each: `lane = gate(candidate, profile)` → route to scrape list / pending / drop.
   - Spawn scrape job with the ranked scrape list (Phase 5 ordering).
   - Update cursor; snapshot progress as today.
2. Keep the existing source-rotation path when the flag is off (no regression).
3. Reuse `ProPublicaSource`/`IRS_BMF_Source` 990 + website-resolution helpers where useful, but the *selection* of which funders to process now comes from the targeting query, not blind rotation.

**Acceptance:** with the flag on, a run produces a ranked, gated scrape list + pending entries + drop telemetry; with the flag off, behavior is unchanged.

---

### Phase 8 — Multi-tenant readiness seam *(light, no tenancy yet)*
**Goal:** ensure nothing new hardcodes the single org.

**Do:**
1. Audit the new modules: every function takes a `TargetingProfile` parameter; no `.limit(1)` org reads inside `targeting.py`/`rerank.py`/`relevance_gate.py`.
2. The cursor (4.5) is already keyed by org id (use `'default'` for the single org today).
3. Document in the spec how Sub-project B will: add `org_id` to `funds`/`discovery_runs`/`pending_urls`, loop `run_discovery` over confirmed profiles, and scope results.

**Acceptance:** a code review confirms the new path would work for an arbitrary profile passed in; a second fake profile run targets different funders.

---

## 7. Testing strategy

- **Unit:** `match_score` blend; `sitemap_map` URL ranking; `relevance_gate` lane decisions (table-driven: each rule → expected lane); `derive_targeting` JSON parsing; embedding wrapper shape/retry.
- **Integration (mocked external):** `retrieve_candidates` against a seeded test set of `discovery_funders` with known embeddings → asserts ordering, geo filter, rotation across two calls, broadening.
- **Pipeline (graceful degradation):** run the orchestrator targeted path with the LLM + embeddings mocked → asserts 3-lane routing and that `pending_urls` receives borderline rows.
- **Manual smoke:** enable the flag on the real single org (a children's charity profile), run once, inspect `/results` for Eligible/Highly Eligible with grantee evidence, and the pending page for the maybe bucket.
- Follow the repo's existing pytest layout (`tests/`); do not add tests to root.

---

## 8. Rollout

1. Ship Phases 0–2 (infra + KB + embeddings) — no user-visible behavior change; enrichment runs in the background.
2. Ship Phase 3 (onboarding UI) — operator can define targeting, still no run change.
3. Ship Phases 4–7 behind `targeting_enabled=FALSE`. Enable for the single org, validate against success criteria (§2).
4. Once validated, flip default to TRUE; keep the legacy path one release for fallback, then remove.

---

## 9. Risks & open questions

| Risk | Mitigation |
|------|-----------|
| Playwright OOM on 1 GiB | Sitemap-first means rendering is rare; semaphore cap 1; consider bumping Container App to 1 vCPU / 2 GiB if render volume is high. |
| Funder pool runs dry for niche causes | Graceful broadening (Phase 4); federal opportunities as a second stream; pending bucket keeps borderline visible. |
| 990 enrichment coverage is slow / incomplete | Embed-from-available so funders are usable pre-enrichment; prioritize enrichment by client geography. |
| Embedding/LLM cost at scale | Vector search is ~free; LLM only reranks the top slice + gates survivors; cap top-K per run. |
| pgvector not enabled on the Supabase plan | Verify in Phase 0 before building Phase 2; fallback = compute similarity in Python over a capped candidate set (slower, last resort). |

**Open questions to confirm during implementation:**
1. Exact `match_score` weighting (similarity vs structured boosts) — tune empirically in Phase 5.
2. Cron cadence + per-run batch caps for `funder_enrichment`.
3. Whether to embed grantee *names* (requires resolving grantees to their own NTEE) or only grantee *purposes* (cheaper, text-only) — start with purposes.

---

## 10. File-change checklist (quick reference)

- [ ] `Dockerfile` — install Chromium
- [ ] `config/migration_phase11_targeting_engine.sql` + `config/schema.sql` — all schema in §4
- [ ] `utils/discovery/embeddings.py` (NEW)
- [ ] `utils/discovery/funder_enrichment.py` (NEW) + scheduler cron
- [ ] `utils/discovery/targeting.py` (NEW)
- [ ] `utils/discovery/rerank.py` (NEW)
- [ ] `utils/discovery/relevance_gate.py` (NEW)
- [ ] `utils/discovery/sitemap_map.py` (NEW)
- [ ] `utils/discovery/foundation_crawler.py` (CHANGE — sitemap + JS)
- [ ] `utils/scraping.py` (CHANGE — Playwright semaphore)
- [ ] `utils/discovery/orchestrator.py` (CHANGE — targeted path behind flag)
- [ ] `utils/discovery/scheduler.py` (CHANGE — enrichment cron)
- [ ] `api/routes/discovery.py` (CHANGE — targeting endpoints)
- [ ] `frontend/app/admin/discovery` (CHANGE — targeting panel + pending review already exists)
- [ ] `tests/` — unit + integration per §7
- [ ] Keep `utils/llm_utils.py` scoring **unchanged**
```
