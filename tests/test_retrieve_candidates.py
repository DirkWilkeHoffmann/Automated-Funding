"""Tests for Phase 4: targeting cursor + candidate retrieval."""

import utils.discovery.targeting as tgt
from utils.discovery.targeting import (
    Candidate,
    CandidateSet,
    TargetingCursor,
    TargetingProfile,
    _states_for_level,
    load_cursor,
    retrieve_candidates,
    save_cursor,
)

# ── _states_for_level ─────────────────────────────────────────────────────────


def test_level_0_returns_exact_states():
    assert _states_for_level(["GA", "FL"], 0) == ["GA", "FL"]


def test_level_1_adds_neighbours():
    result = _states_for_level(["GA"], 1)
    assert "GA" in result
    assert "AL" in result  # neighbour of GA
    assert "FL" in result


def test_level_2_returns_none_no_filter():
    assert _states_for_level(["GA"], 2) is None


def test_empty_base_returns_none():
    assert _states_for_level([], 0) is None
    assert _states_for_level([], 1) is None


# ── TargetingCursor ───────────────────────────────────────────────────────────


def test_cursor_defaults():
    c = TargetingCursor()
    assert c.funder_offset == 0
    assert c.opp_offset == 0
    assert c.geo_broaden_level == 0


# ── load_cursor / save_cursor ─────────────────────────────────────────────────


def test_load_cursor_missing_slot(monkeypatch):
    monkeypatch.setattr(tgt, "load_discovery_state", lambda: {}, raising=False)
    # Patch via config_store module since load_cursor imports at call time
    import utils.discovery.config_store as cs
    monkeypatch.setattr(cs, "load_discovery_state", lambda: {})
    profile = TargetingProfile(org_id="default")
    cursor = load_cursor(profile)
    assert cursor.funder_offset == 0
    assert cursor.geo_broaden_level == 0


def test_load_cursor_existing_slot(monkeypatch):
    import utils.discovery.config_store as cs
    monkeypatch.setattr(
        cs, "load_discovery_state",
        lambda: {"targeting": {"org-1": {"funder_offset": 50, "opp_offset": 20, "geo_broaden_level": 1}}},
    )
    profile = TargetingProfile(org_id="org-1")
    cursor = load_cursor(profile)
    assert cursor.funder_offset == 50
    assert cursor.opp_offset == 20
    assert cursor.geo_broaden_level == 1


def test_save_cursor_writes_slot(monkeypatch):
    import utils.discovery.config_store as cs
    saved = {}

    def _fake_load():
        return dict(saved)

    def _fake_save(state):
        saved.update(state)

    monkeypatch.setattr(cs, "load_discovery_state", _fake_load)
    monkeypatch.setattr(cs, "save_discovery_state", _fake_save)

    profile = TargetingProfile(org_id="org-2")
    cursor = TargetingCursor(funder_offset=30, opp_offset=10, geo_broaden_level=0)
    save_cursor(profile, cursor)

    assert saved["targeting"]["org-2"]["funder_offset"] == 30
    assert saved["targeting"]["org-2"]["opp_offset"] == 10


def test_save_cursor_preserves_other_org(monkeypatch):
    import utils.discovery.config_store as cs
    initial = {"targeting": {"org-1": {"funder_offset": 99, "opp_offset": 5, "geo_broaden_level": 0}}}
    saved = {}

    monkeypatch.setattr(cs, "load_discovery_state", lambda: dict(initial))
    monkeypatch.setattr(cs, "save_discovery_state", lambda s: saved.update(s))

    save_cursor(TargetingProfile(org_id="org-2"), TargetingCursor(funder_offset=10))
    # org-1 slot should still be there
    assert saved["targeting"]["org-1"]["funder_offset"] == 99


# ── retrieve_candidates ───────────────────────────────────────────────────────


def _make_funder_row(ein, similarity=0.9, state="GA"):
    return {
        "ein": ein, "name": f"Foundation {ein}", "city": "Atlanta",
        "state": state, "ntee_code": "P20", "asset_amount": 1_000_000,
        "website": f"https://f{ein}.org", "program_areas": ["Youth"],
        "grantee_purposes": "youth programs", "similarity": similarity,
    }


def _make_opp_row(opp_id, similarity=0.8):
    return {
        "opportunity_id": opp_id, "title": f"Grant {opp_id}", "agency": "HHS",
        "url": f"https://grants.gov/{opp_id}", "close_date": "2026-12-31",
        "award_ceiling": 500_000, "cfda_number": "93.123",
        "category": "HL", "similarity": similarity,
    }


class _FakeRPC:
    def __init__(self, rows):
        self._rows = rows

    def execute(self):
        class _R:
            pass
        r = _R()
        r.data = self._rows
        return r


class _FakeSB:
    def __init__(self, funder_rows, opp_rows):
        self._funder_rows = funder_rows
        self._opp_rows = opp_rows
        self.calls = []

    def rpc(self, fn_name, params):
        self.calls.append((fn_name, dict(params)))
        if fn_name == "match_funders":
            return _FakeRPC(self._funder_rows)
        return _FakeRPC(self._opp_rows)


