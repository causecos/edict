"""
config.py 單元測試 — Edict 配置管理模組。

測試範圍：
- Settings 預設值：postgres_password 動態生成 64 字元 hex、api_key 預設空字串、redis_url 預設值
- DATABASE_URL 環境變數覆蓋 database_url / database_url_sync property
- get_settings LRU 快取行為

隔離策略：透過 monkeypatch 設置/清除環境變數，每個測試獨立。
"""
import os
import re
from unittest.mock import patch

import pytest

from edict.backend.app.config import Settings, get_settings


# ─────────────────────────────────────────────
# 預設值測試
# ─────────────────────────────────────────────


class TestSettingsDefaults:
    """Settings 預設值單元測試。"""

    def test_postgres_password_default_is_64_hex_chars(self):
        """
        given: 未設置 POSTGRES_PASSWORD 環境變數
        when: 建立 Settings 實例（跳過 .env 檔案載入）
        then: postgres_password 為 _generate_secret 動態生成的 64 字元 hex 字串
        """
        settings = Settings(_env_file=None)
        password = settings.postgres_password
        assert len(password) == 64, f"Expected 64 chars, got {len(password)}"
        assert re.fullmatch(r"[0-9a-f]{64}", password), f"Not hex: {password[:20]}..."

    def test_postgres_password_respects_env(self, monkeypatch):
        """
        given: 設置 POSTGRES_PASSWORD=my-custom-password 環境變數
        when: 建立 Settings 實例
        then: postgres_password 回傳環境變數值
        """
        monkeypatch.setenv("POSTGRES_PASSWORD", "my-custom-password")
        settings = Settings()
        assert settings.postgres_password == "my-custom-password"

    def test_api_key_default_is_empty_string(self, monkeypatch):
        """
        given: 未設置 API_KEY 環境變數
        when: 建立 Settings 實例
        then: api_key 預設為空字串（開發/向後相容模式）
        """
        monkeypatch.setenv("api_key", "")
        settings = Settings()
        assert settings.api_key == ""

    def test_api_key_respects_env(self, monkeypatch):
        """
        given: 設置 API_KEY=prod-secret-key 環境變數
        when: 建立 Settings 實例
        then: api_key 回傳環境變數值
        """
        monkeypatch.setenv("API_KEY", "prod-secret-key")
        settings = Settings()
        assert settings.api_key == "prod-secret-key"

    def test_redis_url_default(self):
        """
        given: 未設置 REDIS_URL 環境變數
        when: 建立 Settings 實例
        then: redis_url 預設為 redis://localhost:6379/0
        """
        settings = Settings()
        assert settings.redis_url == "redis://localhost:6379/0"

    def test_redis_url_respects_env(self, monkeypatch):
        """
        given: 設置 REDIS_URL=redis://redis.example.com:6380/1 環境變數
        when: 建立 Settings 實例
        then: redis_url 回傳環境變數值
        """
        monkeypatch.setenv("REDIS_URL", "redis://redis.example.com:6380/1")
        settings = Settings()
        assert settings.redis_url == "redis://redis.example.com:6380/1"

    def test_postgres_host_default(self):
        """given: 未設置環境變數  when: 建立 Settings  then: postgres_host 預設 localhost"""
        settings = Settings()
        assert settings.postgres_host == "localhost"

    def test_postgres_port_default(self):
        """given: 未設置環境變數  when: 建立 Settings  then: postgres_port 預設 5432"""
        settings = Settings()
        assert settings.postgres_port == 5432

    def test_postgres_db_default(self):
        """given: 未設置環境變數  when: 建立 Settings  then: postgres_db 預設 edict"""
        settings = Settings()
        assert settings.postgres_db == "edict"

    def test_postgres_user_default(self):
        """given: 未設置環境變數  when: 建立 Settings  then: postgres_user 預設 edict"""
        settings = Settings()
        assert settings.postgres_user == "edict"


# ─────────────────────────────────────────────
# DATABASE_URL 環境變數覆蓋
# ─────────────────────────────────────────────


class TestDatabaseUrlOverride:
    """DATABASE_URL 環境變數覆蓋 database_url property 測試。"""

    def test_database_url_override_takes_precedence(self, monkeypatch):
        """
        given: 設置 DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
        when: 存取 Settings.database_url property
        then: 直接回傳 DATABASE_URL 值，忽略其他 postgres_* 欄位
        """
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/db")
        settings = Settings()
        assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_database_url_from_parts_when_no_override(self, monkeypatch):
        """
        given: 未設置 DATABASE_URL，但設置了 postgres_* 環境變數
        when: 存取 Settings.database_url property
        then: 由 postgres_user、postgres_password、postgres_host、postgres_port、postgres_db 拼接
        """
        monkeypatch.setenv("POSTGRES_USER", "myuser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "mypass")
        monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.setenv("POSTGRES_DB", "mydb")
        # 確保 DATABASE_URL 未設置
        monkeypatch.delenv("DATABASE_URL", raising=False)

        settings = Settings()
        url = settings.database_url
        assert url == "postgresql+asyncpg://myuser:mypass@db.example.com:5433/mydb"

    def test_database_url_sync_with_override(self, monkeypatch):
        """
        given: 設置 DATABASE_URL=postgresql+asyncpg://user:pass@host/db
        when: 存取 Settings.database_url_sync property
        then: 將 asyncpg driver 移除，回傳同步版本 URL
        """
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/db")
        settings = Settings()
        sync_url = settings.database_url_sync
        assert sync_url.startswith("postgresql://")
        assert "asyncpg" not in sync_url

    def test_database_url_sync_default(self):
        """
        given: 未設置 DATABASE_URL
        when: 存取 Settings.database_url_sync property
        then: 回傳 postgresql:// (非 asyncpg) 格式的同步 URL
        """
        settings = Settings()
        sync_url = settings.database_url_sync
        assert sync_url.startswith("postgresql://")
        assert "asyncpg" not in sync_url

    def test_database_url_override_via_alias(self, monkeypatch):
        """
        given: 設置 DATABASE_URL 環境變數
        when: 建立 Settings 實例
        then: database_url_override 欄位等於 DATABASE_URL 值（pydantic alias 對應）
        """
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://a:b@c:5432/d")
        settings = Settings()
        assert settings.database_url_override == "postgresql+asyncpg://a:b@c:5432/d"


# ─────────────────────────────────────────────
# get_settings LRU 快取
# ─────────────────────────────────────────────


class TestGetSettings:
    """get_settings 工廠函數單元測試。"""

    def test_get_settings_returns_settings_instance(self):
        """
        given: 無
        when: 呼叫 get_settings()
        then: 回傳 Settings 實例
        """
        # 清除 LRU 快取
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_get_settings_cached_returns_same_instance(self):
        """
        given: 已呼叫過一次 get_settings()
        when: 再次呼叫 get_settings()
        then: 因 @lru_cache，回傳相同實例
        """
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
