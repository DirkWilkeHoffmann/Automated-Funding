"""Tests for Phase 6: LLM reranking."""

import json

import utils.discovery.rerank as rr
from utils.discovery.rerank import _apply_batch_results, _build_batch_prompt, rerank_and_explain
from utils.discovery.targeting import Candidate, TargetingProfile


# ── helpers ───────────────────────────────────────────────────────────────────


def _funder(name="Test Fdn", similarity=0.7, program_areas=None, grantee_purposes=None):
    return Candidate(
        kind="funder", id="1", name=name, url="https://test.org",
        state="GA", similarity=similarity,
        program_areas=program_areas or ["Youth Development"],
        grantee_purposes=grantee_purposes or "youth employment programs",
    )


def _opp(name="Youth Grant", similarity=0.7, match_score=0.0):
    c = Candidate(
        kind="opportunity", id="OPP-1", name=name,
        url="https://grants.gov/1", state=None, similarity=similarity,
    )
    c.match_score = match_score
    return c


def _profile():
    return TargetingProfile(
        mission="We help at-risk youth find jobs",
        cause_keywords=["youth", "employment"],
    )


# ── _build_batch_prompt ───────────────────────────────────────────────────────


def test_prompt_includes_mission():
    p = _profile()
    c = _funder()
    prompt = _build_batch_prompt(p, [c])
    assert "at-risk youth" in prompt


def test_prompt_includes_candidate_name():
    p = _profile()
    c = _funder(name="Community Trust")
    prompt = _build_batch_prompt(p, [c])
    assert "Community Trust" in prompt


def test_prompt_includes_grantee_purposes():
    p = _profile()
    c = _funder(grantee_purposes="after-school reading programs")
    prompt = _build_batch_prompt(p, [c])
    assert "after-school reading programs" in prompt


def test_prompt_handles_empty_profile():
    p = TargetingProfile()
    c = _funder()
    prompt = _build_batch_prompt(p, [c])
    assert "CLIENT MISSION" in prompt  # still renders without crashing


# ── _apply_batch_results ──────────────────────────────────────────────────────


def test_apply_sets_all_fields():
    c = _funder()
    results = [{
        "match_confirmed": True,
        "match_reason": "Matches youth workforce focus",
        "past_grantee_overlap": True,
        "predicted_tier": "highly_eligible",
    }]
    _apply_batch_results([c], results)
    assert c.match_reason == "Matches youth workforce focus"
    assert c.past_grantee_overlap is True
    assert c.predicted_tier == "highly_eligible"


def test_apply_clamps_unknown_tier_to_borderline():
    c = _funder()
    _apply_batch_results([c], [{"predicted_tier": "unknown_value"}])
    assert c.predicted_tier == "borderline"


def test_apply_partial_results_safe():
    c1, c2 = _funder(), _funder()
    _apply_batch_results([c1, c2], [{"predicted_tier": "eligible"}])
    assert c1.predicted_tier == "eligible"
    assert c2.predicted_tier == ""  # untouched — only 1 result for 2 candidates


def test_apply_truncates_long_reason():
    c = _funder()
    long_reason = "x" * 600
    _apply_batch_results([c], [{"match_reason": long_reason, "predicted_tier": "eligible"}])
    assert len(c.match_reason) <= 500


# ── rerank_and_explain — no client ────────────────────────────────────────────


def test_rerank_no_client_defaults_funders_to_borderline(monkeypatch):
    monkeypatch.setattr(rr, "get_client", lambda: None)
    candidates = [_funder(), _funder()]
    rerank_and_explain(_profile(), candidates)
    assert all(c.predicted_tier == "borderline" for c in candidates)


def test_rerank_no_client_returns_all_candidates(monkeypatch):
    monkeypatch.setattr(rr, "get_client", lambda: None)
    candidates = [_funder(), _opp()]
    result = rerank_and_explain(_profile(), candidates)
    assert len(result) == 2


# ── rerank_and_explain — opportunities ────────────────────────────────────────


def test_rerank_opp_high_score_gets_eligible(monkeypatch):
    monkeypatch.setattr(rr, "get_client", lambda: None)
    c = _opp(match_score=0.80)
    rerank_and_explain(_profile(), [c])
    assert c.predicted_tier == "eligible"


def test_rerank_opp_medium_score_gets_borderline(monkeypatch):
    monkeypatch.setattr(rr, "get_client", lambda: None)
    c = _opp(match_score=0.60)
    rerank_and_explain(_profile(), [c])
    assert c.predicted_tier == "borderline"


def test_rerank_opp_low_score_gets_not_eligible(monkeypatch):
    monkeypatch.setattr(rr, "get_client", lambda: None)
    c = _opp(match_score=0.40)
    rerank_and_explain(_profile(), [c])
    assert c.predicted_tier == "not_eligible"


def test_rerank_opp_existing_tier_not_overwritten(monkeypatch):
    monkeypatch.setattr(rr, "get_client", lambda: None)
    c = _opp(match_score=0.40)
    c.predicted_tier = "eligible"  # pre-set
    rerank_and_explain(_profile(), [c])
    assert c.predicted_tier == "eligible"  # unchanged


# ── rerank_and_explain — with fake LLM client ─────────────────────────────────


class _FakeCompletion:
    def __init__(self, content: str):
        class _Choice:
            class message:
                pass
        choice = _Choice()
        choice.message.content = content
        self.choices = [choice]


class _FakeChat:
    def __init__(self, response_json: dict):
        self._json = response_json

    def create(self, **kwargs):
        return _FakeCompletion(json.dumps(self._json))


class _FakeClient:
    def __init__(self, response_json: dict):
        self.chat = type("chat", (), {"completions": _FakeChat(response_json)})()


def test_rerank_with_client_sets_tier(monkeypatch):
    response = {"results": [{"match_confirmed": True, "match_reason": "Great fit",
                              "past_grantee_overlap": False, "predicted_tier": "eligible"}]}
    monkeypatch.setattr(rr, "get_client", lambda: _FakeClient(response))
    c = _funder()
    rerank_and_explain(_profile(), [c])
    assert c.predicted_tier == "eligible"
    assert c.match_reason == "Great fit"


def test_rerank_with_client_sets_overlap(monkeypatch):
    response = {"results": [{"match_confirmed": True, "match_reason": "Funded youth orgs",
                              "past_grantee_overlap": True, "predicted_tier": "highly_eligible"}]}
    monkeypatch.setattr(rr, "get_client", lambda: _FakeClient(response))
    c = _funder()
    rerank_and_explain(_profile(), [c])
    assert c.past_grantee_overlap is True
    assert c.predicted_tier == "highly_eligible"


def test_rerank_batch_failure_defaults_to_borderline(monkeypatch):
    class _BrokenChat:
        def create(self, **kwargs):
            raise RuntimeError("API down")

    class _BrokenClient:
        chat = type("chat", (), {"completions": _BrokenChat()})()

    monkeypatch.setattr(rr, "get_client", lambda: _BrokenClient())
    c = _funder()
    rerank_and_explain(_profile(), [c])
    assert c.predicted_tier == "borderline"
