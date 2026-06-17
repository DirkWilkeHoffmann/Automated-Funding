# tests/test_pipeline.py
"""Integration tests for the two-stage pipeline (mocked LLM)."""
import json
import pytest
from unittest.mock import patch, MagicMock
from utils.constants.llm import LLM_PROMPT_STAGE1, LLM_PROMPT_STAGE2, PHASE2_PROMOTE_TIERS


# ── Prompt construction tests ─────────────────────────────────────────────────

def test_stage1_prompt_has_no_org_data():
    """Stage 1 prompt template must not reference org-specific placeholders."""
    assert "{org_profile}" not in LLM_PROMPT_STAGE1
    assert "Work4ALiving" not in LLM_PROMPT_STAGE1
    assert "501c3" not in LLM_PROMPT_STAGE1


def test_stage1_prompt_has_text_placeholder():
    assert "{text}" in LLM_PROMPT_STAGE1


def test_stage2_prompt_has_org_profile_placeholder():
    assert "{org_profile}" in LLM_PROMPT_STAGE2


def test_stage2_prompt_has_stage1_fact_placeholders():
    for field in ["{geographic_scope}", "{applicant_types}", "{funding_range}"]:
        assert field in LLM_PROMPT_STAGE2, f"Missing {field} in Stage 2 prompt"


def test_stage1_example_values_not_w4al_data():
    """Example values in Stage 1 template must not be W4AL's real org data."""
    forbidden = [
        "501(c)(3) nonprofits",
        "workforce development organisations",
        "unemployed adults",
    ]
    for val in forbidden:
        assert val not in LLM_PROMPT_STAGE1, f"W4AL data '{val}' found in Stage 1 template"


def test_low_match_not_in_phase2_tiers():
    assert "Low Match" not in PHASE2_PROMOTE_TIERS


def test_not_eligible_not_in_phase2_tiers():
    assert "Not Eligible" not in PHASE2_PROMOTE_TIERS


# ── stage1_extract mock tests ─────────────────────────────────────────────────

def _mock_openai_response(content: dict):
    mock = MagicMock()
    mock.choices[0].message.content = json.dumps(content)
    return mock


def test_stage1_extract_returns_structured_facts():
    from utils.llm_utils import stage1_extract

    fake_s1 = {
        "fund_name": "Community Grant",
        "funder_name": "Acme Foundation",
        "geographic_scope": "South Africa",
        "us_state_scope": [],
        "applicant_types": ["registered NPOs"],
        "topic_areas": ["workforce development"],
        "beneficiaries": ["unemployed youth"],
        "funding_range": "R50,000–R200,000",
        "deadline": "31-Aug-2026",
        "application_status": "open",
        "restrictions": [],
        "grant_type": "foundation",
        "application_process": "Online portal",
        "notes": "",
    }

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response(fake_s1)

    result = stage1_extract("Some fund page text here.", client=mock_client)

    assert result["fund_name_extracted"] == "Community Grant"
    assert result["geographic_scope"] == "South Africa"
    assert result["applicant_types_list"] == ["registered NPOs"]
    assert result["application_status"] == "open"


def test_stage1_extract_cleans_invalid_status():
    from utils.llm_utils import stage1_extract

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response({
        "application_status": "OPEN NOW",
        "geographic_scope": "Kenya",
    })
    result = stage1_extract("text", client=mock_client)
    assert result["application_status"] == "unclear"


# ── Listing page pipeline test ────────────────────────────────────────────────

def test_listing_page_detection_returns_skipped():
    """When detect_listing_page fires, process_single_fund returns early without LLM calls."""
    from utils.scrape_worker import process_single_fund

    with patch("utils.scrape_worker.prioritized_crawl") as mock_crawl, \
         patch("utils.scrape_worker.detect_listing_page", return_value=True), \
         patch("utils.scrape_worker.extract_listing_urls", return_value=[{"url": "https://fund.example.com", "title": "A Fund"}]), \
         patch("utils.scrape_worker._upsert_pending", return_value=1), \
         patch("utils.scrape_worker.call_llm_extract") as mock_llm, \
         patch("utils.scrape_worker._grants_gov_detail_text", return_value=None):

        mock_crawl.return_value = ("listing page text " * 50, "/tmp", 1, ["https://listing.example.com"], {})

        result = process_single_fund("https://listing.example.com", persist=False)

        assert result.get("skipped") == "listing_page"
        mock_llm.assert_not_called()


# ── Stage 2 failure graceful degradation ─────────────────────────────────────

def test_stage2_failure_produces_unclear_eligibility():
    from utils.llm_utils import stage2_evaluate

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API timeout")

    result = stage2_evaluate(
        {"geographic_scope": "South Africa", "applicant_types_list": []},
        "org profile text",
        {"verdict": "match", "evidence": "test"},
        client=mock_client,
    )
    assert result["eligibility"] == "unclear"
    assert result["match_rubric"] == {}
