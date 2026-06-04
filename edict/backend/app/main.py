"""Edict Backend — FastAPI 應用入口。

Lifespan 管理：
- startup: 連接 Redis Event Bus, 初始化數據庫
- shutdown: 關閉連接

路由：
- /api/tasks — 任務 CRUD
- /api/agents — Agent 信息
- /api/events — 事件查詢
- /api/admin — 管理操作
- /ws — WebSocket 實時推送
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .services.event_bus import get_event_bus
from .api import tasks, agents, events, admin, websocket
from .api import legacy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("edict")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命周期管理。

    startup 階段：
    1. 建立 Redis Event Bus 連線（供 publish/subscribe 使用）
    2. 若連線失敗會拋出異常，阻止應用啟動

    shutdown 階段：
    1. 關閉 Event Bus 連線，釋放 Redis 連接池
    """
    settings = get_settings()
    log.info(f"🏛️ Edict Backend starting on port {settings.port}...")

    # 連接 Event Bus
    bus = await get_event_bus()
    log.info("✅ Event Bus connected")

    yield

    # 清理 — 關閉 Redis 連線
    await bus.close()
    log.info("Edict Backend shutdown complete")


app = FastAPI(
    title="Edict 三省六部",
    description="事件驅動的 AI Agent 協作平臺",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — 僅允許本地開發環境與 Dashboard 端口
# 生產環境應透過反向代理處理 CORS，此處僅供開發使用
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{settings.port}",
        "http://localhost:7891",     # 舊 Dashboard 端口
        "http://127.0.0.1:7891",
        "http://localhost:5173",     # Vite dev server
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    # 允許 X-API-Key 自定義 header 通過 CORS 檢查
    allow_headers=["X-API-Key", "Authorization", "Content-Type"],
)

# 註冊路由 — 包含新版 REST API 與舊版兼容端點
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(websocket.router, tags=["websocket"])
# legacy router 掛在相同 prefix 下，用於兼容舊版 API 格式
app.include_router(legacy.router, prefix="/api/tasks", tags=["legacy"])


@app.get("/health")
async def health():
    """存活檢查端點 — 供負載均衡 / Docker healthcheck 使用。"""
    return {"status": "ok", "version": "2.0.0", "engine": "edict"}


@app.get("/api")
async def api_root():
    """API 根路徑 — 回傳可用端點清單。"""
    return {
        "name": "Edict 三省六部 API",
        "version": "2.0.0",
        "endpoints": {
            "tasks": "/api/tasks",
            "agents": "/api/agents",
            "events": "/api/events",
            "admin": "/api/admin",
            "websocket": "/ws",
            "health": "/health",
        },
    }
