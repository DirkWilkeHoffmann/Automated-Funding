# Smart Scrape + Two-Stage LLM Pipeline — Design Spec
**Date:** 2026-06-06
**Scope:** Content acquisition (A) + LLM extraction/evaluation (B). Discovery pipeline (C) is out of scope.

---

## Problem Statement

The current scraping and LLM extraction pipeline produces poor results for Work4ALiving (W4AL), a multinational workforce development nonprofit operating in 7 countries. The root failures are:

1. **Thin scrapes** — root domain URLs (e.g. `mergon.co.za`, `dell.org`) only retrieve homepage HTML (732–1100 chars) because the path-prefix crawl rule blocks all sub-pages when `seed_path = ""`. JS-rendered sites return skeleton HTML with no content.
2. **Template echo** — the LLM prompt uses W4AL's own data as JSON example values (`["501(c)(3) nonprofits", "workforce development organisations"]`). On thin pages, the model anchors on these examples and copies them verbatim into the extracted fund fields — the fund's applicant types end up showing W4AL's applicant types, not the fund's.
3. **Wrong eligibility tiers** — bad extracted fields produce bad rubric scores, which produce wrong eligibility tiers (A is downstream of B).
4. **Geography bugs** — "Africa" is not handled as a geographic term (should match W4AL's 5 African countries); multi-country fund scopes ("London, Northern Ireland, South Africa") return `partial` instead of `match` because residual non-South-Africa text is wrongly treated as a sub-region restriction.
5. **Listing pages processed as single funds** — `africanngos.org` (an article listing 30+ grants) is fed as one 242K-char blob to the LLM, producing garbage. `detect_listing_page` exists but is only wired to the manual scrape route, not `process_single_fund`.
6. **Junk sub-pages waste crawl slots** — comment pages (`/comment-page-1?replytocom=2949`) and social share variants (`?share=twitter`) pass the path-prefix filter and consume crawl budget with zero content.
7. **Phase 2 fires for Low Match** — expensive enrichment runs on funds already scored as weak.
8. **Evidence field contradicts eligibility** — Phase 2 uses Phase 1's raw evidence string (which may say "Eligible") even when the deterministic tier overrode to "Possibly Eligible".
9. **Fund name defaults to domain** — `fund_name` falls back to `urlparse(url).netloc`, producing "www2.fundsforngos.org" instead of the actual grant title.

---

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| JS rendering | Playwright fallback when BS4 < 150 words | Fixes thin scrapes without making every fetch slow |
| Root URL crawling | Allow depth-1 sub-pages with grant-related path keywords | Targeted, not unlimited — prevents sibling pollution |
| LLM architecture | Two-stage: extraction then evaluation | Separates concerns, eliminates template echo |
| Geography | Fix Python deterministic checker | Testable, predictable; LLM still extracts `geographic_scope` text |
| Listing pages | Detect → extract sub-URLs → user review | User approves before scraping; prevents junk auto-queuing |
| Discovery pipeline | Out of scope for this redesign | Discovery is working; scrape+eval quality is the problem |

---

## Architecture Overview

```
URL submitted (discovery or manual)
        │
        ▼
fetch_page (HTTP + BS4)
        │
word_count < 150?
  YES → playwright_fetch(url)    ← new Playwright fallback
        │
detect_listing_page(url, text)?
  YES → extract_listing_urls
        → write to pending_urls (status: awaiting_review)
        → return {skipped: "listing_page"}     ← no fund created
        │
  NO → prioritized_crawl (with fixes)
        │
        ▼
  ┌─────────────────────────────────┐
  │  STAGE 1 — FACT EXTRACTION      │
  │  Model: gpt-4o-mini (→ gpt-4o) │
  │  Input: fund page text ONLY     │
  │  No org profile in prompt       │
  │  Output: fund facts JSON        │
  └────────────┬────────────────────┘
               │
        Python geography check (fixed)
        Input: stage1.geographic_scope + org profile
        Output: geo_verdict {verdict, evidence}
               │
               ▼
  ┌─────────────────────────────────┐
  │  STAGE 2 — ELIGIBILITY EVAL     │
  │  Model: gpt-4o                  │
  │  Input: stage1 facts +          │
  │         org profile +           │
  │         geo_verdict             │
  │  Scores 7 rubric dimensions     │
  │  (geography pre-computed)       │
  │  Output: rubric, tier, evidence │
  └────────────┬────────────────────┘
               │
  Deterministic _tier_from_rubric
               │
  tier ∈ {Highly Eligible, Eligible, Possibly Eligible}?
    YES → Phase 2 enrichment (gpt-4o-mini)
    NO  → skip enrichment
               │
               ▼
        upsert_fund(merged result)
```

---

## Section A — Content Acquisition

### A1. Playwright Fallback

**New dependency:** `playwright` Python package + Chromium browser.
```bash
pip install playwright
playwright install chromium
```
Add `playwright` to `requirements.txt`.

**Trigger:** After `extract_visible_text(html)` yields fewer than 150 words.

**Implementation:**
- New function `playwright_fetch(url) -> Optional[str]` in `utils/scraping.py`
- Uses `playwright.sync_api` (or `asyncio` context with `async_playwright`)
- Launches Chromium in headless mode, navigates to URL, waits for `networkidle`, returns `page.content()`
- 30-second timeout; returns `None` on failure
- If Playwright returns content, re-run `extract_visible_text` on the result
- If Playwright fails, use the BS4 result as-is (even if thin) and log a warning

**Threshold:** 150 words (not chars) — chars are misleading because navigation/cookie boilerplate inflates raw char count.

### A2. Root URL Sub-Page Rule

**Current behaviour:** When `seed_path = ""` (root URL), `_is_sub_path` returns `True` only for the exact seed URL — all internal links are filtered out.

**New behaviour:** When `seed_path = ""`, also allow depth-1 sub-pages whose path contains a grant-relevant keyword:

```python
_GRANT_PATH_KEYWORDS = {
    "grant", "apply", "fund", "giving", "invest",
    "opportunity", "award", "support", "programme", "program",
}

def _is_sub_path(candidate_url: str) -> bool:
    if not seed_path:
        # Root URL — allow depth-1 pages with grant-relevant path keywords
        cand_path = urlparse(candidate_url).path.lower().strip("/")
        path_depth = len([p for p in cand_path.split("/") if p])
        if path_depth == 1 and any(kw in cand_path for kw in _GRANT_PATH_KEYWORDS):
            return True
        return candidate_url == seed_norm
    # ... existing sub-path logic unchanged
```

### A3. Junk URL Filter

Applied in `discover_links` before adding a URL to the crawl queue:

```python
_JUNK_PATTERNS = (
    "comment-page-", "replytocom=", "share=", "like=",
    "action=share", "ref=", "utm_", "#",
)

def _is_junk_url(url: str) -> bool:
    lower = url.lower()
    return any(p in lower for p in _JUNK_PATTERNS)
```

URLs matching any junk pattern are skipped entirely, never queued.

### A4. Listing Page Detection in `process_single_fund`

`detect_listing_page` is currently only called in `api/routes/scrape.py`. It must also be called in `process_single_fund` in `utils/scrape_worker.py`:

```python
# After combined_text is assembled, before Stage 1 LLM
from utils.scraping import detect_listing_page, extract_listing_urls

if detect_listing_page(url, combined_text):
    sub_urls = extract_listing_urls(url)
    if sub_urls:
        from utils.db.pending_urls_store import upsert_pending_urls
        upsert_pending_urls(sub_urls, source_url=url)
        log_message(f"Listing page detected: {len(sub_urls)} sub-URLs queued for review at {url}", "info")
    result["skipped"] = "listing_page"
    result["error"] = ""
    return result  # No fund row created; pending_urls written instead
```

### A5. Fund Name Extraction

`fund_name` currently defaults to `urlparse(url).netloc`. Priority order in `process_single_fund`:
1. `fund_name` parameter passed into the function (e.g., from Grants.gov DB pre-fetch — most accurate)
2. Stage 1 LLM extracted `fund_name` (if non-empty)
3. `urlparse(url).netloc` (last resort fallback only)

---

## Section B — Two-Stage LLM Pipeline

### B1. Stage 1 — Fact Extraction

**Model:** `gpt-4o-mini` → `gpt-4o` fallback if thin result (≥3 empty key fields)

**Input:** Fund page text only. No org profile.

**Output fields:**
- `fund_name` — name of the grant/fund (not the funder org)
- `funder_name` — who is offering the grant
- `geographic_scope` — full text description including region AND country names
- `applicant_types` — who is eligible to apply (list)
- `topic_areas` — what topics/sectors the fund supports (list)
- `beneficiaries` — intended beneficiaries (list)
- `funding_range` — dollar amounts if stated
- `deadline` — application deadline or "rolling" / "not stated"
- `application_status` — one of: open | closed | paused | rolling | seasonal | unclear
- `restrictions` — explicit eligibility exclusions (list)
- `grant_type` — federal | foundation | corporate | community | other
- `application_process` — how to apply (brief)
- `notes` — other relevant facts

**Prompt design rules:**
- No org profile text anywhere in the Stage 1 prompt
- JSON template example values are clearly fictional (e.g., `"Acme Community Foundation"`, `["registered charities"]`, `"United Kingdom"`) — no W4AL data
- Explicit instruction: "If a field does not appear in the text, use an empty string or empty array. Do NOT guess or infer."
- Explicit instruction: "Extract `geographic_scope` as completely as possible — include both region names AND country name when both appear."

### B2. Python Geography Check (Fixed)

The deterministic `_compute_geography_verdict` function is fixed for three bugs:

**Fix 1 — Continental terms:**
Add a `_CONTINENTAL` lookup mapping continent names to the set of W4AL's service_countries that fall within that continent. If the fund's `geographic_scope` contains a continental term and at least one org service_country is in that continent, return `match`.

```python
_CONTINENTAL_KEYWORDS = {
    "africa", "sub-saharan africa", "east africa", "southern africa",
    "west africa", "north africa", "latin america", "central america",
    "south america", "asia", "middle east", "europe",
}

_COUNTRY_CONTINENT = {
    # Africa — covers W4AL's African countries + common neighbours
    "south africa": "africa", "kenya": "africa", "namibia": "africa",
    "ethiopia": "africa", "nigeria": "africa", "ghana": "africa",
    "tanzania": "africa", "uganda": "africa", "zimbabwe": "africa",
    "mozambique": "africa", "zambia": "africa", "malawi": "africa",
    "botswana": "africa", "rwanda": "africa", "senegal": "africa",
    "cameroon": "africa", "angola": "africa", "egypt": "africa",
    # Latin America / Central America — covers W4AL's Americas countries
    "honduras": "latin america", "mexico": "latin america",
    "guatemala": "latin america", "el salvador": "latin america",
    "nicaragua": "latin america", "costa rica": "latin america",
    "panama": "latin america", "colombia": "latin america",
    "brazil": "latin america", "peru": "latin america",
    # North America
    "united states": "north america", "canada": "north america",
    # Asia
    "india": "asia", "cambodia": "asia", "bangladesh": "asia",
    "nepal": "asia", "philippines": "asia", "indonesia": "asia",
}
```

If `any(t in scope_lower for t in _CONTINENTAL_KEYWORDS)`:
- Find the continent term(s) in scope
- Check if any org service_country maps to that continent
- If yes → `match`; if no → `unknown`

**Fix 2 — Multi-country residual:**
After matching `matched_country` in the scope, check if the residual text (after stripping `matched_country` name) contains any words from the org's own sub-regions for that country. If not, the residual refers to other countries' regions — return `match`.

```python
# After stripping matched_country from scope_lower:
residual_words = set(re.split(r"[\s,.\-/()/]+", scope_residual.lower()))
org_region_words = set(
    word
    for region in org_regions
    for word in region.lower().split()
)
if not (residual_words & org_region_words):
    # Residual contains no words from org's SA regions → other-country text
    return {"verdict": "match", "evidence": f"Fund targets '{matched_country}' explicitly; other text in scope refers to other countries"}
```

**Fix 3 — Stale DB keys:**
Clean up `"SO"` and `"UN"` entries from `service_regions` in the DB (one-time migration). The code already filters them via `valid_country_names` but they should be removed from the source.

### B3. Stage 2 — Eligibility Evaluation

**Model:** `gpt-4o`

**Input:** Stage 1 facts (structured JSON) + full org profile + `geo_verdict` from Python checker

**Output:** `match_rubric` (7 dimensions), `eligibility` tier, `evidence` (one sentence)

**Rubric dimensions scored by Stage 2 (geography is pre-computed):**
`applicant_type`, `topic_focus`, `beneficiary`, `org_history`, `grant_size`, `cost_share`, `explicit_exclusion`

**International applicant type logic in Stage 2 prompt:**
```
The applicant org holds these registrations:
  - 501(c)(3): US federal nonprofit designation
  - NPO: South African Non-Profit Organisation registration

When evaluating applicant_type:
  - A fund open to "registered nonprofits", "501(c)(3)", "charities", "NGOs",
    "civil society organisations", or "NPOs" → this org qualifies.
  - Only score `mismatch` for hard exclusions: "for-profit entities only",
    "government agencies only", or explicit bars on foreign-registered orgs.
  - A locale-specific label (e.g., "South African NPO") does NOT by itself
    imply mismatch when the org's accreditations cover that locale.
```

**Prompt design:** Stage 2 receives Stage 1 facts as a structured block, not raw text. It is NOT asked to extract from the fund page. Its only job is scoring.

### B4. Phase 2 Enrichment

**Unchanged except:**
1. Remove `"Low Match"` from `PHASE2_PROMOTE_TIERS`. New value: `{"Highly Eligible", "Eligible", "Possibly Eligible"}`
2. Fix evidence contradiction in `_format_rich_evidence`: replace the Phase 1 verdict tier in the VERDICT line with the actual deterministic `tier` parameter passed to the function.

```python
# Before (buggy):
verdict_line = phase1_evidence.strip() or f"VERDICT: {tier}"
# Problem: phase1_evidence may say "Eligible" when tier is "Possibly Eligible"

# After (fixed):
# Use the deterministic tier; strip the tier label from phase1_evidence and
# keep only the reason clause (everything after " — ").
_reason = ""
if " — " in phase1_evidence:
    _reason = phase1_evidence.split(" — ", 1)[1].strip()
verdict_line = f"VERDICT: {tier}" + (f" — {_reason}" if _reason else "")
```

---

## Section C — Pending URLs Review

### C1. Database

```sql
CREATE TABLE pending_urls (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  url           text NOT NULL,
  title         text,
  source_url    text,
  status        text NOT NULL DEFAULT 'awaiting_review',
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  approved_by   uuid REFERENCES auth.users(id),
  scrape_job_id uuid REFERENCES scrape_jobs(id),
  CONSTRAINT pending_urls_status_check
    CHECK (status IN ('awaiting_review', 'approved', 'rejected', 'scraped'))
);

CREATE INDEX pending_urls_status_idx ON pending_urls(status);
```

### C2. Backend

New file: `utils/db/pending_urls_store.py`
- `upsert_pending_urls(items: list[dict], source_url: str)` — insert batch, skip duplicates by URL
- `list_pending(status="awaiting_review")` — return rows for admin panel
- `approve_batch(ids: list[str], user_id: str) -> list[str]` — mark approved, return URLs for scrape
- `reject_batch(ids: list[str])` — mark rejected

New endpoints in `api/routes/scrape.py` (or new `api/routes/pending.py`):
- `GET /admin/pending-urls` — list awaiting_review rows (superuser only)
- `POST /admin/pending-urls/approve` — body `{ids: [...]}`, triggers scrape job, marks `approved`/`scraped`
- `POST /admin/pending-urls/reject` — body `{ids: [...]}`, marks `rejected`

### C3. Frontend

New tab in `/admin`: **"Pending URLs"**

- Table: checkbox | URL + title | Source listing page | Created at
- [Select All] / [Reject Selected] / [Scrape Selected] actions
- Notification badge on Admin nav link when pending count > 0
- "Scrape Selected" calls `POST /admin/pending-urls/approve`, then triggers normal scrape job flow

---

## Section D — Error Handling

| Failure | Behaviour |
|---|---|
| Playwright fetch fails/times out | Use BS4 result, log warning, continue |
| Stage 1 thin result | Retry with gpt-4o; if still thin, persist what we have |
| Stage 2 fails entirely | Persist Stage 1 facts, set `eligibility: "unclear"`, log error |
| Geography check throws | Default `verdict: "unknown"`, log warning, continue |
| Phase 2 enrichment fails | Use Stage 2 evidence as-is (Phase 2 is additive) |
| Listing page false positive | URL goes to pending_urls; user can reject it |
| `pending_urls` write fails | Log warning, do not crash fund processing |

---

## Section E — Testing

### Unit Tests

**`tests/test_geography.py`** — `_compute_geography_verdict` with W4AL profile:

| Input scope | Expected verdict |
|---|---|
| `"Africa"` | `match` |
| `"East Africa"` | `match` |
| `"London, Northern Ireland, South Africa"` | `match` |
| `"Eastern Cape, South Africa"` | `match` |
| `"KwaZulu-Natal, South Africa"` | `partial` |
| `"United Kingdom"` | `unknown` |
| `"Global"` | `match` |
| `"Georgia, United States"` | `match` |
| `"Worldwide"` | `match` |
| `""` | `unknown` |

**`tests/test_tier_derivation.py`** — `_tier_from_rubric`:
- 8× match, 0× mismatch → `Highly Eligible`
- 3× match, 1× non-veto mismatch → `Eligible`
- 2× match, 0× mismatch → `Possibly Eligible`
- 1× match → `Low Match`
- 1× veto mismatch (geography) → `Not Eligible`

**`tests/test_scraping.py`** — crawl logic (mocked HTTP):
- BS4 < 150 words → Playwright called
- BS4 ≥ 150 words → Playwright not called
- Junk patterns (`?share=`, `comment-page-`) filtered from queue
- Root URL: `/grants` path allowed, `/about` path not allowed

**`tests/test_pipeline.py`** — integration with mocked LLM:
- Stage 1 prompt does NOT contain org profile text
- Stage 2 prompt DOES contain org profile text
- Stage 1 template example values contain no W4AL data
- Listing page detected → pending_urls written, no fund row created
- Stage 2 failure → fund row persisted with `eligibility: "unclear"`
- Phase 2 not called for `Low Match` tier

---

## Files Changed

| File | Change type |
|---|---|
| `utils/scraping.py` | Playwright fallback, junk filter, root URL keyword rule |
| `utils/llm_utils.py` | Split into `stage1_extract` + `stage2_evaluate`; geography fixes; Phase 2 tier fix |
| `utils/constants/llm.py` | Stage 1 prompt (new); Stage 2 prompt (updated); continental terms; remove Low Match from PHASE2_PROMOTE_TIERS |
| `utils/scrape_worker.py` | Listing page detection + pending_urls write; Stage 1→2 orchestration; fund_name from Stage 1 |
| `utils/db/pending_urls_store.py` | New file — CRUD for pending_urls |
| `api/routes/scrape.py` or `api/routes/pending.py` | New pending URLs endpoints |
| `config/schema.sql` | Add pending_urls table |
| `frontend/app/admin/` | New Pending URLs tab |
| `tests/test_geography.py` | New |
| `tests/test_tier_derivation.py` | New |
| `tests/test_scraping.py` | New |
| `tests/test_pipeline.py` | New |

---

## Out of Scope

- Discovery pipeline (sources, orchestrator, scheduler)
- Existing fund records (no backfill; re-scraping runs new pipeline in place)
- NTEE code data entry (org profile gap — fill in admin panel separately)
- Multi-tenant support
