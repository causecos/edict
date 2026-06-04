"""Task 模型 — 三省六部任務核心表。"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Enum, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..db import Base


class TaskState(str, enum.Enum):
    """任務狀態枚舉 — 映射三省六部流程。

    狀態流轉方向（簡化）：
      Pending → Taizi → Zhongshu → Menxia → Assigned → Doing → Review → Done
                                                    ↑        ↓         ↑
                                                   Next ← Blocked → Menxia/Review

    終止態：Done（完成）、Cancelled（取消）
    關鍵轉折：Menxia 可駁回至 Zhongshu（封駁）；Review 可駁回 Menxia（複審）
    """

    Taizi = "Taizi"
    Zhongshu = "Zhongshu"
    Menxia = "Menxia"
    Assigned = "Assigned"
    Next = "Next"
    Doing = "Doing"
    Review = "Review"
    Done = "Done"
    Blocked = "Blocked"
    Cancelled = "Cancelled"
    Pending = "Pending"
    PendingConfirm = "PendingConfirm"


# 終止態 — 進入後不再流轉（僅可復歸到非終止態）
TERMINAL_STATES = {TaskState.Done, TaskState.Cancelled}

# 狀態轉換矩陣：每個狀態允許轉換到的目標狀態集合
# Blocked 態可從任意狀態進入，也可轉回任意非終止態（解鎖後恢復原流程）
STATE_TRANSITIONS = {
    TaskState.Pending: {TaskState.Taizi, TaskState.Cancelled},
    TaskState.Taizi: {TaskState.Zhongshu, TaskState.Cancelled},
    TaskState.Zhongshu: {TaskState.Menxia, TaskState.Cancelled, TaskState.Blocked},
    TaskState.Menxia: {TaskState.Assigned, TaskState.Zhongshu, TaskState.Cancelled},
    TaskState.Assigned: {TaskState.Doing, TaskState.Next, TaskState.Cancelled, TaskState.Blocked},
    TaskState.Next: {TaskState.Doing, TaskState.Cancelled, TaskState.Blocked},
    TaskState.Doing: {TaskState.Review, TaskState.Done, TaskState.Blocked, TaskState.Cancelled},
    TaskState.Review: {TaskState.Done, TaskState.Menxia, TaskState.Doing, TaskState.Cancelled, TaskState.PendingConfirm},
    TaskState.PendingConfirm: {TaskState.Done, TaskState.Review, TaskState.Cancelled},
    TaskState.Blocked: {
        TaskState.Taizi,
        TaskState.Zhongshu,
        TaskState.Menxia,
        TaskState.Assigned,
        TaskState.Next,
        TaskState.Doing,
        TaskState.Review,
        TaskState.Cancelled,
    },
}

# 狀態 → Agent 映射：當任務進入特定狀態時，由哪個 Agent 負責處理
STATE_AGENT_MAP = {
    TaskState.Taizi: "taizi",
    TaskState.Zhongshu: "zhongshu",
    TaskState.Menxia: "menxia",
    TaskState.Assigned: "shangshu",
    TaskState.Review: "shangshu",
    TaskState.PendingConfirm: "shangshu",
    TaskState.Pending: "zhongshu",
}

# 部門名稱 → Agent ID：供 DispatchWorker 解析目標 agent
ORG_AGENT_MAP = {
    "戶部": "hubu",
    "禮部": "libu",
    "兵部": "bingbu",
    "刑部": "xingbu",
    "工部": "gongbu",
    "吏部": "libu_hr",
}

# 狀態 → 部門顯示名稱：供 Dashboard 呈現當前負責部門
STATE_ORG_MAP = {
    TaskState.Taizi: "太子",
    TaskState.Zhongshu: "中書省",
    TaskState.Menxia: "門下省",
    TaskState.Assigned: "尚書省",
    TaskState.Review: "尚書省",
    TaskState.PendingConfirm: "尚書省",
    TaskState.Pending: "中書省",
}


class Task(Base):
    """三省六部任務表。

    雙層欄位設計：
    - 新欄位（task_id/trace_id/state/assignee_org 等）：供 backend 服務使用
    - 舊兼容欄位（org/official/now/block/output 等）：供舊 Dashboard 直接讀取
      兩組欄位在寫入時同步更新，確保新舊系統並行過渡。
    """

    __tablename__ = "tasks"

    # ── 核心識別 ──
    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(64), nullable=False, default=lambda: str(uuid.uuid4()), comment="追蹤鏈路 ID")
    title = Column(String(200), nullable=False, comment="任務標題")
    description = Column(Text, default="", comment="任務描述")
    priority = Column(String(10), default="中", comment="優先級")

    # ── 狀態與派發 ──
    state = Column(
        Enum(TaskState, name="task_state", native_enum=False, validate_strings=True),
        nullable=False,
        default=TaskState.Taizi,
        comment="任務狀態",
    )
    assignee_org = Column(String(50), nullable=True, comment="目標執行部門")
    creator = Column(String(50), default="emperor", comment="創建者")
    tags = Column(JSONB, default=list, comment="標籤")
    meta = Column(JSONB, default=dict, comment="擴展元數據")

    # ── 舊看板兼容欄位（與新欄位同步寫入，供舊 Dashboard 直接讀取）──
    org = Column(String(32), nullable=False, default="太子", comment="當前執行部門")
    official = Column(String(32), default="", comment="責任官員")
    now = Column(Text, default="", comment="當前進展描述")
    eta = Column(String(64), default="-", comment="預計完成時間")
    block = Column(Text, default="無", comment="阻塞原因")
    output = Column(Text, default="", comment="最終產出")
    archived = Column(Boolean, default=False, comment="是否歸檔")

    # ── 日誌與附件 ──
    flow_log = Column(JSONB, default=list, comment="流轉日誌 [{from, to, agent, reason, ts, at}]")
    progress_log = Column(JSONB, default=list, comment="進展日誌 [{at, agent, text, todos}]")
    todos = Column(JSONB, default=list, comment="子任務 [{id, title, status, detail}]")
    scheduler = Column(JSONB, default=dict, comment="調度器元數據")
    template_id = Column(String(64), default="", comment="模板ID")
    template_params = Column(JSONB, default=dict, comment="模板參數")
    ac = Column(Text, default="", comment="驗收標準")
    target_dept = Column(String(64), default="", comment="目標部門")

    # ── 時間戳 ──
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # 索引設計：覆蓋 list_tasks 的常用過濾組合（state+archived、created_at 排序）
    __table_args__ = (
        Index("ix_tasks_trace_id", "trace_id"),
        Index("ix_tasks_assignee_org", "assignee_org"),
        Index("ix_tasks_created_at", "created_at"),
        Index("ix_tasks_state", "state"),
        Index("ix_tasks_state_archived", "state", "archived"),
        Index("ix_tasks_updated_at", "updated_at"),
    )

    @staticmethod
    def org_for_state(state: TaskState, assignee_org: str | None = None) -> str:
        """根據當前狀態推斷對應的執行部門顯示名稱。

        - Doing/Next → 由 assignee_org 決定（六部執行階段），否則顯示「六部」
        - 其他狀態 → 查 STATE_ORG_MAP（三省或太子），fallback 為 assignee_org
        """
        if state in {TaskState.Doing, TaskState.Next}:
            return assignee_org or "六部"
        return STATE_ORG_MAP.get(state, assignee_org or "太子")

    def to_dict(self) -> dict[str, Any]:
        """序列化爲 API 響應格式，併兼容舊 live_status 字段。

        輸出同時包含：
        - 新欄位（task_id, trace_id, state, assignee_org 等）
        - 舊欄位（id, org, official, now, output 等） — 供舊版 Dashboard 無縫讀取
        - camelCase 別名（createdAt, updatedAt, templateId 等） — 供 React 前端
        """
        state_value = self.state.value if isinstance(self.state, TaskState) else str(self.state or "")
        meta = self.meta or {}
        scheduler = self.scheduler or {}
        task_id = str(self.task_id) if self.task_id else ""
        updated_at = self.updated_at.isoformat() if self.updated_at else ""
        # 輸出優先取 output 欄位，fallback 到 meta.output
        legacy_output = self.output or meta.get("output") or meta.get("legacy_output", "")

        return {
            "task_id": task_id,
            "trace_id": self.trace_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "state": state_value,
            "assignee_org": self.assignee_org,
            "creator": self.creator,
            "tags": self.tags or [],
            "meta": meta,
            "flow_log": self.flow_log or [],
            "progress_log": self.progress_log or [],
            "todos": self.todos or [],
            "scheduler": scheduler,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": updated_at,
            # 舊前端兼容字段
            "id": task_id,
            "org": self.org or self.org_for_state(self.state, self.assignee_org),
            "official": self.official or self.creator,
            "now": self.now or self.description,
            "eta": self.eta if self.eta != "-" else updated_at,
            "block": self.block,
            "output": legacy_output,
            "archived": self.archived,
            "templateId": self.template_id,
            "templateParams": self.template_params or {},
            "ac": self.ac,
            "targetDept": self.target_dept,
            "_scheduler": scheduler,
            "createdAt": self.created_at.isoformat() if self.created_at else "",
            "updatedAt": updated_at,
        }
