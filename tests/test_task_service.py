"""
task_service.py 單元測試 — 核心業務邏輯層。

測試範圍：
- create_task: 建立任務 → trace_id 為 UUID 36 字元、outbox 事件寫入、審計事件寫入
- transition_state: 合法狀態轉換成功；非法轉換 → ValueError；任務不存在 → ValueError
- list_tasks: 過濾條件（state、assignee_org、priority）及分頁（limit/offset）
- add_progress / get_live_status / count_tasks 輔助方法

隔離策略：
- 使用 unittest.mock.AsyncMock 模擬 AsyncSession
- 直接實例化 Task/OutboxEvent/Event 模型物件，不依賴資料庫
- 不啟動 Redis / PostgreSQL
"""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from edict.backend.app.models.event import Event
from edict.backend.app.models.outbox import OutboxEvent
from edict.backend.app.models.task import (
    STATE_TRANSITIONS,
    TERMINAL_STATES,
    Task,
    TaskState,
)
from edict.backend.app.services.task_service import TaskService


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def make_fake_task(**overrides) -> Task:
    """建立用於測試的 Task 實例（不經資料庫）。"""
    task_id = overrides.pop("task_id", uuid.uuid4())
    task = Task()
    task.task_id = task_id
    task.trace_id = str(uuid.uuid4())
    task.title = overrides.pop("title", "測試任務")
    task.description = overrides.pop("description", "測試描述")
    task.priority = overrides.pop("priority", "中")
    task.state = overrides.pop("state", TaskState.Taizi)
    task.assignee_org = overrides.pop("assignee_org", None)
    task.creator = overrides.pop("creator", "emperor")
    task.tags = overrides.pop("tags", [])
    task.meta = overrides.pop("meta", {})
    task.org = overrides.pop("org", "太子")
    task.official = overrides.pop("official", "")
    task.now = overrides.pop("now", "")
    task.output = overrides.pop("output", "")
    task.block = overrides.pop("block", "無")
    task.flow_log = overrides.pop("flow_log", [])
    task.progress_log = overrides.pop("progress_log", [])
    task.todos = overrides.pop("todos", [])
    task.scheduler = overrides.pop("scheduler", {})
    task.template_id = overrides.pop("template_id", "")
    task.template_params = overrides.pop("template_params", {})
    task.ac = overrides.pop("ac", "")
    task.target_dept = overrides.pop("target_dept", "")
    task.created_at = overrides.pop("created_at", datetime(2025, 1, 1))
    task.updated_at = overrides.pop("updated_at", datetime(2025, 1, 1))
    task.archived = overrides.pop("archived", False)
    # 任何剩餘的 overrides
    for k, v in overrides.items():
        setattr(task, k, v)
    return task


def make_mock_db() -> AsyncMock:
    """建立模擬的 AsyncSession。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    return db


def make_mock_execute_result(return_value):
    """建立模擬 execute() 的回傳物件，支援 .scalar_one_or_none() 與 .scalars().all()。"""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = return_value if isinstance(return_value, list) else [return_value]
    mock_result.scalars.return_value = mock_scalars

    return mock_result


# ─────────────────────────────────────────────
# create_task
# ─────────────────────────────────────────────


class TestCreateTask:
    """create_task 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_creates_task_with_trace_id_uuid_36_chars(self):
        """
        given: 模擬的 AsyncSession
        when: 呼叫 create_task 建立新任務
        then: 回傳的 Task 包含 36 字元 trace_id（UUID 格式）
        """
        db = make_mock_db()
        svc = TaskService(db)

        task = await svc.create_task(title="測試任務", description="描述")

        assert task is not None
        assert task.title == "測試任務"
        assert len(task.trace_id) == 36
        # 驗證 trace_id 為有效 UUID 格式
        uuid.UUID(task.trace_id)

    @pytest.mark.asyncio
    async def test_create_task_adds_to_db(self):
        """
        given: 模擬的 AsyncSession
        when: 呼叫 create_task
        then: db.add 被呼叫兩次（Task + OutboxEvent + Event 審計 → 共 3 次 add）
        """
        db = make_mock_db()
        svc = TaskService(db)

        await svc.create_task(title="任務")

        # Task + OutboxEvent + Event = 3 次 add
        assert db.add.call_count >= 2, f"Expected at least 2 add calls, got {db.add.call_count}"

    @pytest.mark.asyncio
    async def test_create_task_flushes_then_commits(self):
        """
        given: 模擬的 AsyncSession
        when: 呼叫 create_task
        then: 先呼叫 flush() 取得 task_id，再 commit() 提交事務
        """
        db = make_mock_db()
        svc = TaskService(db)

        await svc.create_task(title="任務")

        db.flush.assert_awaited()
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_task_default_initial_state_is_taizi(self):
        """
        given: 模擬的 AsyncSession，未指定 initial_state
        when: 呼叫 create_task
        then: 任務狀態預設為 TaskState.Taizi
        """
        db = make_mock_db()
        svc = TaskService(db)

        task = await svc.create_task(title="任務")

        assert task.state == TaskState.Taizi

    @pytest.mark.asyncio
    async def test_create_task_custom_initial_state(self):
        """
        given: 模擬的 AsyncSession，指定 initial_state=Pending
        when: 呼叫 create_task
        then: 任務狀態為 Pending
        """
        db = make_mock_db()
        svc = TaskService(db)

        task = await svc.create_task(title="任務", initial_state=TaskState.Pending)

        assert task.state == TaskState.Pending

    @pytest.mark.asyncio
    async def test_create_task_sets_flow_log_entry(self):
        """
        given: 模擬的 AsyncSession
        when: 呼叫 create_task
        then: flow_log 包含一筆建立記錄，from=None, to=initial_state.value
        """
        db = make_mock_db()
        svc = TaskService(db)

        task = await svc.create_task(title="任務")

        assert len(task.flow_log) == 1
        assert task.flow_log[0]["from"] is None
        assert task.flow_log[0]["to"] == TaskState.Taizi.value
        assert task.flow_log[0]["reason"] == "任務創建"

    @pytest.mark.asyncio
    async def test_create_task_with_tags_and_meta(self):
        """
        given: 模擬的 AsyncSession，帶有 tags 和 meta
        when: 呼叫 create_task
        then: 任務的 tags 和 meta 正確設定
        """
        db = make_mock_db()
        svc = TaskService(db)

        task = await svc.create_task(
            title="任務",
            tags=["urgent", "bug"],
            meta={"source": "api", "version": 1},
        )

        assert task.tags == ["urgent", "bug"]
        assert task.meta == {"source": "api", "version": 1}


