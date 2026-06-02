"""Edict 配置管理 — 從環境變量加載所有配置。"""
from __future__ import annotations

import secrets
from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings
from sqlalchemy.engine.url import make_url


def _generate_secret() -> str:
    """生成高強度隨機密鑰（64 字元 hex）。"""
    return secrets.token_hex(32)


class Settings(BaseSettings):
    # ── Postgres ──
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "edict"
    postgres_user: str = "edict"
    postgres_password: str = Field(
        default_factory=_generate_secret,
        description="資料庫密碼，透過 POSTGRES_PASSWORD 環境變數設定",
    )
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── Auth ──
    api_key: str = ""
    secret_key: str = Field(
        default_factory=_generate_secret,
        description="HMAC 簽名密鑰，透過 SECRET_KEY 環境變數設定",
    )

    # ── Server ──
    backend_host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    scheduler_scan_interval_seconds: int = 30

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """同步 URL，供 Alembic 使用。"""
        if self.database_url_override:
            url = make_url(self.database_url_override)
            drivername = url.drivername.split("+", 1)[0]
            return str(url.set(drivername=drivername))
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {
        "env_file": str(Path(__file__).resolve().parent.parent / ".env"),
        "env_file_encoding": "utf-8",
        "env_prefix": "",
        "alias_generator": None,
        "populate_by_name": True,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
