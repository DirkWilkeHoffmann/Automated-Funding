"""Tests for Phase 7: orchestrator integration of the targeting path."""

import utils.discovery.targeted_run as tr
from utils.discovery.targeted_run import _cursor_state, run_targeted_path
from utils.discovery.targeting import Candidate, CandidateSet, TargetingCursor, TargetingProfile


# ── helpers ───────────────────────────────────────────────────────────────────


def _profile(with_embedding=True):
    p = TargetingProfile(
        org_id="test-org",
        mission="Youth workforce development",
        cause_keywords=["youth", "employment"],
        service_states=["GA"],
    )
    if with_embedding:
        p.client_embedding = [0.1] * 1536
    return p


def _funder(ein, similarity=0.8, state="GA", url="https://fdn.org"):
    c = Candidate(
        kind="funder", id=ein, name=f"Foundation {ein}",
        url=url, state=state, similarity=similarity,
    )
    c.predicted_tier = "eligible"
    c.match_score = similarity
    return c


class _FakeProgress:
    def __init__(self):
        self.urls_discovered = 0
        self.urls_new = 0
        self.scrape_job_id = None
        self._sources = {}

    def ensure_source(self, name):
        self._sources.setdefault(name, {})

    def update_source(self, name, **kwargs):
        self._sources.setdefault(name, {}).update(kwargs)


class _FakeThrottle:
    def maybe_write(self, progress, *, force=False):
        pass


# ── _cursor_state ─────────────────────────────────────────────────────────────


def test_cursor_state_shape():
    p = _profile()
    cursor = TargetingCursor(funder_offset=10, opp_offset=5, geo_broaden_level=1)
    state = _cursor_state(p, cursor)
    assert "targeting" in state
    assert state["targeting"]["test-org"]["funder_offset"] == 10
    assert state["targeting"]["test-org"]["opp_offset"] == 5
    assert state["targeting"]["test-org"]["geo_broaden_level"] == 1


# ── run_targeted_path — no embedding ──────────────────────────────────────────


def test_no_embedding_returns_empty(monkeypatch):
    monkeypatch.setattr(tr, "get_supabase", lambda: None)
    monkeypatch.setattr(tr, "load_targeting_profile", lambda: _profile(with_embedding=False))
    monkeypatch.setattr(tr, "load_cursor", lambda p: TargetingCursor())
    result = run_targeted_path(
        {"max_per_source": 10},
        _FakeProgress(), _FakeThrottle(), {},
    )
    scrape_urls, pending, dropped, cursor_patch, job_id = result
    assert scrape_urls == []
    assert pending == 0
    assert job_id is None
    assert cursor_patch == {}


# ── run_targeted_path — empty candidate pool ──────────────────────────────────


def test_empty_candidates_returns_empty(monkeypatch):
    profile = _profile()
    monkeypatch.setattr(tr, "load_targeting_profile", lambda: profile)
    monkeypatch.setattr(tr, "load_cursor", lambda p: TargetingCursor())
    monkeypatch.setattr(
        tr, "retrieve_candidates",
        lambda p, c, limit, sb: (CandidateSet(funders=[], opportunities=[]), TargetingCursor()),
    )
    monkeypatch.setattr(tr, "get_supabase", lambda: None)

    scrape_urls, pending, dropped, cursor_patch, job_id = run_targeted_path(
        {"max_per_source": 10}, _FakeProgress(), _FakeThrottle(), {},
    )
    assert scrape_urls == []
    assert "targeting" in cursor_patch  # cursor still saved


# ── run_targeted_path — full pipeline ─────────────────────────────────────────


class _FakeJobStore:
    class _Job:
        id = "job-123"

    def create(self, urls, url_metadata=None):
        return self._Job()


def _noop_rerank(profile, candidates):
    return candidates


def _gate_all_scrape(candidate, profile, **kw):
    from utils.discovery.relevance_gate import Lane
    return Lane.SCRAPE


def _gate_all_pending(candidate, profile, **kw):
    from utils.discovery.relevance_gate import Lane
    return Lane.PENDING


