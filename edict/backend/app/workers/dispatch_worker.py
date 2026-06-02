"""Dispatch Worker — 消費 task.dispatch 事件，執行 OpenClaw agent 調用。

核心解決舊架構痛點：
- 舊: daemon 線程 + subprocess.run → kill -9 丟失一切
- 新: Redis Streams ACK 保證 → 崩潰後自動重新投遞

流程:
1. 從 task.dispatch stream 消費事件
2. 組裝富上下文 (_build_agent_context)
3. 調用 OpenClaw CLI: `openclaw agent --agent xxx -m "..."`
4. 解析 agent 輸出（kanban_update.py 調用結果）
5. ACK 事件
"""

import asyncio
import json
import logging
import os
import pathlib
import re
import signal
import subprocess
import tempfile
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone

from ..config import get_settings
from ..services.event_bus import (
    EventBus,
    TOPIC_TASK_DISPATCH,
    TOPIC_TASK_DISPATCH_ALERT,
    TOPIC_TASK_DISPATCH_FAILED,
    TOPIC_TASK_DISPATCH_STARTED,
    TOPIC_TASK_STALLED,
    TOPIC_TASK_STATUS,
    TOPIC_AGENT_THOUGHTS,
    TOPIC_AGENT_HEARTBEAT,
)

log = logging.getLogger("edict.dispatcher")

GROUP = "dispatcher"
CONSUMER = "disp-1"


class DispatchError(Exception):
    """帶分類的派發錯誤。"""

    def __init__(self, msg: str, retryable: bool = True):
        super().__init__(msg)
        self.retryable = retryable

# Agent 分組映射 — 用於加載 group 級 prompt
_GROUP_MAP = {
    "taizi": "sansheng",
    "zhongshu": "sansheng",
    "menxia": "sansheng",
    "shangshu": "sansheng",
    "hubu": "liubu",
    "libu": "liubu",
    "bingbu": "liubu",
    "xingbu": "liubu",
    "gongbu": "liubu",
    "libu_hr": "liubu",
    "zaochao": None,
}


def _resolve_agents_dir() -> pathlib.Path:
    """定位 agents/ 目錄。"""
    settings = get_settings()
    project_dir = getattr(settings, "openclaw_project_dir", None)
    if project_dir:
        return pathlib.Path(project_dir) / "agents"
    # 默認: 相對於 edict/backend 上溯到項目根
    return pathlib.Path(__file__).resolve().parents[4] / "agents"


def _build_soul_context(agent_id: str) -> str:
    """拼裝三層 prompt 層級：GLOBAL.md → group/*.md → {agent}/SOUL.md。"""
    agents_dir = _resolve_agents_dir()
    parts = []

    global_md = agents_dir / "GLOBAL.md"
    if global_md.exists():
        parts.append(global_md.read_text(encoding="utf-8"))

    group = _GROUP_MAP.get(agent_id)
    if group:
        group_md = agents_dir / "groups" / f"{group}.md"
        if group_md.exists():
            parts.append(group_md.read_text(encoding="utf-8"))

    soul_md = agents_dir / agent_id / "SOUL.md"
    if soul_md.exists():
        parts.append(soul_md.read_text(encoding="utf-8"))

    return "\n---\n".join(parts) if parts else ""


