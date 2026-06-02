"""Admin API — 管理操作（遷移、診斷、配置）。"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..db import get_db
from ..services.event_bus import get_event_bus
from ..auth import require_api_key

log = logging.getLogger("edict.api.admin")
router = APIRouter()


@router.get("/health/deep")
async def deep_health(db: AsyncSession = Depends(get_db)):
    """深度健康檢查：Postgres + Redis 連通性。"""
    checks = {"postgres": False, "redis": False}

    # Postgres
    try:
        result = await db.execute(text("SELECT 1"))
        checks["postgres"] = result.scalar() == 1
    except Exception as e:
        checks["postgres_error"] = str(e)

    # Redis
    try:
        bus = await get_event_bus()
        pong = await bus.redis.ping()
        checks["redis"] = pong is True
    except Exception as e:
        checks["redis_error"] = str(e)

    status = "ok" if all(checks.get(k) for k in ["postgres", "redis"]) else "degraded"
    return {"status": status, "checks": checks}


@router.get("/pending-events")
async def pending_events(
    topic: str = "task.dispatch",
    group: str = "dispatcher",
    count: int = 20,
):
    """查看未 ACK 的 pending 事件（診斷工具）。"""
    bus = await get_event_bus()
    pending = await bus.get_pending(topic, group, count)
    return {
        "topic": topic,
        "group": group,
        "pending": [
            {
                "entry_id": str(p.get("message_id", "")),
                "consumer": str(p.get("consumer", "")),
                "idle_ms": p.get("time_since_delivered", 0),
                "delivery_count": p.get("times_delivered", 0),
            }
            for p in pending
        ] if pending else [],
    }


@router.post("/migrate/check", dependencies=[Depends(require_api_key)])
async def migration_check():
    """檢查舊數據文件是否存在。"""
    data_dir = Path(__file__).parents[4] / "data"
    files = {
        "tasks_source": (data_dir / "tasks_source.json").exists(),
        "live_status": (data_dir / "live_status.json").exists(),
        "agent_config": (data_dir / "agent_config.json").exists(),
        "officials_stats": (data_dir / "officials_stats.json").exists(),
    }
    return {"data_dir": str(data_dir), "files": files}


@router.get("/config")
async def get_config():
    """獲取當前運行配置（脫敏）。"""
    from ..config import get_settings
    settings = get_settings()
    return {
        "port": settings.port,
        "debug": settings.debug,
        "database": settings.database_url.split("@")[-1] if "@" in settings.database_url else "***",
        "redis": settings.redis_url.split("@")[-1] if "@" in settings.redis_url else settings.redis_url,
        "scheduler_scan_interval": settings.scheduler_scan_interval_seconds,
    }


# ── Source Mode ──

_SOURCE_MODE_FILE = Path(__file__).parents[4] / "data" / "task_source_mode.json"

_DEFAULT_SOURCE_MODE = {
    "mode": "auto",
    "backendApiBase": "http://127.0.0.1:8000",
    "timeoutMs": 3000,
}


def _load_source_mode() -> dict:
    """加載 task_source_mode.json。"""
    try:
        if _SOURCE_MODE_FILE.exists():
            return json.loads(_SOURCE_MODE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return _DEFAULT_SOURCE_MODE.copy()


def _save_source_mode(cfg: dict) -> None:
    """寫入 task_source_mode.json。"""
    _SOURCE_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SOURCE_MODE_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@router.get("/source-mode")
async def get_source_mode():
    """獲取當前任務資料來源模式。"""
    cfg = _load_source_mode()
    effective = cfg.get("mode", "auto")
    if effective == "auto":
        effective = "db"  # backend 存在就代表 DB 可用
    return {
        "ok": True,
        "config": cfg,
        "backend": {"ok": True, "statusCode": 200},
        "effective": effective,
    }


@router.post("/source-mode", dependencies=[Depends(require_api_key)])
async def set_source_mode(body: dict):
    """設定任務資料來源模式。"""
    mode = str(body.get("mode", "auto")).lower().strip()
    if mode not in ("auto", "json", "db"):
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Allowed: auto, json, db")

    cfg = _load_source_mode()
    cfg["mode"] = mode
    if "backendApiBase" in body:
        cfg["backendApiBase"] = str(body["backendApiBase"]).strip().rstrip("/")
    if "timeoutMs" in body:
        try:
            cfg["timeoutMs"] = max(500, min(int(body["timeoutMs"]), 15000))
        except (ValueError, TypeError):
            pass

    _save_source_mode(cfg)

    effective = mode if mode != "auto" else "db"
    return {
        "ok": True,
        "config": cfg,
        "backend": {"ok": True, "statusCode": 200},
        "effective": effective,
    }
