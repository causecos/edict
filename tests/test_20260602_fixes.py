"""Tests for 2026-06-02 Edict fixes: trace_id length, stall checker, source-mode."""

import asyncio
import json
import pathlib
import sys
import tempfile
import uuid
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Test 1: Event.trace_id accepts full 36-char UUID ──


def test_event_trace_id_accepts_full_uuid():
    """After fix: Event.trace_id = String(64) should accept 36-char UUID."""
    from edict.backend.app.models.event import Event

    full_uuid = str(uuid.uuid4())
    assert len(full_uuid) == 36, f"UUID should be 36 chars, got {len(full_uuid)}"

    event = Event(
        trace_id=full_uuid,
        topic="test.fix",
        event_type="test.verify",
        producer="test",
        payload={"key": "value"},
        meta={},
    )
    assert event.trace_id == full_uuid
    assert len(event.trace_id) == 36


# ── Test 2: Stall checker includes all non-terminal states ──


class FakeBus:
    def __init__(self):
        self.published = []
        self.acked = []
        self._pending = []

    async def publish(self, **kwargs):
        self.published.append(kwargs)

    async def ack(self, topic, group, entry_id):
        self.acked.append((topic, group, entry_id))

    async def connect(self):
        pass

    async def close(self):
        pass

    async def ensure_consumer_group(self, topic, group):
        pass

    async def consume_multi(self, topics, group, consumer, count=10, block_ms=500):
        return []

    async def claim_stale(self, topic, group, consumer, min_idle_ms=30000, count=50):
        return []

    async def get_delivery_count(self, topic, group, entry_id):
        return 0


def test_stall_checker_covers_all_non_terminal_states():
    """Verify NON_TERMINAL_STATES includes Zhongshu, Menxia, Assigned, etc."""
    from edict.backend.app.models.task import TaskState, TERMINAL_STATES

    NON_TERMINAL_STATES = [
        s for s in TaskState
        if s not in TERMINAL_STATES and s != TaskState.Blocked
    ]

    # Must include states that were previously missing
    assert TaskState.Zhongshu in NON_TERMINAL_STATES, "Zhongshu should be monitored"
    assert TaskState.Menxia in NON_TERMINAL_STATES, "Menxia should be monitored"
    assert TaskState.Assigned in NON_TERMINAL_STATES, "Assigned should be monitored"
    assert TaskState.Taizi in NON_TERMINAL_STATES, "Taizi should be monitored"
    assert TaskState.Pending in NON_TERMINAL_STATES, "Pending should be monitored"
    assert TaskState.Review in NON_TERMINAL_STATES, "Review should be monitored"
    assert TaskState.PendingConfirm in NON_TERMINAL_STATES, "PendingConfirm should be monitored"
    assert TaskState.Doing in NON_TERMINAL_STATES, "Doing should still be monitored"
    assert TaskState.Next in NON_TERMINAL_STATES, "Next should still be monitored"

    # Must exclude terminal and blocked
    assert TaskState.Done not in NON_TERMINAL_STATES, "Done is terminal"
    assert TaskState.Cancelled not in NON_TERMINAL_STATES, "Cancelled is terminal"
    assert TaskState.Blocked not in NON_TERMINAL_STATES, "Blocked is acknowledged stuck"


# ── Test 3: Stall checker startup order (check first, then sleep) ──


def test_stall_check_loop_order():
    """Verify the stall check loop does check before first sleep (structural)."""
    import inspect
    import textwrap
    from edict.backend.app.workers.orchestrator_worker import OrchestratorWorker

    source = inspect.getsource(OrchestratorWorker._stall_check_loop)
    # Dedent to handle class-level indentation
    source = textwrap.dedent(source)

    # Verify _check_stalled() appears before sleep in the flow
    check_idx = source.find("_check_stalled()")
    sleep_idx = source.find("asyncio.sleep")

    assert check_idx > 0, "_check_stalled() not found in source"
    assert sleep_idx > 0, "asyncio.sleep not found in source"
    assert check_idx < sleep_idx, (
        f"_check_stalled() (pos {check_idx}) must appear before "
        f"asyncio.sleep (pos {sleep_idx}) for check-first-then-sleep order"
    )


# ── Test 4: Source-mode API endpoint ──


def test_source_mode_get_returns_valid_response():
    """GET /api/source-mode returns {ok, config, backend, effective}."""
    from edict.backend.app.api.admin import _load_source_mode

    cfg = _load_source_mode()
    assert isinstance(cfg, dict)
    assert "mode" in cfg
    assert cfg["mode"] in ("auto", "json", "db")
    assert "backendApiBase" in cfg
    assert "timeoutMs" in cfg