def _build_task_context(payload: dict) -> str:
    """從 dispatch 事件 payload 中提取結構化任務上下文。"""
    sections = []

    task_id = payload.get("task_id", "")
    title = payload.get("title", "")
    description = payload.get("description", "")
    state = payload.get("state", "")
    org = payload.get("org", "")
    priority = payload.get("priority", "中")
    tags = payload.get("tags", [])

    sections.append(f"## 當前任務\n- ID: {task_id}\n- 標題: {title}\n- 狀態: {state}\n- 部門: {org}\n- 優先級: {priority}")
    if tags:
        sections.append(f"- 標籤: {', '.join(tags)}")
    if description:
        sections.append(f"\n### 任務描述\n{description}")

    report = payload.get("report", "")
    if report:
        sections.append(f"\n### 最新回奏\n{report}")

    # Todos
    todos = payload.get("todos", [])
    if todos:
        todo_lines = []
        for t in todos:
            status_icon = {"completed": "✅", "in-progress": "🔄"}.get(t.get("status", ""), "⬜")
            todo_lines.append(f"  {status_icon} {t.get('title', '')}")
        sections.append(f"\n### 子任務\n" + "\n".join(todo_lines))

    # 最近流轉記錄 (最多 5 條)
    flow_log = payload.get("flow_log", [])
    if flow_log:
        recent = flow_log[-5:]
        flow_lines = [
            f"  - [{e.get('at') or e.get('ts') or ''}] {e.get('from', '')} → {e.get('to', '')}: {e.get('remark') or e.get('reason') or ''}"
            for e in recent
        ]
        sections.append(f"\n### 最近流轉\n" + "\n".join(flow_lines))

    # 最近進展 (最多 3 條)
    progress_log = payload.get("progress_log", [])
    if progress_log:
        recent = progress_log[-3:]
        prog_lines = [
            f"  - [{e.get('at') or e.get('ts') or ''}] {e.get('agentLabel', e.get('agent', ''))}: {e.get('text') or e.get('content') or ''}"
            for e in recent
        ]
        sections.append(f"\n### 最近進展\n" + "\n".join(prog_lines))

    # 阻塞信息
    block = payload.get("block", "")
    if block and block != "無":
        sections.append(f"\n### ⚠️ 阻塞\n{block}")

    return "\n".join(sections)


def _build_reminder(agent_id: str, payload: dict) -> str:
    """在 prompt 尾部注入動態提醒（借鑑 Claude 的 reminderInstructions）。"""
    reminders = []

    state = payload.get("state", "")
    if state == "Doing":
        reminders.append("先創建 todo 分解任務，再開始執行。每完成一步立即用 progress 上報。")
    elif state == "Review":
        reminders.append("這是覆審任務。審核完畢後用 state 命令流轉狀態，附帶審核意見。")
    elif state == "Menxia":
        reminders.append("門下省審核：通過則流轉 Assigned，不通過則退回 Zhongshu 並說明原因。")

    # 如果有未完成的 todos，提醒繼續
    todos = payload.get("todos", [])
    in_progress = [t for t in todos if t.get("status") == "in-progress"]
    not_started = [t for t in todos if t.get("status") == "not-started"]
    if in_progress:
        reminders.append(f"有 {len(in_progress)} 個進行中的子任務，優先完成它們。")
    elif not_started:
        reminders.append(f"有 {len(not_started)} 個待開始的子任務。")

    # 阻塞提醒
    block = payload.get("block", "")
    if block and block != "無":
        reminders.append(f"⚠️ 存在阻塞: {block}。如已解除，先更新狀態再繼續。")

    if not reminders:
        return ""
    return "\n\n## ⚡ Reminder\n" + "\n".join(f"- {r}" for r in reminders)


def _resolve_project_root() -> pathlib.Path:
    """定位項目根目錄。"""
    settings = get_settings()
    project_dir = getattr(settings, "openclaw_project_dir", None)
    if project_dir:
        return pathlib.Path(project_dir)
    return pathlib.Path(__file__).resolve().parents[4]


