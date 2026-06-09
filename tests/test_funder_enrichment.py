"""Unit tests for funder enrichment (pure builders + job helpers, all mocked)."""
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