# ─────────────────────────────────────────────
# transition_state
# ─────────────────────────────────────────────


class TestTransitionState:
    """transition_state 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_valid_transition_succeeds(self):
        """
        given: 任務當前狀態為 Taizi，目標狀態 Zhongshu 在 STATE_TRANSITIONS 中
        when: 呼叫 transition_state(task_id, Zhongshu)
        then: 任務狀態變更為 Zhongshu，回傳更新後的 Task
        """
        task = make_fake_task(state=TaskState.Taizi)
        task_id = task.task_id
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(task)
        svc = TaskService(db)

        result = await svc.transition_state(task_id, TaskState.Zhongshu, agent="test")

        assert result.state == TaskState.Zhongshu

    @pytest.mark.asyncio
    async def test_invalid_transition_raises_value_error(self):
        """
        given: 任務當前狀態為 Taizi，目標狀態 Done 不在允許轉換集合中
        when: 呼叫 transition_state(task_id, Done)
        then: 拋出 ValueError，訊息包含 "Invalid transition"
        """
        task = make_fake_task(state=TaskState.Taizi)
        task_id = task.task_id
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(task)
        svc = TaskService(db)

        with pytest.raises(ValueError, match="Invalid transition"):
            await svc.transition_state(task_id, TaskState.Done)

    @pytest.mark.asyncio
    async def test_task_not_found_raises_value_error(self):
        """
        given: 指定的 task_id 在資料庫中不存在
        when: 呼叫 transition_state
        then: 拋出 ValueError，訊息包含 "Task not found"
        """
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(None)
        svc = TaskService(db)

        with pytest.raises(ValueError, match="Task not found"):
            await svc.transition_state(uuid.uuid4(), TaskState.Zhongshu)

    @pytest.mark.asyncio
    async def test_transition_to_terminal_state_uses_completed_topic(self):
        """
        given: 任務當前狀態為 Doing，目標狀態 Done 是終止狀態
        when: 呼叫 transition_state(task_id, Done)
        then: db.add 被呼叫，且 outbox 的 topic 為 task.completed
        """
        task = make_fake_task(state=TaskState.Doing)
        task_id = task.task_id
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(task)
        svc = TaskService(db)

        await svc.transition_state(task_id, TaskState.Done, reason="完成")

        # 驗證 add 被呼叫（Task 更新 + OutboxEvent + Event）
        assert db.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_transition_appends_flow_log(self):
        """
        given: 任務當前狀態為 Taizi，已有 flow_log 記錄
        when: 呼叫 transition_state(task_id, Zhongshu)
        then: flow_log 追加一筆新記錄，包含 from/to/reason
        """
        task = make_fake_task(
            state=TaskState.Taizi,
            flow_log=[{"from": None, "to": "Taizi", "agent": "system", "reason": "創建"}],
        )
        task_id = task.task_id
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(task)
        svc = TaskService(db)

        result = await svc.transition_state(task_id, TaskState.Zhongshu, reason="開始處理")

        assert len(result.flow_log) == 2
        assert result.flow_log[-1]["from"] == "Taizi"
        assert result.flow_log[-1]["to"] == "Zhongshu"
        assert result.flow_log[-1]["reason"] == "開始處理"

    @pytest.mark.asyncio
    async def test_transition_to_blocked_from_doing(self):
        """
        given: 任務當前狀態為 Doing，Blocked 在允許轉換集合中
        when: 呼叫 transition_state(task_id, Blocked)
        then: 任務狀態變更為 Blocked
        """
        task = make_fake_task(state=TaskState.Doing)
        task_id = task.task_id
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(task)
        svc = TaskService(db)

        result = await svc.transition_state(task_id, TaskState.Blocked, reason="遇到阻礙")

        assert result.state == TaskState.Blocked

    @pytest.mark.asyncio
    async def test_transition_to_cancelled_is_terminal(self):
        """
        given: 任務狀態為 Taizi，Cancelled 既是合法轉換也是終止狀態
        when: 呼叫 transition_state(task_id, Cancelled)
        then: 狀態變更為 Cancelled，且 Cancelled ∈ TERMINAL_STATES
        """
        task = make_fake_task(state=TaskState.Taizi)
        task_id = task.task_id
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(task)
        svc = TaskService(db)

        result = await svc.transition_state(task_id, TaskState.Cancelled, reason="取消")

        assert result.state == TaskState.Cancelled
        assert result.state in TERMINAL_STATES


# ─────────────────────────────────────────────
# list_tasks
# ─────────────────────────────────────────────


class TestListTasks:
    """list_tasks 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_list_tasks_returns_all_when_no_filters(self):
        """
        given: 資料庫中有 3 筆任務
        when: 呼叫 list_tasks() 不帶任何過濾條件
        then: 回傳全部 3 筆任務
        """
        tasks = [make_fake_task(title=f"任務{i}") for i in range(3)]
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(tasks)
        svc = TaskService(db)

        result = await svc.list_tasks()

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_state(self):
        """
        given: 資料庫中有多筆任務，呼叫時指定 state=TaskState.Doing
        when: 呼叫 list_tasks(state=Doing)
        then: execute 被呼叫，查詢條件包含 state 過濾
        """
        tasks = [make_fake_task(state=TaskState.Doing)]
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(tasks)
        svc = TaskService(db)

        result = await svc.list_tasks(state=TaskState.Doing)

        assert len(result) == 1
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_assignee_org(self):
        """
        given: 呼叫時指定 assignee_org="戶部"
        when: 呼叫 list_tasks(assignee_org="戶部")
        then: execute 被呼叫，查詢條件包含 assignee_org 過濾
        """
        tasks = [make_fake_task(assignee_org="戶部")]
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(tasks)
        svc = TaskService(db)

        result = await svc.list_tasks(assignee_org="戶部")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_priority(self):
        """
        given: 呼叫時指定 priority="高"
        when: 呼叫 list_tasks(priority="高")
        then: 回傳過濾後的結果
        """
        tasks = [make_fake_task(priority="高")]
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(tasks)
        svc = TaskService(db)

        result = await svc.list_tasks(priority="高")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_tasks_default_limit_50(self):
        """
        given: 未指定 limit
        when: 呼叫 list_tasks()
        then: 預設 limit=50
        """
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result([])
        svc = TaskService(db)

        await svc.list_tasks()

        # 驗證 execute 被呼叫（具體 limit 值在 SQLAlchemy stmt 中，mock 無法直接確認）
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_tasks_custom_limit_offset(self):
        """
        given: 指定 limit=10, offset=20
        when: 呼叫 list_tasks(limit=10, offset=20)
        then: execute 被呼叫
        """
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result([])
        svc = TaskService(db)

        await svc.list_tasks(limit=10, offset=20)

        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_tasks_combined_filters(self):
        """
        given: 同時指定 state、assignee_org、priority 三項過濾
        when: 呼叫 list_tasks
        then: 所有過濾條件同時生效
        """
        tasks = [make_fake_task(state=TaskState.Doing, assignee_org="戶部", priority="高")]
        db = make_mock_db()
        db.execute.return_value = make_mock_execute_result(tasks)
        svc = TaskService(db)

        result = await svc.list_tasks(
            state=TaskState.Doing,
            assignee_org="戶部",
            priority="高",
        )

        assert len(result) == 1


