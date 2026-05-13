"""Event 模型 — 事件持久化表，支持回放和審計。

每個事件對應一次系統行爲：任務創建、狀態變更、Agent 思考、Todo 更新等。
遵循 Edict Architecture §3 事件結構規範。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..db import Base


class Event(Base):
    """事件表 — 所有系統事件的持久化記錄。"""
    __tablename__ = "events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(32), nullable=False, index=True, comment="關聯任務ID")
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # 事件分類
    topic = Column(String(128), nullable=False, index=True, comment="事件主題, e.g. task.created")
    event_type = Column(String(128), nullable=False, comment="事件類型, e.g. state.changed")
    producer = Column(String(128), nullable=False, comment="事件生產者, e.g. orchestrator:v1")

    # 事件數據
    payload = Column(JSONB, default=dict, comment="事件負載")
    meta = Column(JSONB, default=dict, comment="元數據 {priority, model, version}")

    __table_args__ = (
        Index("ix_events_trace_topic", "trace_id", "topic"),
        Index("ix_events_timestamp", "timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "event_id": str(self.event_id),
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else "",
            "topic": self.topic,
            "event_type": self.event_type,
            "producer": self.producer,
            "payload": self.payload or {},
            "meta": self.meta or {},
        }
