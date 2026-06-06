"""Thought 模型 — Agent 思考流持久化。

遵循 Edict Architecture §4 Thought JSON Schema。
支持 streaming partial thoughts 和 dashboard 實時展示。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID

from ..db import Base


class Thought(Base):
    """Agent 思考記錄。"""
    __tablename__ = "thoughts"

    thought_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(64), nullable=False, index=True, comment="關聯任務ID")
    agent = Column(String(32), nullable=False, index=True, comment="Agent 標識")
    step = Column(Integer, nullable=False, default=0, comment="思考步驟序號")
    type = Column(
        String(32),
        nullable=False,
        default="reasoning",
        comment="思考類型: reasoning|query|action_intent|summary",
    )
    source = Column(String(16), default="llm", comment="來源: llm|tool|human")
    content = Column(Text, nullable=False, default="", comment="思考內容")
    tokens = Column(Integer, default=0, comment="消耗 token 數")
    confidence = Column(Float, default=0.0, comment="置信度 0-1")
    sensitive = Column(Boolean, default=False, comment="是否敏感內容")
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("ix_thoughts_trace_agent", "trace_id", "agent"),
        Index("ix_thoughts_timestamp", "timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "thought_id": str(self.thought_id),
            "trace_id": self.trace_id,
            "agent": self.agent,
            "step": self.step,
            "type": self.type,
            "source": self.source,
            "content": self.content,
            "tokens": self.tokens,
            "confidence": self.confidence,
            "sensitive": self.sensitive,
            "timestamp": self.timestamp.isoformat() if self.timestamp else "",
        }