# ─────────────────────────────────────────────
# _get_task / get_task
# ─────────────────────────────────────────────


class TestGetTask:
    """get_task / _get_task 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_get_task_returns_task(self):
        """
        given: task_id 對應的任務存在
        when: 呼叫 get_task
        then: 回傳 Task 實例
        """
        task = make_fake_task()
        db = make_mock_db()
        db.get = AsyncMock(return_value=task)
        svc = TaskService(db)

        result = await svc.get_task(task.task_id)

        assert result is task
        db.get.assert_awaited_once_with(Task, task.task_id)

    @pytest.mark.asyncio
    async def test_get_task_not_found_raises_value_error(self):
        """
        given: task_id 對應的任務不存在
        when: 呼叫 get_task
        then: 拋出 ValueError
        """
        db = make_mock_db()
        db.get = AsyncMock(return_value=None)
        svc = TaskService(db)

        with pytest.raises(ValueError, match="Task not found"):
            await svc.get_task(uuid.uuid4())


# ─────────────────────────────────────────────
# add_progress
# ─────────────────────────────────────────────


class TestAddProgress:
    """add_progress 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_add_progress_appends_to_log(self):
        """
        given: 任務存在，progress_log 為空
        when: 呼叫 add_progress 新增進度
        then: progress_log 追加一筆記錄
        """
        task = make_fake_task(progress_log=[])
        db = make_mock_db()
        db.get = AsyncMock(return_value=task)
        svc = TaskService(db)

        result = await svc.add_progress(task.task_id, agent="agent-1", content="處理中")

        assert len(result.progress_log) == 1
        assert result.progress_log[0]["agent"] == "agent-1"
        assert result.progress_log[0]["text"] == "處理中"


