"""Tests for Phase 5: match scoring and candidate prioritisation."""

import utils.discovery.scoring as sc
from utils.discovery.scoring import (
    ASSET_BOOST,
    KEYWORD_BOOST_MAX,
    KEYWORD_BOOST_PER,
    NTEE_BOOST,
    _asset_in_range,
    _keyword_hits,
    _ntee_matches,
    match_score,
    rank_candidates,
    scored_urls,
)
from utils.discovery.targeting import Candidate, TargetingProfile


# ── _ntee_matches ─────────────────────────────────────────────────────────────


def test_ntee_exact_prefix_matches():
    assert _ntee_matches("P20", ["P"]) is True


def test_ntee_longer_prefix_matches():
    assert _ntee_matches("P20", ["P20"]) is True


def test_ntee_no_match():
    assert _ntee_matches("B30", ["P", "O"]) is False


def test_ntee_case_insensitive():
    assert _ntee_matches("p20", ["P"]) is True


def test_ntee_none_code():
    assert _ntee_matches(None, ["P"]) is False


def test_ntee_empty_profile_codes():
    assert _ntee_matches("P20", []) is False


# ── _keyword_hits ─────────────────────────────────────────────────────────────


def test_keyword_hit_single():
    assert _keyword_hits("after-school youth programs", ["youth"]) == 1


def test_keyword_hit_multiple():
    assert _keyword_hits("youth employment and job training", ["youth", "employment", "training"]) == 3


def test_keyword_no_hit():
    assert _keyword_hits("arts and culture grants", ["youth", "employment"]) == 0


def test_keyword_word_boundary():
    # "youth" should not hit on "youthful"
    assert _keyword_hits("youthful exuberance grants", ["youth"]) == 0


def test_keyword_empty_purposes():
    assert _keyword_hits("", ["youth"]) == 0
    assert _keyword_hits(None, ["youth"]) == 0


def test_keyword_empty_keywords():
    assert _keyword_hits("youth programs", []) == 0


# ── _asset_in_range ───────────────────────────────────────────────────────────


def test_asset_in_range_typical():
    assert _asset_in_range(10_000_000, None, None) is True


def test_asset_below_floor():
    assert _asset_in_range(100_000, None, None) is False


def test_asset_above_ceiling():
    assert _asset_in_range(5_000_000_000, None, None) is False


def test_asset_none():
    assert _asset_in_range(None, None, None) is False


def test_asset_min_grant_size_too_large():
    # $1M asset, 2% = $20K implied. min_grant = $100K → no match
    assert _asset_in_range(1_000_000, min_grant_size=100_000, max_grant_size=None) is False


def test_asset_min_grant_size_fits():
    # $5M asset, 2% = $100K implied. min_grant = $50K → match
    assert _asset_in_range(5_000_000, min_grant_size=50_000, max_grant_size=None) is True


# ── match_score ───────────────────────────────────────────────────────────────


def _funder(similarity=0.7, ntee_code="P20", asset_amount=5_000_000,
            grantee_purposes="youth employment programs"):
    return Candidate(
        kind="funder", id="123", name="Test Foundation",
        url="https://testfdn.org", state="GA",
        similarity=similarity, ntee_code=ntee_code,
        asset_amount=asset_amount, grantee_purposes=grantee_purposes,
    )


def _opp(similarity=0.7):
    return Candidate(
        kind="opportunity", id="OPP-1", name="Youth Grant",
        url="https://grants.gov/1", state=None, similarity=similarity,
    )


def _profile(ntee_codes=None, cause_keywords=None, min_grant_size=None):
    return TargetingProfile(
        ntee_codes=ntee_codes or [],
        cause_keywords=cause_keywords or [],
        min_grant_size=min_grant_size,
    )


def test_match_score_base_only():
    c = _funder(similarity=0.6, ntee_code=None, asset_amount=None, grantee_purposes=None)
    p = _profile()
    assert match_score(c, p) == 0.6


def test_match_score_ntee_boost():
    c = _funder(similarity=0.6, ntee_code="P20", asset_amount=None)
    p = _profile(ntee_codes=["P"])
    s = match_score(c, p)
    assert abs(s - (0.6 + NTEE_BOOST)) < 1e-9


