"""OutboxEvent 模型 — Transactional Outbox Pattern。

事件先與業務數據寫入同一事務，再由 OutboxRelay worker 異步投遞到 Redis Streams。
消滅 DB/Event 雙寫不一致問題：
- create_task: flush→publish→commit 中 publish 失敗導致操作白費
- transition_state: 先 publish 後 commit，commit 失敗產生幽靈事件
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from ..db import Base


class OutboxEvent(Base):
    """發件箱表 — 事件先寫 DB，再由專用 worker 投遞到 Redis。"""

    __tablename__ = "outbox_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    event_id = Column(
        String(64),
        default=lambda: str(uuid.uuid4()),
        nullable=False,
        unique=True,
    )
    topic = Column(String(100), nullable=False, comment="目標 Redis Stream topic")
    trace_id = Column(String(64), nullable=False)
    event_type = Column(String(100), nullable=False)
    producer = Column(String(100), nullable=False)
    payload = Column(JSONB, default=dict)
    meta = Column(JSONB, default=dict)
    published = Column(Boolean, default=False, index=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_outbox_unpublished", "published", "id", postgresql_where="published = false"),
        Index("ix_outbox_created_at", "created_at"),
    )
