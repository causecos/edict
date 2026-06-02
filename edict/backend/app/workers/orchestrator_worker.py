"""Orchestrator Worker — 消費事件總線，驅動任務狀態機。

監聽 topic:
- task.created → 自動派發給太子 agent
- task.status → 處理各種狀態變更，自動派發下遊 agent
- task.completed → 記錄任務完成日誌
- task.stalled → 處理停滯任務（重試 → 升級 → 阻塞）

附加定時任務:
- _check_stalled → 每 60s 掃描 Doing 狀態超時任務，發布 task.stalled 事件

這是系統的核心編排器，取代舊架構中 daemon 線程 + 定時掃描的角色。
得益於 Redis Streams ACK 機制：即使 worker 崩潰，未 ACK 的事件
會被其他消費者自動認領，永不丟失。
"""

import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone, timedelta

from ..db import async_session
from ..models.task import TaskState, STATE_AGENT_MAP, ORG_AGENT_MAP, TERMINAL_STATES
from ..services.event_bus import (
    EventBus,
    TOPIC_TASK_CREATED,
    TOPIC_TASK_STATUS,
    TOPIC_TASK_DISPATCH,
    TOPIC_TASK_DISPATCH_FAILED,
    TOPIC_TASK_COMPLETED,
    TOPIC_TASK_STALLED,
    TOPIC_TASK_ESCALATED,
)
from ..services.task_service import TaskService

log = logging.getLogger("edict.orchestrator")

GROUP = "orchestrator"
CONSUMER = "orch-1"

# 停滯恢復配置
MAX_STALL_RETRIES = 2        # 最大重試次數
MAX_ESCALATION_LEVEL = 3     # 最大升級層級
STALL_RETRY_BACKOFF = [30, 60, 120]  # 重試退避時間（秒）

# 停滯檢測配置
STALL_CHECK_INTERVAL_SEC = 60   # 檢查間隔（秒）
STALL_THRESHOLD_SEC = 600       # 超過 10 分鐘無心跳視爲停滯

# 升級路徑: 卡在某部門時向上級升級
_ESCALATION_PATH = {
    "Doing": TaskState.Assigned,   # 六部卡住 → 退回尚書省重新派發
    "Next": TaskState.Assigned,
    "Assigned": TaskState.Menxia,  # 尚書省卡住 → 退回門下省覆核
    "Menxia": TaskState.Zhongshu,  # 門下省卡住 → 退回中書省重新規劃
    "Zhongshu": TaskState.Taizi,   # 中書省卡住 → 退回太子重新起草
}

# 需要監聽的 topics
WATCHED_TOPICS = [
    TOPIC_TASK_CREATED,
    TOPIC_TASK_STATUS,
    TOPIC_TASK_COMPLETED,
    TOPIC_TASK_STALLED,
    TOPIC_TASK_DISPATCH_FAILED,
]


