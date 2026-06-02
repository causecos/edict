"""Events API — 事件查詢與審計。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from ..db import get_db
from ..models.event import Event
from ..services.event_bus import get_event_bus

log = logging.getLogger("edict.api.events")
router = APIRouter()


@router.get("")
async def list_events(
    trace_id: str | None = None,
    topic: str | None = None,
    producer: str | None = None,
    limit: int = Query(default=50, le=500),
    db: AsyncSession = Depends(get_db),
):
    """查詢持久化事件（從 Postgres event 表）。"""
    stmt = select(Event)
    if trace_id:
        stmt = stmt.where(Event.trace_id == trace_id)
    if topic:
        stmt = stmt.where(Event.topic == topic)
    if producer:
        stmt = stmt.where(Event.producer == producer)
    stmt = stmt.order_by(Event.timestamp.desc()).limit(limit)
    result = await db.execute(stmt)
    events = result.scalars().all()
    return {
        "events": [
            {
                "event_id": str(e.event_id),
                "trace_id": e.trace_id,
                "topic": e.topic,
                "event_type": e.event_type,
                "producer": e.producer,
                "payload": e.payload,
                "meta": e.meta,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in events
        ],
        "count": len(events),
    }


@router.get("/stream-info")
async def stream_info(topic: str = Query(description="Stream topic")):
    """查詢 Redis Stream 實時信息。"""
    bus = await get_event_bus()
    info = await bus.stream_info(topic)
    return {"topic": topic, "info": info}


@router.get("/topics")
async def list_topics():
    """列出所有可用事件 topic。"""
    from ..services.event_bus import (
        TOPIC_TASK_CREATED,
        TOPIC_TASK_STATUS,
        TOPIC_TASK_DISPATCH,
        TOPIC_TASK_DISPATCH_STARTED,
        TOPIC_TASK_DISPATCH_FAILED,
        TOPIC_TASK_DISPATCH_ALERT,
        TOPIC_TASK_COMPLETED,
        TOPIC_TASK_STALLED,
        TOPIC_TASK_AUDIT,
        TOPIC_AGENT_THOUGHTS,
        TOPIC_AGENT_HEARTBEAT,
    )
    return {
        "topics": [
            {"name": TOPIC_TASK_CREATED, "description": "任務創建"},
            {"name": TOPIC_TASK_STATUS, "description": "狀態變更"},
            {"name": TOPIC_TASK_DISPATCH, "description": "Agent 派發"},
            {"name": TOPIC_TASK_DISPATCH_STARTED, "description": "派發開始"},
            {"name": TOPIC_TASK_DISPATCH_FAILED, "description": "派發失敗"},
            {"name": TOPIC_TASK_DISPATCH_ALERT, "description": "派發安全告警"},
            {"name": TOPIC_TASK_COMPLETED, "description": "任務完成"},
            {"name": TOPIC_TASK_STALLED, "description": "任務停滯（巡檢）"},
            {"name": TOPIC_TASK_AUDIT, "description": "任務審計快照"},
            {"name": TOPIC_AGENT_THOUGHTS, "description": "Agent 思考流"},
            {"name": TOPIC_AGENT_HEARTBEAT, "description": "Worker 心跳"},
        ]
    }
