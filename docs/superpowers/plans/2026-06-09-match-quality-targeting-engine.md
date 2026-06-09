# Match-Quality & Targeting Engine — Implementation Plan (Phases 0–2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation for demand-driven funder discovery — install JS rendering, enable pgvector, enrich the funder pool with 990 program-areas/grantees, and embed funders + opportunities for vector search.

**Architecture:** This plan covers **Phases 0–2** of the spec at `docs/superpowers/specs/2026-06-09-match-quality-targeting-engine-design.md` — the infrastructure and data foundation that has **no user-visible behavior change**. The targeting query, rerank, gate, and orchestrator wiring (Phases 3–8) are deferred to follow-on plans because their specifics depend on the embedding/enrichment quality produced here (see "Follow-on plans" at the bottom).

**Tech Stack:** Python 3.11, FastAPI, Supabase (Postgres + pgvector), OpenAI `text-embedding-3-small` (openai==2.6.0), Playwright (Chromium), APScheduler. Tests: pytest (flat layout in `tests/`).

**Conventions to follow (read before starting):**
- OpenAI key resolution: reuse `utils.llm_utils.get_client()` / `_get_openai_key()` (DB `api_tokens` first, env var fallback). Never read the key directly.
- Supabase singleton: `utils.db.client.get_supabase()`. Background jobs that run in threads create their own client via `create_client(get_settings().supabase_url, get_settings().supabase_service_key)` (see `IRS_BMF_Source` for the pattern — avoids singleton races).
- Tests are flat files in `tests/` (e.g. `tests/test_embeddings.py`). Mock all network/DB calls with `monkeypatch`.
- Migrations: idempotent SQL in `config/migration_phase*.sql`, also reflected into `config/schema.sql`. Applied manually via the Supabase SQL editor.
- Keep `utils/llm_utils.py` extraction/scoring **unchanged**.

---

## File Structure (Phases 0–2)

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `config/migration_phase11_targeting_engine.sql` | Create | All schema changes from spec §4 (pgvector, funder enrichment cols, embeddings, org targeting cols, pending_urls cols). |
| `config/schema.sql` | Modify | Reflect the same DDL for fresh setups. |
| `Dockerfile` | Modify | Install Chromium for Playwright. |
| `scripts/check_playwright.py` | Create | One-off smoke check that headless Chromium launches. |
| `utils/scraping.py` | Modify | Global Playwright concurrency semaphore. |
| `utils/discovery/embeddings.py` | Create | OpenAI embedding wrapper (`embed_text`, `embed_batch`). |
| `utils/discovery/funder_enrichment.py` | Create | Background job: parse 990s → persist program_areas/grantees → embed funders + opportunities. |
| `utils/discovery/scheduler.py` | Modify | Add `funder_enrichment` cron job. |
| `tests/test_embeddings.py` | Create | Unit tests for the embedding wrapper (mocked). |
| `tests/test_funder_enrichment.py` | Create | Unit tests for enrichment field-building + batch selection (mocked). |

---

## Task 1: Schema migration (pgvector + new columns)

**Files:**
- Create: `config/migration_phase11_targeting_engine.sql`
- Modify: `config/schema.sql` (append the same DDL under a Phase 11 banner)

- [ ] **Step 1: Write the migration file**

Create `config/migration_phase11_targeting_engine.sql`:

```sql
-- ============================================================
-- Phase 11 migration: Match-Quality & Targeting Engine
-- ============================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- Funder knowledge base enrichment
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS program_areas    TEXT[];
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS top_grantees     JSONB;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS grantee_purposes TEXT;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS embedding        vector(1536);
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS enriched_at      TIMESTAMPTZ;
ALTER TABLE discovery_funders ADD COLUMN IF NOT EXISTS embedded_at      TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS discovery_funders_embedding_idx
  ON discovery_funders USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS discovery_funders_enrich_queue_idx
  ON discovery_funders (enriched_at) WHERE enriched_at IS NULL;

-- Federal opportunity embeddings
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS embedding   vector(1536);
ALTER TABLE grant_opportunities ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS grant_opportunities_embedding_idx
  ON grant_opportunities USING hnsw (embedding vector_cosine_ops);

-- Client targeting profile
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cause_keywords       TEXT[] DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS targeting_confirmed  BOOLEAN DEFAULT FALSE;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS client_embedding     vector(1536);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS targeting_updated_at TIMESTAMPTZ;

-- Pending-URLs maybe-bucket metadata
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS funder_name      TEXT;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS discovery_source TEXT;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS match_score      REAL;
ALTER TABLE pending_urls ADD COLUMN IF NOT EXISTS match_reason     TEXT;
```

