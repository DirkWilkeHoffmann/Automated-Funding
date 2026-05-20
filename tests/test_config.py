import importlib
import sys


def _load_config_module(monkeypatch, *, supabase_url=None, supabase_service_key=None):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", supabase_url or "https://example.supabase.co")
    monkeypatch.setenv(
        "SUPABASE_SERVICE_KEY", supabase_service_key or "service-role-key-value"
    )

    sys.modules.pop("api.config", None)
    module = importlib.import_module("api.config")
    return importlib.reload(module)


def test_load_requires_supabase_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "some-key")
    sys.modules.pop("api.config", None)
    import pytest
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        importlib.import_module("api.config")


def test_load_requires_supabase_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    sys.modules.pop("api.config", None)
    import pytest
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_KEY"):
        importlib.import_module("api.config")


def test_load_sets_supabase_fields(monkeypatch):
    config = _load_config_module(
        monkeypatch,
        supabase_url="https://myproject.supabase.co",
        supabase_service_key="secret-key",
    )
    assert config.settings.supabase_url == "https://myproject.supabase.co"
    assert config.settings.supabase_service_key == "secret-key"


def test_load_openai_key_optional(monkeypatch):
    config = _load_config_module(monkeypatch)
    assert config.settings.openai_api_key is None
