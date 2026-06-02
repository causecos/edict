"""AuditLog 模型 — 獨立審計日誌表。

記錄所有 Agent 和系統對任務的操作，支持 "誰在什麼時候對哪個任務做了什麼" 查詢。
與 flow_log (JSONB 字段) 不同，審計日誌是獨立表，可跨任務檢索。
"""

from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from ..db import Base


class AuditLog(Base):
    """審計日誌表。"""

    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    task_id = Column(String(64), nullable=True, comment="關聯任務 ID")
    trace_id = Column(String(64), nullable=True, comment="追蹤鏈路 ID")
    agent_id = Column(String(50), nullable=True, comment="執行操作的 Agent")
    action = Column(String(50), nullable=False, comment="操作類型: state/flow/todo/confirm/memory/permission_denied")
    old_value = Column(JSONB, nullable=True, comment="變更前狀態")
    new_value = Column(JSONB, nullable=True, comment="變更後狀態")
    reason = Column(Text, default="", comment="操作原因/備註")
    meta = Column(JSONB, default=dict, comment="擴展元數據 (tokens, cost, duration)")

    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_task_id", "task_id"),
        Index("ix_audit_agent_id", "agent_id"),
        Index("ix_audit_action", "action"),
    )
