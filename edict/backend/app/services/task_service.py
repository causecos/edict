"""任務服務層 — CRUD + 狀態機邏輯。

所有業務規則集中在此：
- 創建任務 → 事件寫入 outbox 表（同一事務）
- 狀態流轉 → 校驗合法性 + SELECT FOR UPDATE 防並發 + outbox 事件
- 查詢、過濾、聚合

事件投遞由 OutboxRelay worker 異步完成，保證 DB/Event 原子一致。
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.event import Event
from ..models.outbox import OutboxEvent
from ..models.task import Task, TaskState, STATE_TRANSITIONS, TERMINAL_STATES
from .event_bus import (
    TOPIC_TASK_AUDIT,
    TOPIC_TASK_CREATED,
    TOPIC_TASK_STATUS,
    TOPIC_TASK_COMPLETED,
    TOPIC_TASK_DISPATCH,
)

log = logging.getLogger("edict.task_service")


class TaskService:
    def __init__(self, db: AsyncSession, event_bus=None):
        self.db = db
        # event_bus 保留用於 request_dispatch 等直接發布場景
        # 常規事件（create/transition）走 outbox 模式，不直接呼叫 bus.publish
        self.bus = event_bus

    @staticmethod
    def _report_text(task: Task, fallback: str = "") -> str:
        """統一「回奏內容」來源，供 DB 欄位與事件 payload 共用。

        解析優先級：
        1. progress_log 最後一筆的 text/content 欄位
        2. task 的 now/output/ac/description 欄位（依序 fallback）
        3. 傳入的 fallback 參數
        """
        progress_log = task.progress_log or []
        if progress_log:
            last = progress_log[-1]
            text = (last.get("text") or last.get("content") or "").strip()
            if text:
                return text

        for field in ("now", "output", "ac", "description"):
            val = (getattr(task, field, "") or "").strip()
            if val:
                return val
        return (fallback or "").strip()

    @classmethod
    def _dispatch_snapshot(cls, task: Task, *, message: str = "") -> dict[str, Any]:
        """生成可直接給 Event Bus / Dispatcher 的任務快照。

        包含所有派遣所需欄位，report/message 欄位供 Agent prompt 注入使用。
        """
        report = cls._report_text(task, fallback=message)
        return {
            "task_id": str(task.task_id),
            "title": task.title,
            "description": task.description or "",
            "state": task.state.value if isinstance(task.state, TaskState) else str(task.state or ""),
            "org": task.org or Task.org_for_state(task.state, task.assignee_org),
            "priority": task.priority or "中",
            "assignee_org": task.assignee_org,
            "tags": task.tags or [],
            "todos": task.todos or [],
            "flow_log": task.flow_log or [],
            "progress_log": task.progress_log or [],
            "block": task.block or "",
            "meta": task.meta or {},
            "now": task.now or "",
            "output": task.output or "",
            "report": report,
            "message": message or report,
        }

    @classmethod
    def _audit_snapshot(cls, task: Task, *, message: str = "", **extra: Any) -> dict[str, Any]:
        """生成寫入 events 表的審計 payload。"""
        payload = cls._dispatch_snapshot(task, message=message)
        if extra:
            payload.update(extra)
        return payload

    def _record_audit_event(
        self,
        task: Task,
        *,
        event_type: str,
        producer: str,
        payload: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> None:
        """將任務變更寫入 events 表，供 /api/events 查詢。"""
        self.db.add(Event(
            trace_id=str(task.trace_id),
            topic=TOPIC_TASK_AUDIT,
            event_type=event_type,
            producer=producer,
            payload=payload,
            meta=meta or {},
        ))

    # ── 創建 ──

    async def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "中",
        assignee_org: str | None = None,
        creator: str = "emperor",
        tags: list[str] | None = None,
        initial_state: TaskState = TaskState.Taizi,
        meta: dict | None = None,
    ) -> Task:
        """創建任務，事件寫入 outbox 表（同一事務原子提交）。

        Transactional Outbox 保證：
        - task INSERT 與 outbox INSERT 在同一個 DB 事務中
        - commit 成功 → 兩者同時持久化
        - commit 失敗 → 兩者同時回滾
        - OutboxRelay worker 異步投遞事件到 Redis Stream
        """
        now = datetime.now(timezone.utc)
        trace_id = str(uuid.uuid4())
        target_org = Task.org_for_state(initial_state, assignee_org)
        task_meta = meta or {}

        task = Task(
            trace_id=trace_id,
            title=title,
            description=description,
            priority=priority,
            state=initial_state,
            assignee_org=assignee_org,
            creator=creator,
            tags=tags or [],
            org=target_org,
            official=creator,
            now=description or "任務創建",
            target_dept=assignee_org or "",
            flow_log=[
                {
                    "from": None,
                    "to": initial_state.value,
                    "agent": "system",
                    "reason": "任務創建",
                    "remark": "任務創建",
                    "ts": now.isoformat(),
                    "at": now.isoformat(),
                }
            ],
            progress_log=[],
            todos=[],
            scheduler={},
            meta=task_meta,
        )
        self.db.add(task)
        # flush 讓 task.task_id 可被 outbox trace_id 參照
        await self.db.flush()

        # 事件寫入 outbox — 與 task 同一事務，原子提交
        outbox = OutboxEvent(
            topic=TOPIC_TASK_CREATED,
            trace_id=trace_id,
            event_type="task.created",
            producer="task_service",
            payload=self._dispatch_snapshot(task, message=f"新任務已創建: {title}"),
        )
        self.db.add(outbox)
        self._record_audit_event(
            task,
            event_type="task.created",
            producer=creator,
            payload=self._audit_snapshot(task, message=f"新任務已創建: {title}"),
        )

        await self.db.commit()
        log.info(f"Created task {task.task_id}: {title} [{initial_state.value}]")
        return task

    # ── 狀態流轉 ──

    async def transition_state(
        self,
        task_id: uuid.UUID,
        new_state: TaskState,
        agent: str = "system",
        reason: str = "",
    ) -> Task:
        """執行狀態流轉。SELECT FOR UPDATE 防止並發 flow_log 丟失。

        並發安全機制：
        1. SELECT ... FOR UPDATE — 行級排他鎖，串行化相同 task_id 的寫入
        2. 校驗 STATE_TRANSITIONS 矩陣，非法轉換拋 ValueError
        3. 更新 state/org/flow_log，在同一事務內寫入 outbox 事件
        4. commit 釋放行鎖
        """
        # 行級排他鎖 — 串行化同一任務的並發寫入
        stmt = select(Task).where(Task.task_id == task_id).with_for_update()
        result = await self.db.execute(stmt)
        task = result.scalar_one_or_none()
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        old_state = task.state

        # 校驗合法流轉 — 比對 STATE_TRANSITIONS 矩陣
        allowed = STATE_TRANSITIONS.get(old_state, set())
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {old_state.value} → {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        task.state = new_state
        task.org = Task.org_for_state(new_state, task.assignee_org)
        if reason:
            task.now = reason
            if new_state in TERMINAL_STATES and not (task.output or "").strip():
                task.output = reason
        task.updated_at = datetime.now(timezone.utc)

        # 在行鎖保護下安全追加 flow_log
        flow_entry = {
            "from": old_state.value,
            "to": new_state.value,
            "agent": agent,
            "reason": reason,
            "remark": reason,
            "ts": datetime.now(timezone.utc).isoformat(),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if task.flow_log is None:
            task.flow_log = []
        task.flow_log = [*task.flow_log, flow_entry]

        # 事件寫入 outbox（同一事務）
        topic = TOPIC_TASK_COMPLETED if new_state in TERMINAL_STATES else TOPIC_TASK_STATUS
        outbox = OutboxEvent(
            topic=topic,
            trace_id=str(task.trace_id),
            event_type=f"task.state.{new_state.value}",
            producer=agent,
            payload={
                **self._dispatch_snapshot(task, message=reason or f"任務已流轉到 {new_state.value}"),
                "from": old_state.value,
                "to": new_state.value,
                "reason": reason,
            },
        )
        self.db.add(outbox)
        self._record_audit_event(
            task,
            event_type=f"task.state.{new_state.value}",
            producer=agent,
            payload=self._audit_snapshot(
                task,
                message=reason or f"任務已流轉到 {new_state.value}",
                from_state=old_state.value,
                to_state=new_state.value,
                reason=reason,
                agent=agent,
            ),
        )

        await self.db.commit()
        log.info(f"Task {task_id} state: {old_state.value} → {new_state.value} by {agent}")
        return task

    # ── 派發請求 ──

    async def request_dispatch(
        self,
        task_id: uuid.UUID,
        target_agent: str,
        message: str = "",
    ):
        """發布 task.dispatch 事件到 outbox，由 OutboxRelay 投遞後 DispatchWorker 消費。

        不直接呼叫 bus.publish — 走 outbox 確保事件持久化。
        """
        task = await self._get_task(task_id)
        outbox = OutboxEvent(
            topic=TOPIC_TASK_DISPATCH,
            trace_id=str(task.trace_id),
            event_type="task.dispatch.request",
            producer="task_service",
            payload={
                **self._dispatch_snapshot(task, message=message),
                "agent": target_agent,
                "message": message or self._report_text(task),
            },
        )
        self.db.add(outbox)
        self._record_audit_event(
            task,
            event_type="task.dispatch.request",
            producer="task_service",
            payload=self._audit_snapshot(
                task,
                message=message or self._report_text(task),
                agent=target_agent,
                dispatch_message=message,
            ),
        )
        await self.db.commit()
        log.info(f"Dispatch requested: task {task_id} → agent {target_agent}")

    # ── 進度/備註更新 ──

    async def add_progress(
        self,
        task_id: uuid.UUID,
        agent: str,
        content: str,
    ) -> Task:
        task = await self._get_task(task_id)
        now_ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "agent": agent,
            "agentLabel": agent,
            "text": content,
            "content": content,
            "ts": now_ts,
            "at": now_ts,
        }
        if task.progress_log is None:
            task.progress_log = []
        task.progress_log = [*task.progress_log, entry]
        task.now = content or task.now
        task.updated_at = datetime.now(timezone.utc)
        self._record_audit_event(
            task,
            event_type="task.progress.updated",
            producer=agent,
            payload=self._audit_snapshot(
                task,
                message=content,
                progress_entry=entry,
            ),
        )
        await self.db.commit()
        return task

    async def update_todos(
        self,
        task_id: uuid.UUID,
        todos: list[dict],
    ) -> Task:
        task = await self._get_task(task_id)
        task.todos = todos
        task.updated_at = datetime.now(timezone.utc)
        self._record_audit_event(
            task,
            event_type="task.todos.updated",
            producer="task_service",
            payload=self._audit_snapshot(task, message="更新 TODO 清單", todos=todos),
        )
        await self.db.commit()
        return task

    async def update_scheduler(
        self,
        task_id: uuid.UUID,
        scheduler: dict,
    ) -> Task:
        task = await self._get_task(task_id)
        task.scheduler = scheduler
        task.updated_at = datetime.now(timezone.utc)
        self._record_audit_event(
            task,
            event_type="task.scheduler.updated",
            producer="task_service",
            payload=self._audit_snapshot(task, message="更新排期資訊", scheduler=scheduler),
        )
        await self.db.commit()
        return task

    # ── 查詢 ──

    async def get_task(self, task_id: uuid.UUID) -> Task:
        """依 task_id 查詢單一任務，不存在時拋 ValueError。"""
        return await self._get_task(task_id)

    async def list_tasks(
        self,
        state: TaskState | None = None,
        assignee_org: str | None = None,
        priority: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        """查詢任務列表，支援多維度過濾與分頁。

        所有過濾條件為 AND 組合，未填則忽略該維度。
        排序：created_at DESC（最新優先）。
        """
        stmt = select(Task)
        conditions = []
        if state is not None:
            conditions.append(Task.state == state)
        if assignee_org is not None:
            conditions.append(Task.assignee_org == assignee_org)
        if priority is not None:
            conditions.append(Task.priority == priority)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(Task.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_live_status(self) -> dict[str, Any]:
        """生成兼容舊 live_status.json 格式的全局狀態。"""
        tasks = await self.list_tasks(limit=200)
        active_tasks = {}
        completed_tasks = {}
        for t in tasks:
            d = t.to_dict()
            if t.state in TERMINAL_STATES:
                completed_tasks[str(t.task_id)] = d
            else:
                active_tasks[str(t.task_id)] = d
        return {
            "tasks": active_tasks,
            "completed_tasks": completed_tasks,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    async def count_tasks(self, state: TaskState | None = None) -> int:
        stmt = select(func.count(Task.task_id))
        if state is not None:
            stmt = stmt.where(Task.state == state)
        result = await self.db.execute(stmt)
        return result.scalar_one()

    # ── 內部 ──

    async def _get_task(self, task_id: uuid.UUID) -> Task:
        task = await self.db.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        return task
