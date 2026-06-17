"""Unit tests for _tier_from_rubric."""
import pytest
from utils.llm_utils import _tier_from_rubric

_DIMS = [
    "geography", "applicant_type", "topic_focus", "beneficiary",
    "org_history", "grant_size", "cost_share", "explicit_exclusion",
]


def _rubric(overrides: dict) -> dict:
    base = {d: {"verdict": "unknown", "evidence": ""} for d in _DIMS}
    for dim, verdict in overrides.items():
        base[dim] = {"verdict": verdict, "evidence": "test evidence"}
    return base


def test_all_match_highly_eligible():
    assert _tier_from_rubric(_rubric({d: "match" for d in _DIMS})) == "Highly Eligible"


def test_six_match_highly_eligible():
    rubric = _rubric({
        "geography": "match", "applicant_type": "match", "topic_focus": "match",
        "beneficiary": "match", "org_history": "match", "grant_size": "match",
    })
    assert _tier_from_rubric(rubric) == "Highly Eligible"


def test_five_match_no_mismatch_highly_eligible():
    rubric = _rubric({
        "geography": "match", "applicant_type": "match", "topic_focus": "match",
        "beneficiary": "match", "grant_size": "match", "cost_share": "partial",
    })
    # 5 match, 0 mismatch — not ≥6 → Eligible
    assert _tier_from_rubric(rubric) == "Eligible"


def test_three_match_no_mismatch_eligible():
    rubric = _rubric({"geography": "match", "applicant_type": "match", "topic_focus": "match"})
    assert _tier_from_rubric(rubric) == "Eligible"


def test_three_match_one_nv_mismatch_eligible():
    rubric = _rubric({
        "geography": "match", "applicant_type": "match",
        "topic_focus": "match", "grant_size": "mismatch",
    })
    assert _tier_from_rubric(rubric) == "Eligible"


def test_two_match_no_mismatch_possibly_eligible():
    rubric = _rubric({"geography": "match", "applicant_type": "match"})
    assert _tier_from_rubric(rubric) == "Possibly Eligible"


def test_one_match_low():
    assert _tier_from_rubric(_rubric({"geography": "match"})) == "Low Match"


def test_zero_match_low():
    assert _tier_from_rubric(_rubric({})) == "Low Match"


def test_veto_geography_not_eligible():
    rubric = _rubric({
        "geography": "mismatch",
        "applicant_type": "match", "topic_focus": "match",
    })
    assert _tier_from_rubric(rubric) == "Not Eligible"


def test_veto_applicant_type_not_eligible():
    rubric = _rubric({
        "applicant_type": "mismatch",
        "topic_focus": "match", "beneficiary": "match",
    })
    assert _tier_from_rubric(rubric) == "Not Eligible"


def test_veto_topic_focus_not_eligible():
    rubric = _rubric({
        "geography": "match", "applicant_type": "match",
        "org_history": "match", "grant_size": "match", "cost_share": "match",
        "topic_focus": "mismatch",
    })
    assert _tier_from_rubric(rubric) == "Not Eligible"


def test_veto_beneficiary_not_eligible():
    rubric = _rubric({
        "geography": "match", "applicant_type": "match", "topic_focus": "match",
        "org_history": "match", "grant_size": "match", "cost_share": "match",
        "beneficiary": "mismatch",
    })
    assert _tier_from_rubric(rubric) == "Not Eligible"


def test_veto_org_history_not_eligible():
    assert _tier_from_rubric(_rubric({"org_history": "mismatch"})) == "Not Eligible"


def test_veto_cost_share_not_eligible():
    assert _tier_from_rubric(_rubric({"cost_share": "mismatch"})) == "Not Eligible"


def test_veto_explicit_exclusion_not_eligible():
    assert _tier_from_rubric(_rubric({"explicit_exclusion": "mismatch"})) == "Not Eligible"


def test_empty_rubric_low_match():
    assert _tier_from_rubric({}) == "Low Match"


def test_partial_verdicts_not_eligible_threshold():
    rubric = _rubric({d: "partial" for d in _DIMS})
    assert _tier_from_rubric(rubric) == "Low Match"


def test_partial_topic_focus_caps_eligible_to_possibly():
    """Off-domain funds with many other matches must not exceed 'Possibly Eligible'."""
    rubric = _rubric({
        "geography": "match", "applicant_type": "match",
        "topic_focus": "partial",   # e.g. fire management that mentions 'training'
        "beneficiary": "match", "org_history": "match", "grant_size": "match",
    })
    assert _tier_from_rubric(rubric) == "Possibly Eligible"


def test_partial_topic_focus_caps_highly_eligible_to_possibly():
    rubric = _rubric({d: "match" for d in _DIMS if d != "topic_focus"} | {"topic_focus": "partial"})
    assert _tier_from_rubric(rubric) == "Possibly Eligible"


def test_match_topic_focus_allows_eligible():
    """Full topic match should still produce 'Eligible' normally."""
    rubric = _rubric({"geography": "match", "applicant_type": "match", "topic_focus": "match"})
    assert _tier_from_rubric(rubric) == "Eligible"
