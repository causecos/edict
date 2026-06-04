"""Event 模型 — 事件持久化表，支持回放和審計。

每個事件對應一次系統行爲：任務創建、狀態變更、Agent 思考、Todo 更新等。
遵循 Edict Architecture §3 事件結構規範。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..db import Base


class Event(Base):
    """事件表 — 所有系統事件的持久化記錄。

    使用雙層事件模型：
    - topic: 粗分類，對應 Redis Stream key（task.created, task.status 等）
    - event_type: 細分類（task.state.Doing, task.dispatch.request 等）
    - producer: 標記事件來源服務版本，便於回溯（task_service:v2, orchestrator:v1）
    - payload: JSONB 自由結構，依 event_type 不同有不同 schema
    - meta: 事件元數據（priority, model, version），供監控/過濾使用
    """
    __tablename__ = "events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(64), nullable=False, index=True, comment="關聯任務ID")
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # 事件分類 — topic 對應 Redis Stream，event_type 做細粒度區分
    topic = Column(String(128), nullable=False, index=True, comment="事件主題, e.g. task.created")
    event_type = Column(String(128), nullable=False, comment="事件類型, e.g. state.changed")
    # producer 含版本號，便於在事件回放時識別 schema 版本
    producer = Column(String(128), nullable=False, comment="事件生產者, e.g. orchestrator:v1")

    # 事件數據 — payload 為業務內容，meta 為監控/路由資訊
    payload = Column(JSONB, default=dict, comment="事件負載")
    meta = Column(JSONB, default=dict, comment="元數據 {priority, model, version}")

    # 複合索引：依 trace_id+topic 查詢單一任務的所有同類事件最頻繁
    __table_args__ = (
        Index("ix_events_trace_topic", "trace_id", "topic"),
        Index("ix_events_timestamp", "timestamp"),
    )

    def to_dict(self) -> dict:
        """序列化為 API 響應格式，確保 datetime 轉 ISO 字串。"""
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
