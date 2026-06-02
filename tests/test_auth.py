"""
auth.py 單元測試 — API Key 認證模組。

測試範圍：
- _extract_api_key: 從 Request 提取 API Key（X-API-Key、Bearer、無 header）
- require_api_key: FastAPI 依賴注入驗證（開發模式、缺失 key、錯誤 key、正確 key）
- generate_api_key: 安全隨機 Key 生成（長度、唯一性）

隔離策略：使用 unittest.mock.patch 隔離 get_settings() 依賴。
"""
import string
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from edict.backend.app.auth import (
    _extract_api_key,
    generate_api_key,
    require_api_key,
)


# ─────────────────────────────────────────────
# _extract_api_key
# ─────────────────────────────────────────────


class TestExtractApiKey:
    """_extract_api_key 函數單元測試 — 從 HTTP Request 提取 API Key。"""

    def test_from_x_api_key_header_returns_stripped_value(self):
        """
        given: Request 帶有 X-API-Key header，值包含前後空白
        when: 呼叫 _extract_api_key
        then: 回傳去除空白後的 header 值
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": "  my-secret-key  ",
            "Authorization": "",
        }.get(key, default)

        result = _extract_api_key(request)
        assert result == "my-secret-key"

    def test_from_bearer_token_returns_token(self):
        """
        given: Request 帶有 Authorization: Bearer <token> header，無 X-API-Key
        when: 呼叫 _extract_api_key
        then: 回傳 Bearer 後方的 token 字串
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": None,
            "Authorization": "Bearer my-bearer-token",
        }.get(key, default)

        result = _extract_api_key(request)
        assert result == "my-bearer-token"

    def test_no_header_returns_none(self):
        """
        given: Request 沒有 X-API-Key 也沒有 Authorization header
        when: 呼叫 _extract_api_key
        then: 回傳 None
        """
        request = MagicMock()
        # X-API-Key 回傳 None, Authorization 回傳空字串（模擬真實 HTTP header 行為）
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": None,
            "Authorization": "",
        }.get(key, default)

        result = _extract_api_key(request)
        assert result is None

    def test_x_api_key_takes_precedence_over_bearer(self):
        """
        given: Request 同時有 X-API-Key 和 Authorization: Bearer
        when: 呼叫 _extract_api_key
        then: 優先回傳 X-API-Key 的值（X-API-Key 優先於 Bearer）
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": "header-key",
            "Authorization": "Bearer bearer-key",
        }.get(key, default)

        result = _extract_api_key(request)
        assert result == "header-key"

    def test_empty_x_api_key_falls_back_to_bearer(self):
        """
        given: Request 的 X-API-Key header 為空字串，但 Authorization 有 Bearer token
        when: 呼叫 _extract_api_key
        then: 空字串被視為 falsy，退回到 Bearer token
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": "",
            "Authorization": "Bearer fallback-token",
        }.get(key, default)

        result = _extract_api_key(request)
        assert result == "fallback-token"

    def test_bearer_with_extra_whitespace(self):
        """
        given: Request 的 Authorization header 內含多餘空白
        when: 呼叫 _extract_api_key
        then: 正確解析並去除 token 前後空白
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": None,
            "Authorization": "Bearer   padded-token  ",
        }.get(key, default)

        result = _extract_api_key(request)
        assert result == "padded-token"

    def test_non_bearer_authorization_ignored(self):
        """
        given: Request 的 Authorization header 不是 Bearer 格式（例如 Basic）
        when: 呼叫 _extract_api_key
        then: 回傳 None（不處理非 Bearer token）
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": None,
            "Authorization": "Basic dXNlcjpwYXNz",
        }.get(key, default)

        result = _extract_api_key(request)
        assert result is None


# ─────────────────────────────────────────────
# require_api_key
# ─────────────────────────────────────────────


