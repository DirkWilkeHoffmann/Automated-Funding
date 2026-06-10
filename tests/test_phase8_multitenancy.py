"""Phase 8: multi-tenant readiness audit tests.

Verifies that every new targeting-engine function is profile-parameterised
(no hardcoded single-org reads), the cursor is keyed by org_id, and a
second profile with different mission/geography routes independently.
"""

from __future__ import annotations

from utils.discovery.relevance_gate import Lane, gate
from utils.discovery.scoring import match_score, rank_candidates
from utils.discovery.targeted_run import _cursor_state
from utils.discovery.targeting import (
    Candidate,
    CandidateSet,
    TargetingCursor,
    TargetingProfile,
)


# ── Audit: public API accepts TargetingProfile, no global state ───────────────


def test_match_score_is_pure():
    """match_score accepts profile as a parameter — no global reads."""
    p1 = TargetingProfile(ntee_codes=["P"], cause_keywords=["youth"])
    p2 = TargetingProfile(ntee_codes=["B"], cause_keywords=["education"])
    c = Candidate(kind="funder", id="1", name="X", url="https://x.org",
                  state="GA", similarity=0.7, ntee_code="P20",
                  asset_amount=10_000_000, grantee_purposes="youth programs")
    s1 = match_score(c, p1)
    s2 = match_score(c, p2)
    # P1 matches NTEE + keywords → higher score than P2 (no match)
    assert s1 > s2


def test_rank_candidates_different_order_for_different_profiles():
    """Two profiles with different priorities produce different rankings."""
    youth_funder = Candidate(
        kind="funder", id="1", name="Youth Fdn", url="https://y.org",
        state="GA", similarity=0.6,
        ntee_code="P20", grantee_purposes="youth employment programs",
        asset_amount=5_000_000,
    )
    arts_funder = Candidate(
        kind="funder", id="2", name="Arts Fdn", url="https://a.org",
        state="GA", similarity=0.6,
        ntee_code="A30", grantee_purposes="arts and culture grants",
        asset_amount=5_000_000,
    )

    youth_profile = TargetingProfile(ntee_codes=["P"], cause_keywords=["youth"])
    arts_profile = TargetingProfile(ntee_codes=["A"], cause_keywords=["arts", "culture"])

    youth_ranked = rank_candidates([youth_funder, arts_funder], youth_profile)
    arts_ranked = rank_candidates([youth_funder, arts_funder], arts_profile)

    assert youth_ranked[0].id == "1"  # youth funder scores higher for youth profile
    assert arts_ranked[0].id == "2"   # arts funder scores higher for arts profile


def test_gate_routes_by_profile_state(monkeypatch):
    """Gate respects the profile's service_states — two profiles, different outcomes."""
    ga_profile = TargetingProfile(service_states=["GA"])
    hi_profile = TargetingProfile(service_states=["HI"])

    ga_candidate = Candidate(
        kind="funder", id="1", name="GA Fdn", url="https://ga.org",
        state="GA", similarity=0.8,
    )
    ga_candidate.predicted_tier = "eligible"
    ga_candidate.match_score = 0.8

    # GA candidate + HI-only profile → DROP on state mismatch (no I/O needed)
    result_hi = gate(
        ga_candidate, hi_profile,
        sitemap_fn=lambda url: [],
        crawler_fn=lambda url, **kw: None,
    )
    assert result_hi == Lane.DROP

    # GA candidate + GA profile → needs pathway; inject a fake one to get SCRAPE
    ga_candidate.url = "https://ga.org"
    result_ga = gate(
        ga_candidate, ga_profile,
        sitemap_fn=lambda url: ["https://ga.org/grants"],
        crawler_fn=lambda url, **kw: None,
    )
    assert result_ga == Lane.SCRAPE


# ── Cursor is keyed by org_id ─────────────────────────────────────────────────


def test_cursor_keyed_by_org_id():
    """Each profile's cursor is stored under its own org_id key."""
    p1 = TargetingProfile(org_id="org-children")
    p2 = TargetingProfile(org_id="org-environment")
    c1 = TargetingCursor(funder_offset=10, opp_offset=5, geo_broaden_level=0)
    c2 = TargetingCursor(funder_offset=30, opp_offset=0, geo_broaden_level=1)

    state1 = _cursor_state(p1, c1)
    state2 = _cursor_state(p2, c2)

    assert state1["targeting"]["org-children"]["funder_offset"] == 10
    assert state2["targeting"]["org-environment"]["funder_offset"] == 30
    # Keys are isolated — merging both into discovery_state preserves each
    merged = {**state1["targeting"], **state2["targeting"]}
    assert "org-children" in merged
    assert "org-environment" in merged


def test_cursor_default_org_id():
    """TargetingProfile defaults to org_id='default' (single-org placeholder)."""
    p = TargetingProfile()
    assert p.org_id == "default"
    state = _cursor_state(p, TargetingCursor())
    assert "default" in state["targeting"]


# ── load_targeting_profile is the single seam for org reads ──────────────────


def test_load_targeting_profile_is_the_only_org_read():
    """Confirm the audit finding: only load_targeting_profile reads the DB.

    All downstream functions accept a TargetingProfile parameter.
    This test documents the multi-tenancy seam:
      - To support multiple orgs, change load_targeting_profile(org_id) to
        accept an org_id, query organizations WHERE id=org_id, and return
        the per-org profile.
      - targeted_run.run_targeted_path() loops over confirmed profiles.
      - No other function needs changing.
    """
    import inspect
    import utils.discovery.rerank as rerank_mod
    import utils.discovery.relevance_gate as gate_mod
    import utils.discovery.scoring as scoring_mod

    for mod in (rerank_mod, gate_mod, scoring_mod):
        src = inspect.getsource(mod)
        assert "get_supabase" not in src, (
            f"{mod.__name__} must not call get_supabase() — "
            "it should only accept TargetingProfile as a parameter"
        )
        assert ".limit(" not in src, (
            f"{mod.__name__} must not make DB queries"
        )


# ── CandidateSet.all_sorted is stable across profiles ────────────────────────


def test_candidate_set_all_sorted_profile_agnostic():
    """CandidateSet.all_sorted() uses only similarity — profile-independent."""
    funders = [Candidate("funder", "1", "A", None, "GA", 0.9)]
    opps = [Candidate("opportunity", "2", "B", None, None, 0.95)]
    cs = CandidateSet(funders=funders, opportunities=opps)

    # Same result regardless of which profile will later score these
    merged = cs.all_sorted()
    assert merged[0].similarity == 0.95  # opportunity first (higher similarity)
    assert merged[1].similarity == 0.9
