"""Tests for Phase 6: relevance gate (3-lane routing)."""

import utils.discovery.relevance_gate as rg
from utils.discovery.relevance_gate import (
    Lane,
    _deadline_passed,
    _is_invitation_only,
    _state_allowed,
    gate,
)
from utils.discovery.targeting import Candidate, TargetingProfile


# ── helpers ───────────────────────────────────────────────────────────────────


def _funder(
    state="GA",
    url="https://fdn.org",
    predicted_tier="eligible",
    grantee_purposes="youth programs",
    match_score=0.8,
):
    c = Candidate(
        kind="funder", id="1", name="Test Fdn", url=url,
        state=state, similarity=0.8,
        grantee_purposes=grantee_purposes,
    )
    c.predicted_tier = predicted_tier
    c.match_score = match_score
    return c


def _opp(
    state=None,
    url="https://grants.gov/1",
    close_date="2099-12-31",
    predicted_tier="eligible",
):
    c = Candidate(
        kind="opportunity", id="OPP-1", name="Youth Grant",
        url=url, state=state, similarity=0.8,
        close_date=close_date,
    )
    c.predicted_tier = predicted_tier
    return c


def _profile(states=None):
    return TargetingProfile(
        service_states=["GA"] if states is None else states,
        mission="Youth workforce development",
    )


_NO_SITEMAP = lambda url: []
_NO_CRAWLER = lambda url, **kw: None
_HAS_SITEMAP = lambda url: ["https://fdn.org/grants"]
_HAS_CRAWLER = lambda url, **kw: ("https://fdn.org/grants", "keyword_match")


# ── _state_allowed ────────────────────────────────────────────────────────────


def test_state_allowed_matching():
    assert _state_allowed(_funder(state="GA"), _profile(states=["GA"])) is True


def test_state_not_in_profile():
    assert _state_allowed(_funder(state="HI"), _profile(states=["GA"])) is False


def test_state_none_candidate_allowed():
    # Unknown state → don't drop speculatively
    assert _state_allowed(_funder(state=None), _profile(states=["GA"])) is True


def test_state_no_profile_states_allows_all():
    assert _state_allowed(_funder(state="HI"), _profile(states=[])) is True


def test_state_case_insensitive():
    assert _state_allowed(_funder(state="ga"), _profile(states=["GA"])) is True


# ── _deadline_passed ──────────────────────────────────────────────────────────


def test_deadline_future_not_passed():
    assert _deadline_passed(_opp(close_date="2099-12-31")) is False


def test_deadline_past_passed():
    assert _deadline_passed(_opp(close_date="2000-01-01")) is True


def test_deadline_funder_always_false():
    c = _funder()
    c.close_date = "2000-01-01"
    assert _deadline_passed(c) is False


def test_deadline_none_date_not_passed():
    assert _deadline_passed(_opp(close_date=None)) is False


def test_deadline_invalid_date_not_passed():
    assert _deadline_passed(_opp(close_date="not-a-date")) is False


# ── _is_invitation_only ───────────────────────────────────────────────────────


def test_invitation_only_detected():
    c = _funder(grantee_purposes="We do not accept unsolicited proposals.")
    assert _is_invitation_only(c) is True


def test_not_invitation_only():
    c = _funder(grantee_purposes="We fund youth workforce programs.")
    assert _is_invitation_only(c) is False


def test_opportunity_never_invitation_only():
    c = _opp()
    c.grantee_purposes = "invitation only"
    assert _is_invitation_only(c) is False


# ── gate — Stage 1 (hard rules) ───────────────────────────────────────────────


def test_gate_drops_wrong_state():
    c = _funder(state="HI")
    result = gate(c, _profile(states=["GA"]), sitemap_fn=_NO_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.DROP


def test_gate_drops_passed_deadline():
    c = _opp(close_date="2000-01-01")
    result = gate(c, _profile(), sitemap_fn=_NO_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.DROP


def test_gate_drops_invitation_only():
    c = _funder(grantee_purposes="We do not accept unsolicited proposals.")
    result = gate(c, _profile(), sitemap_fn=_NO_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.DROP


# ── gate — Stage 2 (pathway check) ───────────────────────────────────────────


def test_gate_drops_no_pathway():
    c = _funder(predicted_tier="eligible")
    result = gate(c, _profile(), sitemap_fn=_NO_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.DROP


def test_gate_pathway_via_sitemap():
    c = _funder(predicted_tier="eligible")
    result = gate(c, _profile(), sitemap_fn=_HAS_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.SCRAPE


def test_gate_pathway_via_crawler_fallback():
    c = _funder(predicted_tier="eligible")
    result = gate(c, _profile(), sitemap_fn=_NO_SITEMAP, crawler_fn=_HAS_CRAWLER)
    assert result == Lane.SCRAPE


def test_gate_upgrades_url_to_grants_page():
    c = _funder(url="https://fdn.org", predicted_tier="eligible")
    gate(c, _profile(), sitemap_fn=_HAS_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert c.url == "https://fdn.org/grants"


def test_gate_opportunity_always_has_pathway():
    c = _opp(url="https://grants.gov/1", predicted_tier="eligible")
    result = gate(c, _profile(), sitemap_fn=_NO_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.SCRAPE


def test_gate_funder_no_url_drops():
    c = _funder(url=None, predicted_tier="eligible")
    result = gate(c, _profile(), sitemap_fn=_NO_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.DROP


# ── gate — Stage 3 (tier routing) ────────────────────────────────────────────


def test_gate_highly_eligible_scrapes():
    c = _funder(predicted_tier="highly_eligible")
    result = gate(c, _profile(), sitemap_fn=_HAS_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.SCRAPE


def test_gate_eligible_scrapes():
    c = _funder(predicted_tier="eligible")
    result = gate(c, _profile(), sitemap_fn=_HAS_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.SCRAPE


def test_gate_borderline_pending():
    c = _funder(predicted_tier="borderline")
    result = gate(c, _profile(), sitemap_fn=_HAS_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.PENDING


def test_gate_not_eligible_drops():
    c = _funder(predicted_tier="not_eligible")
    result = gate(c, _profile(), sitemap_fn=_HAS_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.DROP


def test_gate_empty_tier_defaults_pending():
    c = _funder(predicted_tier="")
    result = gate(c, _profile(), sitemap_fn=_HAS_SITEMAP, crawler_fn=_NO_CRAWLER)
    assert result == Lane.PENDING