def test_match_score_keyword_boost_single():
    c = _funder(similarity=0.6, ntee_code=None, asset_amount=None,
                grantee_purposes="youth workforce programs")
    p = _profile(cause_keywords=["youth"])
    s = match_score(c, p)
    assert abs(s - (0.6 + KEYWORD_BOOST_PER)) < 1e-9


def test_match_score_keyword_boost_capped():
    # 6 keywords in text → capped at KEYWORD_BOOST_MAX
    purposes = "youth employment training jobs workforce skills"
    c = _funder(similarity=0.5, ntee_code=None, asset_amount=None, grantee_purposes=purposes)
    kws = ["youth", "employment", "training", "jobs", "workforce", "skills"]
    p = _profile(cause_keywords=kws)
    s = match_score(c, p)
    assert abs(s - (0.5 + KEYWORD_BOOST_MAX)) < 1e-9


def test_match_score_asset_boost():
    c = _funder(similarity=0.6, asset_amount=10_000_000, ntee_code=None, grantee_purposes=None)
    p = _profile()
    s = match_score(c, p)
    assert abs(s - (0.6 + ASSET_BOOST)) < 1e-9


def test_match_score_all_boosts():
    c = _funder(similarity=0.6, ntee_code="P20",
                asset_amount=10_000_000, grantee_purposes="youth employment programs")
    p = _profile(ntee_codes=["P"], cause_keywords=["youth", "employment"])
    s = match_score(c, p)
    expected = min(0.6 + NTEE_BOOST + 2 * KEYWORD_BOOST_PER + ASSET_BOOST, 1.0)
    assert abs(s - expected) < 1e-9


def test_match_score_clamped_at_one():
    c = _funder(similarity=0.99, ntee_code="P20",
                asset_amount=10_000_000, grantee_purposes="youth employment training")
    p = _profile(ntee_codes=["P"], cause_keywords=["youth", "employment", "training"])
    assert match_score(c, p) == 1.0


def test_match_score_opportunity_no_structural_boosts():
    # Opportunities only get the base similarity — no NTEE/keyword/asset boost
    c = _opp(similarity=0.7)
    p = _profile(ntee_codes=["P"], cause_keywords=["youth"])
    assert match_score(c, p) == 0.7


# ── rank_candidates ───────────────────────────────────────────────────────────


def test_rank_candidates_sorted_descending():
    candidates = [
        _funder(similarity=0.5),
        _funder(similarity=0.9),
        _funder(similarity=0.7),
    ]
    p = _profile()
    ranked = rank_candidates(candidates, p)
    scores = [c.match_score for c in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_candidates_sets_match_score():
    c = _funder(similarity=0.6, ntee_code="P20", asset_amount=10_000_000)
    p = _profile(ntee_codes=["P"])
    rank_candidates([c], p)
    assert c.match_score > 0.6  # boosted


def test_rank_candidates_empty():
    assert rank_candidates([], _profile()) == []


# ── scored_urls ───────────────────────────────────────────────────────────────


def test_scored_urls_returns_top_k():
    candidates = [_funder(similarity=float(i) / 10) for i in range(1, 8)]
    p = _profile()
    urls = scored_urls(candidates, p, limit=3)
    assert len(urls) == 3


def test_scored_urls_excludes_no_url():
    c1 = _funder(similarity=0.9)
    c2 = Candidate(kind="funder", id="2", name="No URL", url=None,
                   state="GA", similarity=0.95)
    urls = scored_urls([c1, c2], _profile(), limit=5)
    assert len(urls) == 1
    assert urls[0] == c1.url


def test_scored_urls_order_matches_score():
    c_low = _funder(similarity=0.4)
    c_low.url = "https://low.org"
    c_high = _funder(similarity=0.9)
    c_high.url = "https://high.org"
    urls = scored_urls([c_low, c_high], _profile(), limit=2)
    assert urls[0] == "https://high.org"
    assert urls[1] == "https://low.org"