def _build_memory_context(agent_id: str, task_id: str, payload: dict) -> str:
    """分層注入三級記憶：全局規則 → Agent 經驗 → 任務上下文。"""
    root = _resolve_project_root()
    parts = []

    # 1. 全局共享記憶 — 始終注入
    shared_file = root / "data" / "shared_memory.json"
    if shared_file.exists():
        try:
            shared = json.loads(shared_file.read_text(encoding="utf-8"))
            rules = shared.get("rules", [])
            if rules:
                rule_lines = [r.get("content", "") for r in rules[-20:]]
                parts.append("## 全局規則\n" + "\n".join(f"- {r}" for r in rule_lines if r))
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Agent 永久記憶 — 按相關性過濾，最多 50 條
    agent_mem_file = root / "data" / "agent_memory" / f"{agent_id}.json"
    if agent_mem_file.exists():
        try:
            agent_data = json.loads(agent_mem_file.read_text(encoding="utf-8"))
            memories = agent_data.get("memories", [])
            if memories:
                # 相關性排序：pinned 優先，其次按 tags 交集匹配當前任務
                task_tags = set(payload.get("tags", []))
                task_org = payload.get("org", "")
                if task_org:
                    task_tags.add(task_org)

                def _relevance(m):
                    pinned = 1 if m.get("pinned") else 0
                    overlap = len(task_tags & set(m.get("relevance_tags", [])))
                    is_feedback = 1 if m.get("type") == "feedback" else 0
                    return (pinned, overlap, is_feedback)

                memories.sort(key=_relevance, reverse=True)
                top = memories[:50]
                mem_lines = [f"- [{m.get('type', '')}] {m.get('content', '')}" for m in top]
                parts.append("## 歷史經驗\n" + "\n".join(mem_lines))
        except (json.JSONDecodeError, OSError):
            pass

    # 3. 任務上下文記憶 — 完整注入上遊 Agent 決策鏈
    task_mem_file = root / "data" / "task_memory" / f"{task_id}.json"
    if task_mem_file.exists():
        try:
            task_data = json.loads(task_mem_file.read_text(encoding="utf-8"))
            chain = task_data.get("context_chain", [])
            if chain:
                chain_lines = []
                for c in chain:
                    decisions = ", ".join(c.get("key_decisions", []))
                    warnings = ", ".join(c.get("warnings", []))
                    line = f"- [{c.get('phase', '')}] {c.get('agent', '')}: {decisions}"
                    if warnings:
                        line += f" ⚠️ {warnings}"
                    chain_lines.append(line)
                parts.append("## 上遊決策鏈\n" + "\n".join(chain_lines))
        except (json.JSONDecodeError, OSError):
            pass

    if not parts:
        return ""
    return "\n---\n".join(parts)


# ── Prompt 注入檢測 ──

_INJECTION_PATTERNS = [
    re.compile(r"忽略.{0,20}(指令|規則|協議)", re.IGNORECASE),
    re.compile(r"ignore.{0,20}(instructions|rules|above)", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"你(現在)?是.{0,10}(管理員|超級用戶)", re.IGNORECASE),
    re.compile(r"override|bypass|skip.{0,10}(check|review|approval)", re.IGNORECASE),
]


def _sanitize_agent_output(output: str, agent_id: str) -> tuple[str, list[str]]:
    """檢測 Agent 輸出中的注入模式。返回 (原始文本, 告警列表)。"""
    warnings = []
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(output)
        if match:
            warnings.append(
                f"Agent {agent_id} 輸出觸發注入檢測: '{match.group()}' (pattern: {pattern.pattern})"
            )
    return output, warnings


def _load_agent_skills(agent_id: str, payload: dict) -> str:
    """按任務特徵動態加載 Agent Skills（延遲能力加載）。"""
    agents_dir = _resolve_agents_dir()
    manifest_path = agents_dir / agent_id / "skills" / "manifest.json"
    if not manifest_path.exists():
        return ""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    task_tags = set(payload.get("tags", []))
    task_org = payload.get("org", "")

    matched_skills = []
    for skill in manifest.get("skills", []):
        tag_match = task_tags & set(skill.get("match_tags", []))
        org_match = task_org in skill.get("match_orgs", [])
        if tag_match or org_match:
            skill_path = agents_dir / agent_id / "skills" / skill["file"]
            if skill_path.exists():
                try:
                    matched_skills.append(skill_path.read_text(encoding="utf-8"))
                except OSError:
                    pass

    if matched_skills:
        return "## 本次任務相關技能\n" + "\n---\n".join(matched_skills)
    return ""