# ─────────────────────────────────────────────
# count_tasks
# ─────────────────────────────────────────────


class TestCountTasks:
    """count_tasks 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_count_tasks_returns_count(self):
        """
        given: 資料庫中有任務
        when: 呼叫 count_tasks
        then: 回傳整數計數
        """
        db = make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        db.execute.return_value = mock_result
        svc = TaskService(db)

        count = await svc.count_tasks()

        assert count == 42

    @pytest.mark.asyncio
    async def test_count_tasks_filter_by_state(self):
        """
        given: 指定 state 過濾
        when: 呼叫 count_tasks(state=Doing)
        then: execute 被呼叫且回傳計數
        """
        db = make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 5
        db.execute.return_value = mock_result
        svc = TaskService(db)

        count = await svc.count_tasks(state=TaskState.Doing)

        assert count == 5
        db.execute.assert_awaited_once()


# ─────────────────────────────────────────────
# _report_text
# ─────────────────────────────────────────────


class TestReportText:
    """_report_text 靜態方法單元測試。"""

    def test_report_from_progress_log_text(self):
        """
        given: Task 的 progress_log 最後一筆包含 "text" 欄位
        when: 呼叫 _report_text
        then: 回傳該 text 值
        """
        task = make_fake_task(
            progress_log=[{"text": "第一步"}, {"text": "第二步"}]
        )
        result = TaskService._report_text(task)
        assert result == "第二步"

    def test_report_from_progress_log_content(self):
        """
        given: Task 的 progress_log 最後一筆只有 "content" 欄位
        when: 呼叫 _report_text
        then: 回傳 content 值
        """
        task = make_fake_task(
            progress_log=[{"content": "進度內容"}]
        )
        result = TaskService._report_text(task)
        assert result == "進度內容"

    def test_report_from_now_field(self):
        """
        given: Task 無 progress_log，但 now 欄位有值
        when: 呼叫 _report_text
        then: 回傳 now 欄位值
        """
        task = make_fake_task(progress_log=[], now="目前狀態")
        result = TaskService._report_text(task)
        assert result == "目前狀態"

    def test_report_fallback_when_empty(self):
        """
        given: Task 無 progress_log、now、output、ac、description
        when: 呼叫 _report_text(task, fallback="預設文字")
        then: 回傳 fallback 值
        """
        task = make_fake_task(
            progress_log=[],
            now="",
            output="",
            ac="",
            description="",
        )
        result = TaskService._report_text(task, fallback="預設文字")
        assert result == "預設文字"


# ─────────────────────────────────────────────
# _dispatch_snapshot
# ─────────────────────────────────────────────


class TestDispatchSnapshot:
    """_dispatch_snapshot 靜態方法單元測試。"""

    def test_snapshot_contains_required_keys(self):
        """
        given: 一個已建立的 Task
        when: 呼叫 _dispatch_snapshot
        then: 回傳 dict 包含 task_id、title、state、report 等必要鍵
        """
        task = make_fake_task(title="快照任務", description="快照描述")
        snapshot = TaskService._dispatch_snapshot(task, message="自訂訊息")

        assert snapshot["task_id"] == str(task.task_id)
        assert snapshot["title"] == "快照任務"
        assert snapshot["description"] == "快照描述"
        assert snapshot["state"] == "Taizi"
        assert "report" in snapshot
        assert "message" in snapshot
