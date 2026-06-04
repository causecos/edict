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

# Bearer token scheme for API key — auto_error=False 避免未帶 token 時自動 403
# 實際驗證邏輯由 require_api_key dependency 控制（未設定 API_KEY 時略過）
_api_key_scheme = HTTPBearer(auto_error=False)


def _extract_api_key(request: Request) -> str | None:
    """從 request 中提取 API Key。

    優先級：Authorization: Bearer *** > X-API-Key header
    X-API-Key 放在前面方便 curl 腳本直接使用。
    提取後做 strip() 防止前後空白導致比對失敗。
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
    """FastAPI dependency：驗證 API Key，用於保護 POST/PUT/DELETE 端點。

    驗證流程：
    1. 若未設定 API_KEY → 開發模式，略過驗證（logging warning）
    2. 從 request 提取 key（優先 X-API-Key，其次 Bearer）
    3. 使用 secrets.compare_digest 常數時間比對，防止 timing attack
    4. 驗證失敗 → 401 Unauthorized

    Returns:
        通過驗證的 API key（字串）
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

    # secrets.compare_digest: 常數時間字串比對，防止 timing side-channel
    if not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return provided_key


@lru_cache
def generate_api_key() -> str:
    """生成一個安全的隨機 API Key（256-bit，僅供初次設定參考）。

    使用 lru_cache 確保同一次啟動只生成一個值。
    """
    return secrets.token_urlsafe(32)