def test_retrieve_candidates_no_embedding():
    profile = TargetingProfile(client_embedding=None)
    cursor = TargetingCursor()
    result, new_cursor = retrieve_candidates(profile, cursor, limit=10, sb=object())
    assert result.funders == []
    assert result.opportunities == []
    assert new_cursor.funder_offset == 0


def test_retrieve_candidates_happy_path():
    profile = TargetingProfile(
        client_embedding=[0.1] * 1536,
        service_states=["GA"],
    )
    cursor = TargetingCursor(funder_offset=0, opp_offset=0)
    funder_rows = [_make_funder_row(str(i)) for i in range(5)]
    opp_rows = [_make_opp_row(str(i)) for i in range(2)]
    sb = _FakeSB(funder_rows, opp_rows)

    result, new_cursor = retrieve_candidates(profile, cursor, limit=10, sb=sb)

    assert len(result.funders) == 5
    assert len(result.opportunities) == 2
    assert all(c.kind == "funder" for c in result.funders)
    assert all(c.kind == "opportunity" for c in result.opportunities)


def test_retrieve_candidates_advances_offset():
    profile = TargetingProfile(client_embedding=[0.0] * 1536)
    cursor = TargetingCursor(funder_offset=0)
    funder_rows = [_make_funder_row(str(i)) for i in range(10)]
    sb = _FakeSB(funder_rows, [])

    _, new_cursor = retrieve_candidates(profile, cursor, limit=12, sb=sb)
    assert new_cursor.funder_offset == 10


def test_retrieve_candidates_rotation_different_results():
    """Two calls with advancing cursor pass different offsets to the RPC."""
    profile = TargetingProfile(client_embedding=[0.0] * 1536)
    cursor = TargetingCursor(funder_offset=0)
    funder_rows = [_make_funder_row(str(i)) for i in range(10)]
    sb = _FakeSB(funder_rows, [])

    _, cursor2 = retrieve_candidates(profile, cursor, limit=10, sb=sb)
    assert cursor2.funder_offset == 10

    sb2 = _FakeSB(funder_rows, [])
    _, cursor3 = retrieve_candidates(profile, cursor2, limit=10, sb=sb2)
    # Second call passed offset=10 to the RPC
    assert sb2.calls[0][1]["funder_offset"] == 10
    assert cursor3.funder_offset == 20


def test_retrieve_candidates_reset_on_empty():
    """When RPC returns nothing, offset resets to 0."""
    profile = TargetingProfile(client_embedding=[0.0] * 1536)
    cursor = TargetingCursor(funder_offset=500)
    sb = _FakeSB([], [])

    _, new_cursor = retrieve_candidates(profile, cursor, limit=10, sb=sb)
    assert new_cursor.funder_offset == 0


def test_retrieve_candidates_broadens_geo(monkeypatch):
    """When geo-tight search returns sparse results, broadening is triggered."""
    profile = TargetingProfile(
        client_embedding=[0.0] * 1536,
        service_states=["HI"],  # Hawaii — very small pool
    )
    cursor = TargetingCursor(funder_offset=0, geo_broaden_level=0)

    call_log = []

    class _BroadenSB:
        def rpc(self, fn_name, params):
            call_log.append((fn_name, params.get("filter_states")))
            # Return sparse (1 row) for level 0, enough for level 1+
            if fn_name == "match_funders":
                states = params.get("filter_states")
                rows = [_make_funder_row("1")] if states == ["HI"] else [_make_funder_row(str(i)) for i in range(10)]
            else:
                rows = []
            return _FakeRPC(rows)

    result, new_cursor = retrieve_candidates(profile, cursor, limit=10, sb=_BroadenSB())
    # Should have broadened (final level > 0)
    assert new_cursor.geo_broaden_level >= 1
    assert len(result.funders) > 1


def test_candidate_set_all_sorted():
    funders = [Candidate("funder", "1", "A", None, "GA", 0.9)]
    opps = [Candidate("opportunity", "2", "B", None, None, 0.95)]
    cs = CandidateSet(funders=funders, opportunities=opps)
    merged = cs.all_sorted()
    assert merged[0].similarity == 0.95
    assert merged[1].similarity == 0.9


def test_retrieve_candidates_geo_filter_passed_to_rpc():
    """State filter is forwarded to match_funders when profile has states."""
    profile = TargetingProfile(
        client_embedding=[0.0] * 1536,
        service_states=["GA", "FL"],
    )
    cursor = TargetingCursor()
    sb = _FakeSB([_make_funder_row("1")], [])

    retrieve_candidates(profile, cursor, limit=10, sb=sb)

    funder_call_params = sb.calls[0][1]
    assert "filter_states" in funder_call_params
    assert set(funder_call_params["filter_states"]) == {"GA", "FL"}
