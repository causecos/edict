"""WebSocket 端點 — 實時推送事件到前端。

取代舊架構的 5 秒 HTTP 輪詢，改爲：
- 客戶端 WebSocket 連接
- 服務端訂閱 Redis Pub/Sub 頻道
- 實時推送事件（狀態變更、Agent 思考流、心跳等）
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import get_settings
from ..services.event_bus import get_event_bus

log = logging.getLogger("edict.ws")
router = APIRouter()

# 活躍連接管理
_connections: set[WebSocket] = set()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """主 WebSocket 端點 — 推送所有事件。"""
    await ws.accept()
    _connections.add(ws)
    log.info(f"WebSocket connected. Total: {len(_connections)}")

    # 創建獨立的 Redis Pub/Sub 連接
    settings = get_settings()
    pubsub_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = pubsub_redis.pubsub()

    # 訂閱所有 edict 頻道
    await pubsub.psubscribe("edict:pubsub:*")

    try:
        # 並發：監聽 Redis Pub/Sub + 客戶端消息
        await asyncio.gather(
            _relay_events(pubsub, ws),
            _handle_client_messages(ws),
        )
    except WebSocketDisconnect:
        log.info("WebSocket disconnected")
    except Exception as e:
        log.error(f"WebSocket error: {e}")
    finally:
        _connections.discard(ws)
        await pubsub.punsubscribe("edict:pubsub:*")
        await pubsub_redis.aclose()
        log.info(f"WebSocket cleaned up. Remaining: {len(_connections)}")


async def _relay_events(pubsub, ws: WebSocket):
    """從 Redis Pub/Sub 接收事件，推送到 WebSocket。"""
    async for message in pubsub.listen():
        if message["type"] == "pmessage":
            channel = message["channel"]
            data = message["data"]

            # 提取 topic 名
            topic = channel.replace("edict:pubsub:", "") if channel.startswith("edict:pubsub:") else channel

            try:
                event_data = json.loads(data) if isinstance(data, str) else data
                await ws.send_json({
                    "type": "event",
                    "topic": topic,
                    "data": event_data,
                })
            except Exception as e:
                log.warning(f"Failed to relay event: {e}")
                break


async def _handle_client_messages(ws: WebSocket):
    """處理客戶端發送的消息（心跳、訂閱過濾等）。"""
    while True:
        try:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
            elif msg_type == "subscribe":
                # 前端可請求只訂閱特定 topic（未來擴展）
                topics = data.get("topics", [])
                log.debug(f"Client subscribe request: {topics}")
                await ws.send_json({"type": "subscribed", "topics": topics})
            else:
                log.debug(f"Unknown client message: {msg_type}")

        except WebSocketDisconnect:
            raise
        except Exception:
            break


@router.websocket("/ws/task/{task_id}")
async def task_websocket(ws: WebSocket, task_id: str):
    """單任務 WebSocket — 只推送與特定任務相關的事件。"""
    await ws.accept()
    _connections.add(ws)

    settings = get_settings()
    pubsub_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = pubsub_redis.pubsub()
    await pubsub.psubscribe("edict:pubsub:*")

    try:
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                data = message["data"]
                try:
                    event_data = json.loads(data) if isinstance(data, str) else data
                    payload = event_data.get("payload", {})
                    if isinstance(payload, str):
                        payload = json.loads(payload)

                    # 只轉發與此任務相關的事件
                    if payload.get("task_id") == task_id:
                        topic = message["channel"].replace("edict:pubsub:", "")
                        await ws.send_json({
                            "type": "event",
                            "topic": topic,
                            "data": event_data,
                        })
                except Exception:
                    continue
    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(ws)
        await pubsub.punsubscribe("edict:pubsub:*")
        await pubsub_redis.aclose()


async def broadcast(event: dict):
    """向所有連接的 WebSocket 客戶端廣播事件（服務端內部調用用）。"""
    dead = set()
    for ws in _connections:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    _connections -= dead