class OrchestratorWorker:
    """事件驅動的編排器 Worker。"""

    def __init__(self):
        self.bus = EventBus()
        self._running = False
        self._stall_checker_task: asyncio.Task | None = None

    async def start(self):
        """啓動 worker 主循環。"""
        await self.bus.connect()

        # 確保所有消費者組
        for topic in WATCHED_TOPICS:
            await self.bus.ensure_consumer_group(topic, GROUP)

        self._running = True
        log.info("🏛️ Orchestrator worker started")

        # 先處理崩潰遺留的 pending 事件
        await self._recover_pending()

        # 啓動停滯檢測後臺任務
        self._stall_checker_task = asyncio.create_task(self._stall_check_loop())

        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                log.error(f"Orchestrator poll error: {e}", exc_info=True)
                await asyncio.sleep(2)

    async def stop(self):
        self._running = False
        if self._stall_checker_task:
            self._stall_checker_task.cancel()
        await self.bus.close()
        log.info("Orchestrator worker stopped")

    async def _recover_pending(self):
        """恢復崩潰前未 ACK 的事件。"""
        for topic in WATCHED_TOPICS:
            events = await self.bus.claim_stale(
                topic, GROUP, CONSUMER, min_idle_ms=30000, count=50
            )
            if events:
                log.info(f"Recovering {len(events)} stale events from {topic}")
                for entry_id, event in events:
                    await self._handle_event(topic, entry_id, event)

    async def _poll_cycle(self):
        """一次輪詢周期：多 topic 同時消費，按 task_id 分組並行處理。"""
        events = await self.bus.consume_multi(
            WATCHED_TOPICS, GROUP, CONSUMER, count=20, block_ms=500
        )
        if not events:
            return

        # 按 task_id 分組：同一任務串行，不同任務並行
        by_task: dict[str, list[tuple[str, str, dict]]] = {}
        for topic, entry_id, event in events:
            task_id = event.get("payload", {}).get("task_id", entry_id)
            by_task.setdefault(task_id, []).append((topic, entry_id, event))

        async def _process_task_events(task_events: list[tuple[str, str, dict]]):
            for topic, entry_id, event in task_events:
                try:
                    await self._handle_event(topic, entry_id, event)
                    await self.bus.ack(topic, GROUP, entry_id)
                except Exception as e:
                    log.error(
                        f"Error handling event {entry_id} from {topic}: {e}",
                        exc_info=True,
                    )

        await asyncio.gather(*[
            _process_task_events(evts) for evts in by_task.values()
        ])

    async def _handle_event(self, topic: str, entry_id: str, event: dict):
        """根據 topic 和 event_type 分發處理。"""
        event_type = event.get("event_type", "")
        trace_id = event.get("trace_id", "")
        payload = event.get("payload", {})

        log.info(f"📨 {topic}/{event_type} trace={trace_id}")

        if topic == TOPIC_TASK_CREATED:
            await self._on_task_created(payload, trace_id)
        elif topic == TOPIC_TASK_STATUS:
            await self._on_task_status(event_type, payload, trace_id)
        elif topic == TOPIC_TASK_COMPLETED:
            await self._on_task_completed(payload, trace_id)
        elif topic == TOPIC_TASK_STALLED:
            await self._on_task_stalled(payload, trace_id)
        elif topic == TOPIC_TASK_DISPATCH_FAILED:
            await self._on_task_dispatch_failed(payload, trace_id)

    async def _on_task_created(self, payload: dict, trace_id: str):
        """任務創建 → 派發給太子 agent 起草。"""
        task_id = payload.get("task_id")
        state = payload.get("state") or TaskState.Taizi.value
        try:
            task_state = TaskState(state)
        except ValueError:
            log.warning(f"Unknown created state: {state!r}, falling back to Taizi")
            task_state = TaskState.Taizi
            state = task_state.value
        agent = STATE_AGENT_MAP.get(task_state, "taizi")

        await self.bus.publish(
            topic=TOPIC_TASK_DISPATCH,
            trace_id=trace_id,
            event_type="task.dispatch.request",
            producer="orchestrator",
            payload={
                **payload,
                "task_id": task_id,
                "agent": agent,
                "state": state,
                "message": payload.get("message") or f"新任務已創建: {payload.get('title', '')}",
            },
        )

    async def _on_task_status(self, event_type: str, payload: dict, trace_id: str):
        """狀態變更 → 自動派發下一個 agent。"""
        task_id = payload.get("task_id")
        new_state_str = payload.get("to", "")

        try:
            new_state = TaskState(new_state_str)
        except ValueError:
            log.warning(f"Unknown state: {new_state_str}")
            return

        # 如果新狀態有對應 agent，自動派發
        agent = STATE_AGENT_MAP.get(new_state)

        # 如果進入 assigned 狀態，需要查找六部對應 agent
        if new_state == TaskState.Assigned:
            org = payload.get("assignee_org", "")
            if org:
                agent = ORG_AGENT_MAP.get(org, agent)
            else:
                # assignee_org 爲空時，無法確定目標部門
                # 派發給尚書省讓其決定分配
                log.warning(
                    f"Task {task_id} entering Assigned without assignee_org, "
                    f"dispatching to shangshu for manual routing"
                )
                agent = "shangshu"

        if agent:
            await self.bus.publish(
                topic=TOPIC_TASK_DISPATCH,
                trace_id=trace_id,
                event_type="task.dispatch.request",
                producer="orchestrator",
                payload={
                    **payload,
                    "task_id": task_id,
                    "agent": agent,
                    "state": new_state_str,
                    "message": payload.get("message") or payload.get("reason") or f"任務已流轉到 {new_state_str}",
                },
            )

    async def _on_task_completed(self, payload: dict, trace_id: str):
        """任務完成 → 記錄日誌。"""
        task_id = payload.get("task_id")
        log.info(f"🎉 Task {task_id} completed. trace={trace_id}")

    async def _on_task_dispatch_failed(self, payload: dict, trace_id: str):
        """派發失敗 → 直接升級或標記阻塞，不再佔用停滯重試語意。"""
        task_id = payload.get("task_id")
        current_state = payload.get("state", "")
        assignee_org = payload.get("assignee_org", "")
        agent = payload.get("agent", "")
        error = payload.get("error", "")
        retryable = bool(payload.get("retryable", False))
        attempts = int(payload.get("attempts", 0))

        log.warning(
            f"🚫 Dispatch failed for task {task_id}: state={current_state} agent={agent} "
            f"retryable={retryable} attempts={attempts} trace={trace_id} error={error}"
        )

        escalate_to = _ESCALATION_PATH.get(current_state)
        if escalate_to:
            escalate_agent = STATE_AGENT_MAP.get(escalate_to, "shangshu")
            log.info(
                f"⬆️ Dispatch failure escalation for {task_id}: {current_state} → {escalate_to.value}"
            )
            await self.bus.publish(
                topic=TOPIC_TASK_ESCALATED,
                trace_id=trace_id,
                event_type="task.escalated",
                producer="orchestrator",
                payload={
                    "task_id": task_id,
                    "from_state": current_state,
                    "to_state": escalate_to.value,
                    "escalation_level": 1,
                    "reason": f"派發失敗：{error or '未知錯誤'}",
                    "dispatch_error": error,
                    "dispatch_attempts": attempts,
                    "dispatch_retryable": retryable,
                },
            )
            await self.bus.publish(
                topic=TOPIC_TASK_DISPATCH,
                trace_id=trace_id,
                event_type="task.dispatch.escalation",
                producer="orchestrator",
                payload={
                    "task_id": task_id,
                    "agent": escalate_agent,
                    "state": escalate_to.value,
                    "message": f"派發失敗後升級處理: {error or '未知錯誤'}",
                    "escalation_level": 1,
                    "dispatch_error": error,
                    "dispatch_attempts": attempts,
                    "dispatch_retryable": retryable,
                },
            )
            return

        log.error(
            f"🚨 Dispatch failure exhausted recovery for {task_id}. Marking as Blocked."
        )
        await self.bus.publish(
            topic=TOPIC_TASK_STATUS,
            trace_id=trace_id,
            event_type="task.state.Blocked",
            producer="orchestrator",
            payload={
                "task_id": task_id,
                "from": current_state,
                "to": TaskState.Blocked.value,
                "reason": f"任務派發失敗且無上級可升級：{error or '未知錯誤'}",
                "assignee_org": assignee_org,
                "dispatch_error": error,
                "dispatch_attempts": attempts,
                "dispatch_retryable": retryable,
            },
        )

    async def _on_task_stalled(self, payload: dict, trace_id: str):
        """任務停滯 → 自動重試或升級。

        恢復策略：
        1. 第一次停滯：在當前狀態重新派發 agent（重試）
        2. 重試耗盡：向上級升級（如六部→尚書省→門下省）
        3. 升級到頂（太子）仍失敗：標記 Blocked + 通知人工介入
        """
        task_id = payload.get("task_id")
        current_state = payload.get("state", "")
        stall_count = int(payload.get("stall_count", 0))
        escalation_level = int(payload.get("escalation_level", 0))

        log.warning(
            f"⏸️ Task {task_id} stalled! state={current_state} "
            f"stall_count={stall_count} escalation={escalation_level} trace={trace_id}"
        )

        # 策略 1: 重試 — 未超過重試次數時，重新派發同一 agent
        if stall_count < MAX_STALL_RETRIES:
            agent = STATE_AGENT_MAP.get(TaskState(current_state)) if current_state else None
            if current_state in ("Doing", "Next"):
                org = payload.get("assignee_org", "")
                agent = ORG_AGENT_MAP.get(org, agent)

            if agent:
                log.info(f"🔄 Retrying task {task_id} → agent '{agent}' (attempt {stall_count + 1})")
                await self.bus.publish(
                    topic=TOPIC_TASK_DISPATCH,
                    trace_id=trace_id,
                    event_type="task.dispatch.retry",
                    producer="orchestrator",
                    payload={
                        "task_id": task_id,
                        "agent": agent,
                        "state": current_state,
                        "message": f"任務停滯重試 (第{stall_count + 1}次)",
                        "stall_count": stall_count + 1,
                    },
                )
                return

        # 策略 2: 升級 — 重試耗盡，向上級流轉
        if escalation_level < MAX_ESCALATION_LEVEL:
            escalate_to = _ESCALATION_PATH.get(current_state)
            if escalate_to:
                escalate_agent = STATE_AGENT_MAP.get(escalate_to, "shangshu")
                log.info(
                    f"⬆️ Escalating task {task_id}: {current_state} → {escalate_to.value} "
                    f"(level {escalation_level + 1})"
                )
                await self.bus.publish(
                    topic=TOPIC_TASK_ESCALATED,
                    trace_id=trace_id,
                    event_type="task.escalated",
                    producer="orchestrator",
                    payload={
                        "task_id": task_id,
                        "from_state": current_state,
                        "to_state": escalate_to.value,
                        "escalation_level": escalation_level + 1,
                        "reason": f"任務在 {current_state} 停滯，升級處理",
                    },
                )
                # 派發給上級 agent
                await self.bus.publish(
                    topic=TOPIC_TASK_DISPATCH,
                    trace_id=trace_id,
                    event_type="task.dispatch.escalation",
                    producer="orchestrator",
                    payload={
                        "task_id": task_id,
                        "agent": escalate_agent,
                        "state": escalate_to.value,
                        "message": f"下級停滯，需上級介入 (從 {current_state} 升級)",
                        "escalation_level": escalation_level + 1,
                    },
                )
                return

        # 策略 3: 所有升級耗盡 → 標記 Blocked，等待人工介入
        log.error(
            f"🚨 Task {task_id} exhausted all recovery options! "
            f"Marking as Blocked. Manual intervention required."
        )
        await self.bus.publish(
            topic=TOPIC_TASK_STATUS,
            trace_id=trace_id,
            event_type="task.state.Blocked",
            producer="orchestrator",
            payload={
                "task_id": task_id,
                "from": current_state,
                "to": TaskState.Blocked.value,
                "reason": f"任務多次停滯（重試{MAX_STALL_RETRIES}次+升級{MAX_ESCALATION_LEVEL}級），需人工介入",
                "assignee_org": payload.get("assignee_org", ""),
            },
        )

    # ── 停滯任務檢測器 ──

    async def _stall_check_loop(self):
        """定時掃描非終止狀態超時任務，發布 task.stalled 事件。"""
        while self._running:
            try:
                await self._check_stalled()
                await asyncio.sleep(STALL_CHECK_INTERVAL_SEC)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Stall check error: {e}", exc_info=True)
                await asyncio.sleep(STALL_CHECK_INTERVAL_SEC)

    async def _check_stalled(self):
        """掃描數據庫中非終止狀態超過閾值未更新的任務。"""
        threshold = datetime.now(timezone.utc) - timedelta(seconds=STALL_THRESHOLD_SEC)

        # 所有非終止的 active 狀態（排除 Blocked，因 Blocked 已確認需人工介入）
        NON_TERMINAL_STATES = [
            s for s in TaskState
            if s not in TERMINAL_STATES and s != TaskState.Blocked
        ]

        async with async_session() as session:
            svc = TaskService(session)
            from sqlalchemy import select
            from ..models.task import Task
            stmt = select(Task).where(
                Task.state.in_(NON_TERMINAL_STATES),
                Task.updated_at < threshold,
                Task.archived == False,  # noqa: E712
            )
            result = await session.execute(stmt)
            stalled_tasks = result.scalars().all()

        for task in stalled_tasks:
            task_id = str(task.task_id)
            state = task.state.value if isinstance(task.state, TaskState) else str(task.state)
            log.warning(
                f"⏰ Detected stalled task {task_id} in state={state}, "
                f"last updated {task.updated_at}"
            )
            await self.bus.publish(
                topic=TOPIC_TASK_STALLED,
                trace_id=task.trace_id or str(uuid.uuid4()),
                event_type="task.stalled.detected",
                producer="orchestrator.stall_checker",
                payload={
                    "task_id": task_id,
                    "state": state,
                    "assignee_org": task.assignee_org or task.org or "",
                    "stall_count": 0,
                    "escalation_level": 0,
                    "last_updated": task.updated_at.isoformat() if task.updated_at else "",
                },
            )


async def run_orchestrator():
    """入口函數 — 用於直接運行 worker。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    worker = OrchestratorWorker()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))

    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_orchestrator())