- [ ] **Step 2: Reflect into `config/schema.sql`**

Append the same block to `config/schema.sql` under a `-- Phase 11 ...` banner so fresh DB setups get it.

- [ ] **Step 3: Apply to Supabase + verify pgvector**

Run the migration in the Supabase SQL editor. Then verify the extension works:

```sql
SELECT '[1,2,3]'::vector;                          -- should return a vector literal
SELECT embedding FROM discovery_funders LIMIT 1;    -- column exists (NULL ok)
```

Expected: no error. **If `CREATE EXTENSION vector` fails** (plan doesn't allow it), STOP — escalate; Phase 2 needs it (fallback noted in spec §9).

- [ ] **Step 4: Commit**

```bash
git add -f config/migration_phase11_targeting_engine.sql
git add config/schema.sql
git commit -m "feat(discovery): phase11 schema — pgvector, funder enrichment + embedding columns"
```

---

## Task 2: Install Playwright Chromium in the Docker image

**Files:**
- Modify: `Dockerfile`
- Create: `scripts/check_playwright.py`

- [ ] **Step 1: Write a Playwright smoke-check script**

Create `scripts/check_playwright.py`:

```python
"""Smoke check: confirm headless Chromium launches and renders a trivial page."""
import sys


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<h1>ok</h1>")
        text = page.inner_text("h1")
        browser.close()
    print(f"playwright ok: rendered '{text}'")
    return 0 if text == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Modify the Dockerfile to install Chromium**

In `Dockerfile`, in the **final** stage (after `COPY --from=builder /opt/venv /opt/venv`), add a browser-install step. `playwright install --with-deps chromium` pulls the apt libraries Chromium needs on `python:3.11-slim`:

```dockerfile
COPY --from=builder /opt/venv /opt/venv
COPY . .

# Install Chromium + its OS dependencies for the JS-render fallback.
RUN playwright install --with-deps chromium

CMD ["sh", "-c", "gunicorn api.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:${PORT:-8000}"]
```

- [ ] **Step 3: Build the image and run the smoke check**

Run:
```bash
docker build -t af-api:pw-test .
docker run --rm af-api:pw-test python scripts/check_playwright.py
```
Expected: `playwright ok: rendered 'ok'` and exit 0. If it fails with missing-library errors, add the reported `apt-get install -y` packages before the `playwright install` line and rebuild.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile scripts/check_playwright.py
git commit -m "fix(scrape): install Chromium in Docker so the Playwright JS fallback works in prod"
```

---

## Task 3: Cap Playwright concurrency (protect the 1 GiB container)

**Files:**
- Modify: `utils/scraping.py` (the `playwright_fetch` function, ~line 65)
- Test: `tests/test_scraping_utils.py` (existing file — add a test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scraping_utils.py`:

```python
def test_playwright_semaphore_exists_and_bounds_concurrency():
    import utils.scraping as scraping
    # A module-level bounded semaphore must gate browser launches.
    assert hasattr(scraping, "_PW_SEM")
    # Default cap is 1 on the constrained container.
    assert scraping._PW_SEM._initial_value == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scraping_utils.py::test_playwright_semaphore_exists_and_bounds_concurrency -v`
Expected: FAIL with `AttributeError: module 'utils.scraping' has no attribute '_PW_SEM'`.

- [ ] **Step 3: Add the semaphore and wrap the browser launch**

In `utils/scraping.py`, near the top imports ensure `import os` and `import threading` are present, then add a module-level semaphore (place it just above `def playwright_fetch`):

```python
# Cap concurrent headless-Chromium instances. The Azure Container App is
# 0.5 vCPU / 1 GiB — uncapped Chromium across the discovery thread-pool OOMs.
_PW_SEM = threading.BoundedSemaphore(int(os.getenv("PLAYWRIGHT_MAX_CONCURRENCY", "1")))
```

Then wrap the existing `sync_playwright()` block in `playwright_fetch` with the semaphore:

```python
def playwright_fetch(url: str) -> Optional[str]:
    """Fetch a URL with headless Chromium, waiting for JS to render.

    Returns raw HTML string, or None on failure or missing dependency.
    Only call when BS4 extraction yields fewer than _PLAYWRIGHT_WORD_THRESHOLD words.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log_message("playwright not installed — skipping JS render fallback", "warning")
        return None
    try:
        with _PW_SEM:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                content = page.content()
                browser.close()
                return content
    except Exception as exc:
        log_message(f"Playwright fetch failed for {url}: {exc}", "warning")
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scraping_utils.py::test_playwright_semaphore_exists_and_bounds_concurrency -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/scraping.py tests/test_scraping_utils.py
git commit -m "fix(scrape): bound Playwright concurrency with a semaphore for the 1GiB container"
```

---

## Task 4: Embedding wrapper module

**Files:**
- Create: `utils/discovery/embeddings.py`
- Test: `tests/test_embeddings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_embeddings.py`:

```python
import utils.discovery.embeddings as emb


class _FakeEmbeddings:
    def __init__(self, dim):
        self._dim = dim

    def create(self, model, input):
        # Mirror openai's response shape: .data is a list of objects with .embedding
        class _Item:
            def __init__(self, vec):
                self.embedding = vec

        class _Resp:
            pass

        r = _Resp()
        r.data = [_Item([0.1] * self._dim) for _ in input]
        return r


class _FakeClient:
    def __init__(self, dim=1536):
        self.embeddings = _FakeEmbeddings(dim)


def test_embed_text_returns_vector(monkeypatch):
    monkeypatch.setattr(emb, "get_client", lambda: _FakeClient())
    vec = emb.embed_text("children youth education")
    assert isinstance(vec, list)
    assert len(vec) == 1536


def test_embed_batch_preserves_order_and_count(monkeypatch):
    monkeypatch.setattr(emb, "get_client", lambda: _FakeClient())
    out = emb.embed_batch(["a", "b", "c"])
    assert len(out) == 3
    assert all(len(v) == 1536 for v in out)


def test_embed_text_returns_none_without_client(monkeypatch):
    monkeypatch.setattr(emb, "get_client", lambda: None)
    assert emb.embed_text("x") is None


def test_embed_batch_skips_empty_strings(monkeypatch):
    monkeypatch.setattr(emb, "get_client", lambda: _FakeClient())
    out = emb.embed_batch(["", "real", "   "])
    # Empty/whitespace inputs map to None; real text gets a vector.
    assert out[0] is None
    assert out[1] is not None and len(out[1]) == 1536
    assert out[2] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_embeddings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.discovery.embeddings'`.

- [ ] **Step 3: Implement the module**

Create `utils/discovery/embeddings.py`:

```python
"""OpenAI embedding wrapper for the discovery targeting engine.

Reuses the same key-resolution as llm_utils (DB api_tokens → env). Returns
1536-dim vectors from text-embedding-3-small. All callers must handle a None
return (no API key configured) gracefully.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from utils.llm_utils import get_client

logger = logging.getLogger(__name__)

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
_BATCH_CAP = 100
_MAX_CHARS = 8000  # keep well under the model's token limit


def _clean(text: str) -> str:
    return (text or "").strip()[:_MAX_CHARS]


def embed_text(text: str) -> Optional[List[float]]:
    """Embed a single string. Returns None if no client or empty input."""
    cleaned = _clean(text)
    if not cleaned:
        return None
    out = embed_batch([cleaned])
    return out[0] if out else None


def embed_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """Embed many strings, preserving order. Empty inputs map to None.

    Returns a list the same length as `texts`. On API failure for a chunk,
    that chunk's entries are None (caller decides whether to retry later).
    """
    client = get_client()
    results: List[Optional[List[float]]] = [None] * len(texts)
    if client is None:
        return results

    # Collect indices of non-empty inputs to send.
    payload_idx = [i for i, t in enumerate(texts) if _clean(t)]
    for start in range(0, len(payload_idx), _BATCH_CAP):
        chunk_idx = payload_idx[start : start + _BATCH_CAP]
        chunk = [_clean(texts[i]) for i in chunk_idx]
        for attempt in range(3):
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=chunk)
                for local_i, item in enumerate(resp.data):
                    results[chunk_idx[local_i]] = item.embedding
                break
            except Exception as exc:
                if attempt == 2:
                    logger.warning("embed_batch chunk failed after retries: %s", exc)
                else:
                    time.sleep(2 ** attempt)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_embeddings.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add utils/discovery/embeddings.py tests/test_embeddings.py
git commit -m "feat(discovery): embedding wrapper (text-embedding-3-small)"
```

---

## Task 5: Funder enrichment — field builders

Build the pure functions that turn a parsed 990 into the new `discovery_funders` fields. Keep them pure (no DB/LLM) so they're unit-testable; the job wiring comes in Task 6.

**Files:**
- Create: `utils/discovery/funder_enrichment.py`
- Test: `tests/test_funder_enrichment.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_funder_enrichment.py`:

```python
import utils.discovery.funder_enrichment as fe


def test_build_grantee_purposes_concatenates_purposes_and_areas():
    summary = {
        "program_areas": ["Youth development", "Education"],
        "top_grantees": [
            {"name": "Boys & Girls Club", "amount": "$50,000", "purpose": "after-school youth programs"},
            {"name": "Local Library", "amount": "$10,000", "purpose": "childhood literacy"},
        ],
    }
    text = fe.build_grantee_purposes(summary)
    assert "Youth development" in text
    assert "after-school youth programs" in text
    assert "childhood literacy" in text


def test_build_grantee_purposes_handles_empty():
    assert fe.build_grantee_purposes({}) == ""
    assert fe.build_grantee_purposes({"program_areas": [], "top_grantees": []}) == ""


def test_build_embedding_input_combines_signals():
    row = {"name": "Acme Foundation", "ntee_code": "P20", "city": "Atlanta", "state": "GA"}
    text = fe.build_embedding_input(row, grantee_purposes="youth literacy programs")
    assert "Acme Foundation" in text
    assert "youth literacy programs" in text
    assert "GA" in text


def test_build_embedding_input_without_990_uses_identity_only():
    row = {"name": "Bare Foundation", "ntee_code": "T20", "city": "Macon", "state": "GA"}
    text = fe.build_embedding_input(row, grantee_purposes="")
    assert "Bare Foundation" in text
    assert text.strip() != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_funder_enrichment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.discovery.funder_enrichment'`.

- [ ] **Step 3: Implement the field builders**

Create `utils/discovery/funder_enrichment.py` (job wiring added in Task 6):

```python
"""Funder knowledge-base enrichment.

Progressively parses 990s for discovery_funders rows, persisting program areas
and past grantees, then embeds each funder so it is searchable by the targeting
engine. Geo-scoped to the org(s) actually configured — never enriches the whole
~1M-row table at once.

This module file holds pure field-builders (unit-tested) + the job entry point
(run_funder_enrichment) wired in Task 6.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def build_grantee_purposes(summary: Dict[str, Any]) -> str:
    """Concatenate 990 program areas + grantee purposes into embeddable text."""
    parts: List[str] = []
    for area in summary.get("program_areas") or []:
        if area:
            parts.append(str(area))
    for g in summary.get("top_grantees") or []:
        if isinstance(g, dict):
            purpose = (g.get("purpose") or "").strip()
            if purpose:
                parts.append(purpose)
    return " | ".join(parts).strip()


def build_embedding_input(row: Dict[str, Any], *, grantee_purposes: str) -> str:
    """Build the text we embed for a funder.

    Always includes identity (name + NTEE + location) so funders without a
    parsed 990 are still searchable; appends grant-signal text when available.
    """
    bits: List[str] = []
    if row.get("name"):
        bits.append(str(row["name"]))
    if row.get("ntee_code"):
        bits.append(f"NTEE {row['ntee_code']}")
    loc = " ".join(str(row[k]) for k in ("city", "state") if row.get(k))
    if loc:
        bits.append(loc)
    if grantee_purposes:
        bits.append(grantee_purposes)
    return " | ".join(bits).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_funder_enrichment.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add utils/discovery/funder_enrichment.py tests/test_funder_enrichment.py
git commit -m "feat(discovery): funder-enrichment field builders (pure)"
```

---

## Task 6: Funder enrichment — job + scheduler wiring

Wire the field builders into a batch job that reads unenriched funders, parses their 990s (reusing existing helpers), persists fields, embeds, and is registered on a cron.

**Files:**
- Modify: `utils/discovery/funder_enrichment.py` (add `select_enrichment_batch`, `enrich_one`, `run_funder_enrichment`)
- Modify: `utils/discovery/scheduler.py` (add the cron job)
- Test: `tests/test_funder_enrichment.py` (add batch-selection + enrich-one tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_funder_enrichment.py`:

```python
class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        class _R:
            pass

        r = _R()
        r.data = self._rows
        return r


class _FakeSB:
    def __init__(self, rows):
        self._rows = rows
        self.updated = []

    def table(self, name):
        return _FakeQuery(self._rows)


def test_select_enrichment_batch_filters_states(monkeypatch):
    rows = [{"ein": "1", "state": "GA", "name": "A"}]
    sb = _FakeSB(rows)
    out = fe.select_enrichment_batch(sb, states=["GA"], limit=10)
    assert out == rows


def test_enrich_one_builds_update_payload(monkeypatch):
    # Stub the 990 fetch+parse+extract to a fixed summary.
    monkeypatch.setattr(
        fe, "_fetch_990_summary",
        lambda row, sb: {
            "program_areas": ["Youth"],
            "top_grantees": [{"name": "X", "amount": "$1", "purpose": "kids sports"}],
        },
    )
    monkeypatch.setattr(fe, "embed_text", lambda t: [0.0] * 1536)
    payload = fe.enrich_one({"ein": "1", "name": "A", "state": "GA"}, sb=None)
    assert payload["program_areas"] == ["Youth"]
    assert "kids sports" in payload["grantee_purposes"]
    assert len(payload["embedding"]) == 1536
    assert payload["enriched_at"] is not None
    assert payload["embedded_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_funder_enrichment.py -v`
Expected: FAIL with `AttributeError: module 'utils.discovery.funder_enrichment' has no attribute 'select_enrichment_batch'`.

- [ ] **Step 3: Implement the job functions**

Append to `utils/discovery/funder_enrichment.py`:

```python
from datetime import datetime, timezone

from utils.discovery.embeddings import embed_text

_BATCH_DEFAULT = 100


def select_enrichment_batch(sb, *, states: List[str], limit: int = _BATCH_DEFAULT) -> List[Dict[str, Any]]:
    """Unenriched funders in the given states, richest first."""
    q = sb.table("discovery_funders").select(
        "ein, name, city, state, ntee_code, asset_amount, website"
    ).is_("enriched_at", "null")
    if states:
        q = q.in_("state", [s.upper() for s in states])
    q = q.order("asset_amount", desc=True).limit(limit)
    try:
        return q.execute().data or []
    except Exception as exc:
        logger.warning("select_enrichment_batch failed: %s", exc)
        return []


def _fetch_990_summary(row: Dict[str, Any], sb) -> Dict[str, Any]:
    """Look up the funder's latest 990, parse it, and LLM-extract grant signals.

    Reuses irs_990_index (DB) → irs_990_zips.fetch_multiple_xmls →
    irs_990_parser.xml_to_narrative → llm_utils.extract_from_document('form_990').
    Returns {} when no filing / parse fails.
    """
    from utils.discovery.sources.irs_990_parser import xml_to_narrative
    from utils.discovery.sources.irs_990_zips import fetch_multiple_xmls
    from utils.llm_utils import extract_from_document

    ein = str(row.get("ein") or "").strip()
    if not ein:
        return {}
    try:
        rec = (
            sb.table("irs_990_index")
            .select("object_id, batch_zip, submission_year, tax_year")
            .eq("ein", ein)
            .order("tax_year", desc=True)
            .limit(1)
            .execute()
            .data or []
        )
        if not rec:
            return {}
        r0 = rec[0]
        xmls = fetch_multiple_xmls([(r0["object_id"], r0["batch_zip"], int(r0["submission_year"]))])
        xml = xmls.get(r0["object_id"])
        if not xml:
            return {}
        narrative = xml_to_narrative(xml) or ""
        if not narrative:
            return {}
        return extract_from_document(narrative, "form_990") or {}
    except Exception as exc:
        logger.debug("990 summary failed for ein=%s: %s", ein, exc)
        return {}


def enrich_one(row: Dict[str, Any], *, sb) -> Dict[str, Any]:
    """Build the update payload for a single funder (does not write)."""
    summary = _fetch_990_summary(row, sb)
    purposes = build_grantee_purposes(summary)
    now = datetime.now(timezone.utc).isoformat()
    payload: Dict[str, Any] = {
        "program_areas": summary.get("program_areas") or None,
        "top_grantees": summary.get("top_grantees") or None,
        "grantee_purposes": purposes or None,
        "enriched_at": now,
    }
    vec = embed_text(build_embedding_input(row, grantee_purposes=purposes))
    if vec is not None:
        payload["embedding"] = vec
        payload["embedded_at"] = now
    return payload


def run_funder_enrichment(*, states: List[str] | None = None, limit: int = _BATCH_DEFAULT) -> int:
    """Cron entry point. Enriches up to `limit` funders. Returns count processed."""
    from supabase import create_client
    from utils.config import get_settings
    from utils.discovery.prefilter import load_org_profile

    if states is None:
        states = load_org_profile().effective_states()

    s = get_settings()
    sb = create_client(s.supabase_url, s.supabase_service_key)
    batch = select_enrichment_batch(sb, states=states, limit=limit)
    processed = 0
    for row in batch:
        try:
            payload = enrich_one(row, sb=sb)
            sb.table("discovery_funders").update(payload).eq("ein", row["ein"]).execute()
            processed += 1
        except Exception as exc:
            logger.warning("enrich_one failed for ein=%s: %s", row.get("ein"), exc)
    logger.info("funder_enrichment processed %d funders", processed)
    return processed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_funder_enrichment.py -v`
Expected: all passed.

- [ ] **Step 5: Register the cron in the scheduler**

In `utils/discovery/scheduler.py`: add the job id constant near the others, a default cron, a wrapper, and register it in `start_scheduler()` following the existing 5-job pattern.

Add constant + default:
```python
FUNDER_ENRICHMENT_JOB_ID = "funder_enrichment"
_DEFAULT_FUNDER_ENRICHMENT_CRON = "0 1 * * *"  # nightly 1am UTC
```

Add wrapper (near the other `_*_job` wrappers):
```python
def _funder_enrichment_job() -> None:
    """Nightly funder knowledge-base enrichment (990 parse + embed)."""
    try:
        from utils.discovery.funder_enrichment import run_funder_enrichment
        run_funder_enrichment(limit=int(os.getenv("FUNDER_ENRICHMENT_BATCH", "100")))
    except Exception as exc:
        logger.error("Scheduled funder enrichment raised: %s", exc, exc_info=True)
```
(Ensure `import os` is present at the top of `scheduler.py`.)

Register in `start_scheduler()` after the existing `sched.add_job(...)` calls:
```python
    sched.add_job(
        _funder_enrichment_job,
        trigger=_trigger(_DEFAULT_FUNDER_ENRICHMENT_CRON, _DEFAULT_FUNDER_ENRICHMENT_CRON),
        id=FUNDER_ENRICHMENT_JOB_ID,
        replace_existing=True,
    )
```

- [ ] **Step 6: Verify the scheduler still imports and registers cleanly**

Run:
```bash
python -c "from utils.discovery.scheduler import _funder_enrichment_job, FUNDER_ENRICHMENT_JOB_ID; print('ok', FUNDER_ENRICHMENT_JOB_ID)"
```
Expected: `ok funder_enrichment`.

- [ ] **Step 7: Commit**

```bash
git add utils/discovery/funder_enrichment.py utils/discovery/scheduler.py tests/test_funder_enrichment.py
git commit -m "feat(discovery): funder-enrichment job + nightly cron (990 parse + embed)"
```

---

## Manual verification (after Phases 0–2 land)

1. Apply the migration to a dev Supabase project.
2. Run one enrichment batch against a single state with real keys:
   ```bash
   python -c "from utils.discovery.funder_enrichment import run_funder_enrichment; print(run_funder_enrichment(states=['GA'], limit=10))"
   ```
3. Confirm in Supabase: those `discovery_funders` rows now have `program_areas`, `grantee_purposes`, a non-null `embedding`, and `enriched_at`/`embedded_at`.
4. Sanity-check vector search returns sensible neighbours:
   ```sql
   SELECT name, ntee_code FROM discovery_funders
   WHERE embedding IS NOT NULL
   ORDER BY embedding <=> (SELECT embedding FROM discovery_funders WHERE embedding IS NOT NULL LIMIT 1)
   LIMIT 5;
   ```

---

## Self-review (against spec §4, §5, §6 Phases 0–2)

- **Spec coverage:** Playwright install (§A8/Phase 0) → Task 2; semaphore (§A8) → Task 3; pgvector + all columns (§4) → Task 1; embeddings wrapper (§A5/Phase 2) → Task 4; 990 enrichment (§A3/Phase 1) → Tasks 5–6; embedding pass + cron (§Phase 2) → Task 6. Covered.
- **Placeholder scan:** none — every code/SQL/command step is concrete.
- **Type consistency:** `build_grantee_purposes`, `build_embedding_input`, `embed_text`, `embed_batch`, `select_enrichment_batch`, `enrich_one`, `run_funder_enrichment`, `_fetch_990_summary` are used with consistent signatures across tasks; `EMBED_DIM=1536` matches `vector(1536)` in the migration.
- **Open dependency to confirm at execution time:** `llm_utils.extract_from_document(text, "form_990")` is referenced in `_fetch_990_summary` — verify its exact name/signature in `utils/llm_utils.py` before Task 6 (it powers the existing document fetcher); adjust the call if the signature differs.

---

## Follow-on plans (Phases 3–8 — write after 0–2 land)

These are deliberately **not** coded here because their details depend on the embedding/enrichment quality produced above (e.g. `match_score` weighting, broadening thresholds). Each becomes its own plan via the writing-plans skill once Phases 0–2 are verified:

- **Plan B — Phase 3:** Client targeting profile (`targeting.py: derive_targeting`, `build_client_embedding`) + onboarding API/UI.
- **Plan C — Phases 4–5:** `retrieve_candidates` (pgvector search + geo filter + cursor rotation + broadening) + `match_score` + prioritized scrape ordering.
- **Plan D — Phase 6:** `rerank.py`, `sitemap_map.py`, `relevance_gate.py`, `foundation_crawler` upgrade, 3-lane routing into `pending_urls`.
- **Plan E — Phases 7–8:** orchestrator integration behind `targeting_enabled` flag + multi-tenant-readiness audit.
```