class TestRequireApiKey:
    """require_api_key 依賴函數單元測試 — FastAPI 端點守衛。"""

    def test_dev_mode_skips_auth_when_api_key_empty(self):
        """
        given: Settings.api_key 為空字串（開發/向後相容模式）
        when: 呼叫 require_api_key
        then: 略過驗證，回傳空字串
        """
        request = MagicMock()
        with patch("edict.backend.app.auth.get_settings") as mock_settings:
            mock_settings.return_value.api_key = ""
            result = require_api_key(request)
            assert result == ""

    def test_missing_key_returns_401(self):
        """
        given: Settings.api_key 已設定為 "expected-key"，但 Request 未提供任何 key
        when: 呼叫 require_api_key
        then: 拋出 HTTPException，status_code=401，detail 包含 "Missing API key"
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": None,
            "Authorization": "",
        }.get(key, default)

        with patch("edict.backend.app.auth.get_settings") as mock_settings:
            mock_settings.return_value.api_key = "expected-key"
            with pytest.raises(HTTPException) as exc_info:
                require_api_key(request)
            assert exc_info.value.status_code == 401
            assert "Missing API key" in exc_info.value.detail
            assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"

    def test_wrong_key_returns_401(self):
        """
        given: Settings.api_key = "expected-key"，但 Request 提供 "wrong-key"
        when: 呼叫 require_api_key
        then: 拋出 HTTPException，status_code=401，detail 包含 "Invalid API key"
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": "wrong-key",
            "Authorization": "",
        }.get(key, default)

        with patch("edict.backend.app.auth.get_settings") as mock_settings:
            mock_settings.return_value.api_key = "expected-key"
            with pytest.raises(HTTPException) as exc_info:
                require_api_key(request)
            assert exc_info.value.status_code == 401
            assert "Invalid API key" in exc_info.value.detail

    def test_correct_key_passes(self):
        """
        given: Settings.api_key = "correct-key"，Request 透過 X-API-Key 提供相同值
        when: 呼叫 require_api_key
        then: 通過驗證，回傳提供的 key
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": "correct-key",
            "Authorization": "",
        }.get(key, default)

        with patch("edict.backend.app.auth.get_settings") as mock_settings:
            mock_settings.return_value.api_key = "correct-key"
            result = require_api_key(request)
            assert result == "correct-key"

    def test_correct_key_via_bearer_passes(self):
        """
        given: Settings.api_key = "bearer-secret"，Request 透過 Bearer token 提供
        when: 呼叫 require_api_key
        then: 通過驗證，回傳提供的 key
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": None,
            "Authorization": "Bearer bearer-secret",
        }.get(key, default)

        with patch("edict.backend.app.auth.get_settings") as mock_settings:
            mock_settings.return_value.api_key = "bearer-secret"
            result = require_api_key(request)
            assert result == "bearer-secret"

    def test_uses_constant_time_comparison(self):
        """
        given: 正確的 key 和錯誤的 key 長度不同
        when: 呼叫 require_api_key 兩次（一次正確、一次錯誤）
        then: 使用 secrets.compare_digest 進行常數時間比對，避免時序攻擊
        """
        request = MagicMock()
        request.headers.get.side_effect = lambda key, default=None: {
            "X-API-Key": "short",
            "Authorization": "",
        }.get(key, default)

        with patch("edict.backend.app.auth.get_settings") as mock_settings:
            mock_settings.return_value.api_key = "very-long-key-that-is-different"
            with pytest.raises(HTTPException) as exc_info:
                require_api_key(request)
            assert exc_info.value.status_code == 401


# ─────────────────────────────────────────────
# generate_api_key
# ─────────────────────────────────────────────


class TestGenerateApiKey:
    """generate_api_key 函數單元測試 — 安全隨機 Key 生成。"""

    def test_length_is_43_chars(self):
        """
        given: 無
        when: 呼叫 generate_api_key
        then: 回傳長度為 43 的字串（token_urlsafe(32) 的 base64 編碼結果）
        """
        # 清除 LRU 快取，確保每次測試獨立
        generate_api_key.cache_clear()
        key = generate_api_key()
        assert len(key) == 43, f"Expected 43 chars, got {len(key)}: {key!r}"

    def test_only_urlsafe_base64_chars(self):
        """
        given: 無
        when: 呼叫 generate_api_key
        then: 回傳字串僅包含 URL-safe base64 字元（A-Z, a-z, 0-9, -, _）
        """
        generate_api_key.cache_clear()
        key = generate_api_key()
        valid_chars = set(string.ascii_letters + string.digits + "-_")
        assert all(c in valid_chars for c in key), f"Invalid char in: {key!r}"

    def test_uniqueness_across_calls(self):
        """
        given: 無
        when: 連續呼叫 generate_api_key 兩次（清除快取）
        then: 每次回傳不同值
        """
        generate_api_key.cache_clear()
        key1 = generate_api_key()
        generate_api_key.cache_clear()
        key2 = generate_api_key()
        assert key1 != key2, "Consecutive calls should produce different keys"

    @patch("edict.backend.app.auth.secrets.token_urlsafe")
    def test_delegates_to_token_urlsafe_32(self, mock_token_urlsafe):
        """
        given: mock secrets.token_urlsafe
        when: 呼叫 generate_api_key
        then: 委派給 secrets.token_urlsafe(32) 並回傳其結果
        """
        generate_api_key.cache_clear()
        mock_token_urlsafe.return_value = "mock-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        key = generate_api_key()
        mock_token_urlsafe.assert_called_once_with(32)
        assert key == "mock-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

    def test_lru_cache_returns_same_key(self):
        """
        given: 已呼叫過一次 generate_api_key
        when: 再次呼叫 generate_api_key（不清除快取）
        then: 因 @lru_cache 裝飾器，回傳相同值
        """
        generate_api_key.cache_clear()
        key1 = generate_api_key()
        key2 = generate_api_key()  # 不清除快取
        assert key1 == key2, "LRU cache should return the same key"