class DispatchWorker:
    """Agent 派發 Worker — 快慢 Agent 分桶並發控制。"""

    # 快/慢 Agent 分桶 — 互不阻塞
    _BUCKET_CONFIG = {
        "fast": {"agents": {"taizi", "zhongshu", "menxia", "shangshu", "zaochao"}, "limit": 4},
        "slow": {"agents": {"hubu", "libu", "bingbu", "xingbu", "gongbu", "libu_hr"}, "limit": 3},
    }

    def __init__(self):
        self.bus = EventBus()
        self._running = False
        self._buckets: dict[str, asyncio.Semaphore] = {
            name: asyncio.Semaphore(cfg["limit"])
            for name, cfg in self._BUCKET_CONFIG.items()
        }
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._inflight: set[str] = set()
        # 執行時間記錄（僅用於監控告警）
        self._durations: dict[str, list[float]] = {}
        self._heartbeat_task: asyncio.Task | None = None

    def _get_bucket(self, agent_id: str) -> asyncio.Semaphore:
        """根據 agent 類型返回對應桶的信號量。"""
        for name, cfg in self._BUCKET_CONFIG.items():
            if agent_id in cfg["agents"]:
                return self._buckets[name]
        return self._buckets["slow"]  # 未知 Agent 歸入慢桶

    async def _heartbeat_loop(self):
        """定時發布 worker 心跳，供觀測層使用。"""
        interval = max(5, int(get_settings().heartbeat_interval_sec))
        while self._running:
            try:
                await self.bus.publish(
                    topic=TOPIC_AGENT_HEARTBEAT,
                    trace_id=str(uuid.uuid4()),
                    event_type="worker.heartbeat",
                    producer="dispatcher",
                    payload={
                        "worker": "dispatch-worker",
                        "consumer": CONSUMER,
                        "group": GROUP,
                        "pid": os.getpid(),
                        "active_dispatches": len(self._active_tasks),
                        "inflight": len(self._inflight),
                    },
                )
            except Exception as e:
                log.warning(f"Heartbeat publish failed: {e}")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def start(self):
        await self.bus.connect()
        await self.bus.ensure_consumer_group(TOPIC_TASK_DISPATCH, GROUP)
        self._running = True
        log.info("🚀 Dispatch worker started")

        # 恢復崩潰遺留
        await self._recover_pending()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                log.error(f"Dispatch poll error: {e}", exc_info=True)
                await asyncio.sleep(2)

    async def stop(self):
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        # 等待進行中的 agent 調用完成
        if self._active_tasks:
            log.info(f"Waiting for {len(self._active_tasks)} active dispatches...")
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
        await self.bus.close()
        log.info("Dispatch worker stopped")

    async def _recover_pending(self):
        events = await self.bus.claim_stale(
            TOPIC_TASK_DISPATCH, GROUP, CONSUMER, min_idle_ms=60000, count=20
        )
        if events:
            log.info(f"Recovering {len(events)} stale dispatch events")
            for entry_id, event in events:
                await self._dispatch(entry_id, event)

    async def _poll_cycle(self):
        events = await self.bus.consume(
            TOPIC_TASK_DISPATCH, GROUP, CONSUMER, count=3, block_ms=2000
        )
        for entry_id, event in events:
            # 每個派發在獨立任務中執行，帶並發控制
            task = asyncio.create_task(self._dispatch(entry_id, event))
            task_id = event.get("payload", {}).get("task_id", entry_id)
            self._active_tasks[task_id] = task
            task.add_done_callback(lambda t, tid=task_id: self._active_tasks.pop(tid, None))

    async def _dispatch(self, entry_id: str, event: dict):
        """執行一次 agent 派發（桶級並發控制）。"""
        payload = event.get("payload", {})
        task_id = payload.get("task_id", "")
        agent = payload.get("agent", "")
        message = payload.get("message", "")
        trace_id = event.get("trace_id", "")
        state = payload.get("state", "")

        # 去重：同一任務如果已在派發中，跳過並 ACK
        if task_id in self._inflight:
            log.warning(f"⚡ Skipping duplicate dispatch for task {task_id} (already in-flight)")
            await self.bus.ack(TOPIC_TASK_DISPATCH, GROUP, entry_id)
            return
        self._inflight.add(task_id)

        sem = self._get_bucket(agent)
        async with sem:

            log.info(f"🔄 Dispatching task {task_id} → agent '{agent}' state={state}")

            # 組裝富上下文
            task_context = _build_task_context(payload)
            reminder = _build_reminder(agent, payload)
            memory_context = _build_memory_context(agent, task_id, payload)
            skills_context = _load_agent_skills(agent, payload)
            enriched_message = message
            if task_context:
                enriched_message = f"{message}\n\n---\n{task_context}"
            if memory_context:
                enriched_message = f"{enriched_message}\n\n---\n{memory_context}"
            if skills_context:
                enriched_message = f"{enriched_message}\n\n---\n{skills_context}"
            if reminder:
                enriched_message = f"{enriched_message}\n{reminder}"

            # 發布派發開始事件
            await self.bus.publish(
                topic=TOPIC_TASK_DISPATCH_STARTED,
                trace_id=trace_id,
                event_type="task.dispatch.started",
                producer="dispatcher",
                payload={"task_id": task_id, "agent": agent, "state": state},
            )

            try:
                start_time = time.monotonic()
                result = await self._call_openclaw(agent, enriched_message, task_id, trace_id, payload)
                elapsed = time.monotonic() - start_time

                # 記錄執行時間（僅用於監控和告警）
                self._durations.setdefault(agent, []).append(elapsed)
                if len(self._durations[agent]) > 20:
                    self._durations[agent] = self._durations[agent][-20:]
                avg = sum(self._durations[agent]) / len(self._durations[agent])
                if elapsed > 2 * avg and elapsed > 120:
                    log.warning(f"⚠️ Agent {agent} slowdown: {elapsed:.0f}s (avg: {avg:.0f}s)")

                # Prompt 注入檢測
                stdout = result.get("stdout", "")
                stdout, injection_warnings = _sanitize_agent_output(stdout, agent)
                if injection_warnings:
                    for w in injection_warnings:
                        log.warning(f"🛡️ {w}")
                    # 發布注入告警事件
                    await self.bus.publish(
                        topic=TOPIC_TASK_DISPATCH_ALERT,
                        trace_id=trace_id,
                        event_type="agent.injection.detected",
                        producer="dispatcher",
                        payload={
                            "task_id": task_id,
                            "agent": agent,
                            "state": state,
                            "warnings": injection_warnings,
                        },
                    )

                # 發布 agent 輸出
                await self.bus.publish(
                    topic=TOPIC_AGENT_THOUGHTS,
                    trace_id=trace_id,
                    event_type="agent.output",
                    producer=f"agent.{agent}",
                    payload={
                        "task_id": task_id,
                        "agent": agent,
                        "output": stdout,
                        "return_code": result.get("returncode", -1),
                        "injection_warnings": injection_warnings or None,
                    },
                )

                if result.get("returncode") == 0:
                    log.info(f"✅ Agent '{agent}' completed task {task_id}")
                    await self.bus.ack(TOPIC_TASK_DISPATCH, GROUP, entry_id)
                    return

                # 失敗分類
                stderr = result.get("stderr", "")
                if "TIMEOUT" in stderr:
                    raise DispatchError("Agent timeout", retryable=True)
                elif "command not found" in stderr:
                    raise DispatchError("openclaw binary missing", retryable=False)
                elif result["returncode"] in (1, 2):
                    raise DispatchError(
                        f"Agent failed: rc={result['returncode']}", retryable=True
                    )
                else:
                    raise DispatchError(
                        f"Unknown error: rc={result['returncode']}", retryable=False
                    )

            except DispatchError as e:
                delivery_count = await self.bus.get_delivery_count(
                    TOPIC_TASK_DISPATCH, GROUP, entry_id
                )

                if e.retryable and delivery_count < 3:
                    log.warning(
                        f"🔄 Retryable failure for {task_id}, attempt {delivery_count + 1}/3: {e}"
                    )
                    return  # 不 ACK → Redis 自動重投遞

                # 不可重試 or 重試耗盡 → ACK + 發布失敗事件 + DLQ
                log.error(
                    f"💀 Dispatch dead-lettered: {task_id} → {agent} "
                    f"(retryable={e.retryable}, attempts={delivery_count + 1}): {e}"
                )
                await self.bus.publish(
                    topic=TOPIC_TASK_DISPATCH_FAILED,
                    trace_id=trace_id,
                    event_type="task.dispatch.failed",
                    producer="dispatcher",
                    payload={
                        "task_id": task_id,
                        "agent": agent,
                        "state": state,
                        "assignee_org": payload.get("assignee_org", ""),
                        "error": str(e),
                        "retryable": e.retryable,
                        "attempts": delivery_count + 1,
                    },
                )
                await self.bus.publish(
                    topic="dead_letter",
                    trace_id=trace_id,
                    event_type="task.dispatch.dead_letter",
                    producer="dispatcher",
                    payload={
                        "task_id": task_id,
                        "agent": agent,
                        "error": str(e),
                    },
                )
                await self.bus.ack(TOPIC_TASK_DISPATCH, GROUP, entry_id)

            except Exception as e:
                log.error(f"❌ Dispatch failed: task {task_id} → {agent}: {e}", exc_info=True)
                # 不 ACK → Redis 會重新投遞給其他消費者
            finally:
                self._inflight.discard(task_id)

    async def _call_openclaw(
        self,
        agent: str,
        message: str,
        task_id: str,
        trace_id: str,
        payload: dict | None = None,
    ) -> dict:
        """異步調用 OpenClaw CLI — 在線程池中執行，帶富上下文注入。"""
        settings = get_settings()
        cmd = [
            getattr(settings, "openclaw_bin", "openclaw"),
            "agent",
            "--agent", agent,
            "-m", message,
        ]

        env = os.environ.copy()
        env["EDICT_TASK_ID"] = task_id
        env["EDICT_TRACE_ID"] = trace_id
        env["EDICT_API_URL"] = f"http://localhost:{settings.port}"

        # 注入額外上下文環境變量
        if payload:
            env["EDICT_TASK_TITLE"] = payload.get("title", "")
            env["EDICT_TASK_STATE"] = payload.get("state", "")
            env["EDICT_TASK_ORG"] = payload.get("org", "")
            env["EDICT_TASK_PRIORITY"] = payload.get("priority", "中")
            tags = payload.get("tags", [])
            if tags:
                env["EDICT_TASK_TAGS"] = ",".join(str(t) for t in tags)

        # 寫入臨時上下文文件（大型上下文通過文件傳遞，避免命令行參數過長）
        context_file = None
        if payload:
            context_data = {
                "task_id": task_id,
                "trace_id": trace_id,
                "title": payload.get("title", ""),
                "description": payload.get("description", ""),
                "state": payload.get("state", ""),
                "org": payload.get("org", ""),
                "priority": payload.get("priority", "中"),
                "tags": payload.get("tags", []),
                "todos": payload.get("todos", []),
                "flow_log": payload.get("flow_log", [])[-10:],
                "progress_log": payload.get("progress_log", [])[-5:],
                "block": payload.get("block", ""),
                "meta": payload.get("meta", {}),
            }
            try:
                fd, context_file = tempfile.mkstemp(suffix=".json", prefix=f"edict_ctx_{task_id}_")
                with os.fdopen(fd, "w") as f:
                    json.dump(context_data, f, ensure_ascii=False, indent=2)
                env["EDICT_CONTEXT_FILE"] = context_file
            except Exception as e:
                log.warning(f"Failed to write context file for {task_id}: {e}")

        log.debug(f"Executing: {' '.join(cmd)}")

        def _run():
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    env=env,
                    cwd=getattr(settings, "openclaw_project_dir", None) or None,
                )
                return {
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[-5000:] if proc.stdout else "",
                    "stderr": proc.stderr[-2000:] if proc.stderr else "",
                }
            except subprocess.TimeoutExpired:
                return {"returncode": -1, "stdout": "", "stderr": "TIMEOUT after 300s"}
            except FileNotFoundError:
                return {"returncode": -1, "stdout": "", "stderr": "openclaw command not found"}
            finally:
                # 清理臨時上下文文件
                if context_file:
                    try:
                        os.unlink(context_file)
                    except OSError:
                        pass

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run)


async def run_dispatcher():
    """入口函數 — 用於直接運行 worker。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    worker = DispatchWorker()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))

    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_dispatcher())
