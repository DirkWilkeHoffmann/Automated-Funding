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

    def table(self, name):
        return _FakeQuery(self._rows)


def test_select_enrichment_batch_filters_states():
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
