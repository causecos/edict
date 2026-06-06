from __future__ import annotations

import importlib


def test_discover_api_key_prefers_env(monkeypatch):
    monkeypatch.setenv("EDICT_API_KEY", "from-env")
    api_auth = importlib.import_module("tests.api_auth")

    assert api_auth.discover_api_key() == "from-env"



def test_discover_api_key_falls_back_to_backend_settings(monkeypatch):
    monkeypatch.delenv("EDICT_API_KEY", raising=False)
    api_auth = importlib.import_module("tests.api_auth")

    class DummySettings:
        api_key = "from-settings"

    monkeypatch.setattr(api_auth, "get_settings", lambda: DummySettings())

    assert api_auth.discover_api_key() == "from-settings"



def test_api_key_headers_returns_x_api_key_header(monkeypatch):
    monkeypatch.delenv("EDICT_API_KEY", raising=False)
    api_auth = importlib.import_module("tests.api_auth")

    class DummySettings:
        api_key = "header-secret"

    monkeypatch.setattr(api_auth, "get_settings", lambda: DummySettings())

    assert api_auth.api_key_headers() == {"X-API-Key": "header-secret"}
