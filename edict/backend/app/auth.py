"""Edict Backend API Key 認證模組。

使用共享密鑰 (API Key) 保護寫入端點。
GET 端點保持開放以供 Dashboard 讀取。
"""

import logging
import secrets
from functools import lru_cache

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer

from .config import get_settings

log = logging.getLogger("edict.auth")

# Bearer token scheme for API key
_api_key_scheme = HTTPBearer(auto_error=False)


def _extract_api_key(request: Request) -> str | None:
    """從 request 中提取 API Key。

    優先級：Authorization: Bearer <key> > X-API-Key header
    """
    # Try X-API-Key header first (simpler for scripts)
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key.strip()

    # Try Bearer token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()

    return None


def require_api_key(request: Request) -> str:
    """FastAPI dependency：驗證 API Key。

    用於保護 POST/PUT/DELETE 端點。
    若未設定 API_KEY 環境變數則略過驗證（開發/向後相容模式）。

    Returns:
        通過驗證的 API key
    """
    settings = get_settings()
    expected_key = settings.api_key

    # 若未設定 API_KEY，略過驗證（開發模式）
    if not expected_key:
        log.warning("API_KEY not set — all write endpoints are unprotected")
        return ""

    provided_key = _extract_api_key(request)
    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key header or Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return provided_key


@lru_cache
def generate_api_key() -> str:
    """生成一個安全的隨機 API Key（僅供初次設定參考）。"""
    return secrets.token_urlsafe(32)
