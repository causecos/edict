from __future__ import annotations

import os

from edict.backend.app.config import get_settings


def discover_api_key() -> str:
    """Resolve the backend API key for live integration tests.

    Preference order:
    1. EDICT_API_KEY in the current pytest process
    2. Backend Settings() loaded from the repo-local backend .env
    """
    key = os.environ.get("EDICT_API_KEY", "").strip()
    if key:
        return key

    try:
        return (get_settings().api_key or "").strip()
    except Exception:
        return ""



def api_key_headers() -> dict[str, str]:
    key = discover_api_key()
    return {"X-API-Key": key} if key else {}
