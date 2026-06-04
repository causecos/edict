"""AuditLog 模型 — 獨立審計日誌表。

記錄所有 Agent 和系統對任務的操作，支持 "誰在什麼時候對哪個任務做了什麼" 查詢。
與 flow_log (JSONB 字段) 不同，審計日誌是獨立表，可跨任務檢索。
"""

from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from ..db import Base


class AuditLog(Base):
    """審計日誌表 — 記錄所有 Agent 和系統對任務的操作。

    設計原則：
    - 獨立表而非 JSONB 欄位，支援跨任務檢索與聚合查詢
    - 每次操作寫入一行（append-only），不做 UPDATE
    - 透過 action 欄位分類：state（狀態變更）、flow（流轉）、todo（待辦更新）等
    - 查詢模式按 timestamp / task_id / agent_id / action 建立索引
    """

    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # 關聯到 tasks.task_id，可為 NULL（系統級事件不綁定特定任務）
    task_id = Column(String(64), nullable=True, comment="關聯任務 ID")
    # 同一 trace_id 的審計紀錄可串聯為完整操作鏈路
    trace_id = Column(String(64), nullable=True, comment="追蹤鏈路 ID")
    agent_id = Column(String(50), nullable=True, comment="執行操作的 Agent")
    # action 枚舉：state/flow/todo/confirm/memory/permission_denied
    action = Column(String(50), nullable=False, comment="操作類型: state/flow/todo/confirm/memory/permission_denied")
    old_value = Column(JSONB, nullable=True, comment="變更前狀態")
    new_value = Column(JSONB, nullable=True, comment="變更後狀態")
    reason = Column(Text, default="", comment="操作原因/備註")
    # meta 儲存 tokens/cost/duration 等擴展指標，用於效能與成本分析
    meta = Column(JSONB, default=dict, comment="擴展元數據 (tokens, cost, duration)")

    # 索引設計：覆蓋常用查詢維度（時間範圍、任務、Agent、操作類型）
    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_task_id", "task_id"),
        Index("ix_audit_agent_id", "agent_id"),
        Index("ix_audit_action", "action"),
    )
