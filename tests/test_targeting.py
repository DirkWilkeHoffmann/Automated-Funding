import utils.discovery.targeting as tgt
from utils.discovery.targeting import TargetingProfile, derive_targeting, build_client_embedding
from utils.discovery.prefilter import OrgProfile


# ── TargetingProfile construction ────────────────────────────────────────────


def test_from_org_row_empty():
    profile = TargetingProfile.from_org_row(None)
    assert profile.org_id == "default"
    assert profile.cause_keywords == []
    assert profile.targeting_confirmed is False
    assert profile.client_embedding is None


def test_from_org_row_full():
    row = {
        "id": "abc-123",
        "mission": "Youth workforce development",
        "services": ["job training", "placement"],
        "ntee_codes": ["J", "P"],
        "service_states": ["GA", "FL"],
        "cfda_categories": ["ELT", "ISS"],
        "eligible_applicant_codes": ["12"],
        "applicant_types": ["501c3"],
        "accepts_unsolicited": True,
        "can_cost_share": False,
        "min_grant_size": 5000,
        "max_grant_size": None,
        "state": "GA",
        "cause_keywords": ["youth", "employment"],
        "targeting_confirmed": True,
        "client_embedding": [0.1] * 1536,
    }
    profile = TargetingProfile.from_org_row(row)
    assert profile.org_id == "abc-123"
    assert profile.mission == "Youth workforce development"
    assert profile.cause_keywords == ["youth", "employment"]
    assert profile.targeting_confirmed is True
    assert len(profile.client_embedding) == 1536


def test_from_org_profile_roundtrip():
    org = OrgProfile(
        mission="Community health services",
        services=["primary care", "mental health"],
        ntee_codes=["E", "F"],
        service_states=["NC"],
    )
    profile = TargetingProfile.from_org_profile(
        org, org_id="org-1", cause_keywords=["health equity"]
    )
    assert profile.mission == "Community health services"
    assert "NC" in profile.effective_states()
    assert profile.cause_keywords == ["health equity"]


def test_effective_states_uses_service_states():
    profile = TargetingProfile(service_states=["GA", "FL"], state="TX")
    assert profile.effective_states() == ["GA", "FL"]


def test_effective_states_falls_back_to_state():
    profile = TargetingProfile(service_states=[], state="ca")
    assert profile.effective_states() == ["CA"]


def test_effective_states_empty():
    profile = TargetingProfile()
    assert profile.effective_states() == []


def test_embedding_input_text_all_fields():
    profile = TargetingProfile(
        mission="Youth workforce training",
        cause_keywords=["job skills", "employment"],
        services=["career coaching"],
    )
    text = profile.embedding_input_text()
    assert "Youth workforce training" in text
    assert "job skills" in text
    assert "career coaching" in text


def test_embedding_input_text_empty():
    profile = TargetingProfile()
    assert profile.embedding_input_text() == ""


# ── derive_targeting ─────────────────────────────────────────────────────────


class _FakeChoice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeChat:
    def __init__(self, content):
        self._content = content

    def create(self, **_kwargs):
        return _FakeResp(self._content)


class _FakeClient:
    def __init__(self, content):
        self.chat = type("C", (), {"completions": _FakeChat(content)})()


def test_derive_targeting_happy_path(monkeypatch):
    payload = """{
        "ntee_prefixes": ["P", "O"],
        "cfda_categories": ["ISS", "ELT"],
        "cause_keywords": ["youth employment", "job training"],
        "applicant_codes": ["12"],
        "notes": "Strong workforce focus"
    }"""
    monkeypatch.setattr(tgt, "get_client", lambda: _FakeClient(payload))
    result = derive_targeting("We help youth get jobs")
    assert result["ntee_prefixes"] == ["P", "O"]
    assert result["cfda_categories"] == ["ISS", "ELT"]
    assert "youth employment" in result["cause_keywords"]
    assert result["applicant_codes"] == ["12"]
    assert result["notes"] == "Strong workforce focus"


def test_derive_targeting_no_client(monkeypatch):
    monkeypatch.setattr(tgt, "get_client", lambda: None)
    result = derive_targeting("Some mission")
    assert result["ntee_prefixes"] == []
    assert "No OpenAI" in result["notes"]


def test_derive_targeting_malformed_json(monkeypatch):
    monkeypatch.setattr(tgt, "get_client", lambda: _FakeClient("not json {{{"))
    result = derive_targeting("Some mission")
    assert result["ntee_prefixes"] == []
    assert result["notes"] != ""


def test_derive_targeting_applicant_codes_zero_padded(monkeypatch):
    payload = '{"ntee_prefixes":[],"cfda_categories":[],"cause_keywords":[],"applicant_codes":[12],"notes":""}'
    monkeypatch.setattr(tgt, "get_client", lambda: _FakeClient(payload))
    result = derive_targeting("Any mission")
    assert result["applicant_codes"] == ["12"]


# ── build_client_embedding ───────────────────────────────────────────────────


def test_build_client_embedding_returns_vector(monkeypatch):
    monkeypatch.setattr(tgt, "build_client_embedding",
                        lambda p: [0.5] * 1536 if p.embedding_input_text() else None)
    profile = TargetingProfile(mission="Youth jobs", cause_keywords=["employment"])
    vec = tgt.build_client_embedding(profile)
    assert vec is None or len(vec) == 1536


def test_build_client_embedding_empty_profile(monkeypatch):
    # Real call with mocked embed_text
    import utils.discovery.embeddings as emb

    monkeypatch.setattr(emb, "embed_text", lambda t: [0.1] * 1536)
    profile = TargetingProfile()
    vec = build_client_embedding(profile)
    assert vec is None