def _gate_all_drop(candidate, profile, **kw):
    from utils.discovery.relevance_gate import Lane
    return Lane.DROP


def _setup_mocks(monkeypatch, candidates, gate_fn=None, pending_store=None):
    profile = _profile()
    monkeypatch.setattr(tr, "load_targeting_profile", lambda: profile)
    monkeypatch.setattr(tr, "load_cursor", lambda p: TargetingCursor())
    monkeypatch.setattr(tr, "get_supabase", lambda: None)
    monkeypatch.setattr(
        tr, "retrieve_candidates",
        lambda p, c, limit, sb: (
            CandidateSet(funders=candidates, opportunities=[]),
            TargetingCursor(funder_offset=len(candidates)),
        ),
    )
    monkeypatch.setattr(tr, "rank_candidates", lambda candidates, p: candidates)
    monkeypatch.setattr(tr, "rerank_and_explain", _noop_rerank)
    monkeypatch.setattr(tr, "gate", gate_fn or _gate_all_scrape)
    monkeypatch.setattr(tr, "upsert_targeting_pending", pending_store or (lambda c: len(c)))

    import api.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "job_store", _FakeJobStore())
    return profile


def test_all_scrape_spawns_job(monkeypatch):
    candidates = [_funder(str(i)) for i in range(3)]
    _setup_mocks(monkeypatch, candidates)

    scrape_urls, pending, dropped, cursor_patch, job_id = run_targeted_path(
        {"max_per_source": 10}, _FakeProgress(), _FakeThrottle(), {},
    )
    assert len(scrape_urls) == 3
    assert pending == 0
    assert dropped == 0
    assert job_id == "job-123"


def test_all_pending_writes_store(monkeypatch):
    captured = []
    candidates = [_funder(str(i)) for i in range(2)]
    _setup_mocks(monkeypatch, candidates, gate_fn=_gate_all_pending,
                 pending_store=lambda c: captured.extend(c))

    scrape_urls, pending, dropped, cursor_patch, job_id = run_targeted_path(
        {"max_per_source": 10}, _FakeProgress(), _FakeThrottle(), {},
    )
    assert scrape_urls == []
    assert pending == 2
    assert len(captured) == 2
    assert job_id is None


def test_all_drop_no_job(monkeypatch):
    candidates = [_funder(str(i)) for i in range(4)]
    _setup_mocks(monkeypatch, candidates, gate_fn=_gate_all_drop)

    scrape_urls, pending, dropped, cursor_patch, job_id = run_targeted_path(
        {"max_per_source": 10}, _FakeProgress(), _FakeThrottle(), {},
    )
    assert scrape_urls == []
    assert dropped == 4
    assert job_id is None


def test_cursor_advanced_in_patch(monkeypatch):
    candidates = [_funder(str(i)) for i in range(5)]
    _setup_mocks(monkeypatch, candidates)

    _, _, _, cursor_patch, _ = run_targeted_path(
        {"max_per_source": 10}, _FakeProgress(), _FakeThrottle(), {},
    )
    assert cursor_patch["targeting"]["test-org"]["funder_offset"] == 5


def test_progress_urls_set(monkeypatch):
    candidates = [_funder(str(i)) for i in range(3)]
    _setup_mocks(monkeypatch, candidates)
    prog = _FakeProgress()

    run_targeted_path({"max_per_source": 10}, prog, _FakeThrottle(), {})
    assert prog.urls_discovered == 3
    assert prog.urls_new == 3


# ── orchestrator config flag ──────────────────────────────────────────────────


def test_config_defaults_targeting_disabled():
    from utils.discovery.config_store import _DEFAULTS
    assert _DEFAULTS["targeting_enabled"] is False


def test_config_load_includes_targeting_enabled(monkeypatch):
    import utils.discovery.config_store as cs
    monkeypatch.setattr(
        cs, "_load_config_cached",
        lambda: {**cs._DEFAULTS, "targeting_enabled": True},
    )
    from utils.discovery.config_store import load_config
    config = load_config()
    assert config["targeting_enabled"] is True