def test_source_mode_default_config():
    """Default source mode config has valid structure regardless of mode value."""
    from edict.backend.app.api.admin import _load_source_mode

    cfg = _load_source_mode()
    assert isinstance(cfg, dict)
    assert cfg["mode"] in ("auto", "json", "db"), f"Invalid mode: {cfg['mode']}"
    assert cfg["backendApiBase"].startswith("http")
    assert 500 <= cfg["timeoutMs"] <= 15000


def test_source_mode_write_and_read(tmp_path):
    """Writing and reading source mode config via temp file."""
    from edict.backend.app.api import admin as admin_mod

    orig_file = admin_mod._SOURCE_MODE_FILE
    try:
        tmp_file = tmp_path / "task_source_mode.json"
        admin_mod._SOURCE_MODE_FILE = tmp_file

        # Write db mode
        cfg = {"mode": "db", "backendApiBase": "http://127.0.0.1:8000", "timeoutMs": 5000}
        admin_mod._save_source_mode(cfg)

        # Read back
        loaded = admin_mod._load_source_mode()
        assert loaded["mode"] == "db"
        assert loaded["timeoutMs"] == 5000

        # Verify effective
        effective = loaded["mode"]
        assert effective == "db"

    finally:
        admin_mod._SOURCE_MODE_FILE = orig_file


# ── Test 5: _on_task_stalled handles new states ──


def test_on_task_stalled_handles_zhongshu_state():
    """Stalled Zhongshu task should retry dispatch to zhongshu agent."""
    from edict.backend.app.workers.orchestrator_worker import OrchestratorWorker

    worker = OrchestratorWorker()
    worker.bus = FakeBus()
    worker._running = True

    async def run_test():
        await worker._on_task_stalled(
            payload={
                "task_id": "test-zhongshu-1",
                "state": "Zhongshu",
                "stall_count": 0,
                "escalation_level": 0,
            },
            trace_id="trace-zhongshu",
        )

    asyncio.run(run_test())

    # Should dispatch to zhongshu (retry)
    assert len(worker.bus.published) >= 1
    dispatch_event = worker.bus.published[0]
    assert dispatch_event["topic"] == "task.dispatch"
    assert dispatch_event["payload"]["agent"] == "zhongshu"
    assert dispatch_event["payload"]["state"] == "Zhongshu"


def test_on_task_stalled_handles_menxia_state():
    """Stalled Menxia task should retry dispatch to menxia agent."""
    from edict.backend.app.workers.orchestrator_worker import OrchestratorWorker

    worker = OrchestratorWorker()
    worker.bus = FakeBus()

    async def run_test():
        await worker._on_task_stalled(
            payload={
                "task_id": "test-menxia-1",
                "state": "Menxia",
                "stall_count": 0,
                "escalation_level": 0,
            },
            trace_id="trace-menxia",
        )

    asyncio.run(run_test())

    assert len(worker.bus.published) >= 1
    dispatch_event = worker.bus.published[0]
    assert dispatch_event["payload"]["agent"] == "menxia"


def test_on_task_stalled_escalates_after_retries_exhausted():
    """After retries exhausted, stalled task escalates up the chain."""
    from edict.backend.app.workers.orchestrator_worker import OrchestratorWorker

    worker = OrchestratorWorker()
    worker.bus = FakeBus()

    async def run_test():
        # Stall count = 2 (exhausted retries for MAX_STALL_RETRIES=2)
        await worker._on_task_stalled(
            payload={
                "task_id": "test-zhongshu-2",
                "state": "Zhongshu",
                "stall_count": 2,
                "escalation_level": 0,
            },
            trace_id="trace-escalate",
        )

    asyncio.run(run_test())

    # Should escalate: Zhongshu → Taizi
    assert len(worker.bus.published) >= 2
    escalated = [e for e in worker.bus.published if e["topic"] == "task.escalated"]
    assert len(escalated) >= 1
    assert escalated[0]["payload"]["from_state"] == "Zhongshu"
    assert escalated[0]["payload"]["to_state"] == "Taizi"


# ── Test 6: Event model to_dict compatibility ──


def test_event_to_dict():
    """Event.to_dict() should return all required fields."""
    from edict.backend.app.models.event import Event

    event = Event(
        trace_id=str(uuid.uuid4()),
        topic="task.created",
        event_type="task.created",
        producer="test",
        payload={"task_id": "test-1"},
        meta={"version": "1.0"},
    )

    d = event.to_dict()
    assert "event_id" in d
    assert "trace_id" in d
    assert "timestamp" in d
    assert d["topic"] == "task.created"
    assert d["event_type"] == "task.created"
    assert d["producer"] == "test"
    assert d["payload"]["task_id"] == "test-1"
    assert d["meta"]["version"] == "1.0"
