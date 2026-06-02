"""
event_bus.py 單元測試 — Redis Streams 事件匯流排。

測試範圍：
- EventBus 初始化與連接管理
- publish: 發布事件到 Redis Stream + Pub/Sub
- consume: 消費者組消費事件
- ack: 確認消費
- ensure_consumer_group: 冪等建立消費者組
- _stream_key: stream key 前綴生成
- 錯誤處理：未連接時存取 .redis 拋出 AssertionError

隔離策略：
- 使用 unittest.mock.AsyncMock 完全模擬 redis.asyncio.Redis
- 不依賴 Redis 伺服器
- 每個測試獨立建立 EventBus 與 mock Redis
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────
# Helpers — 建立 mock EventBus
# ─────────────────────────────────────────────


def make_mock_redis() -> AsyncMock:
    """建立完全模擬的 aioredis.Redis 實例。"""
    mock = AsyncMock()
    mock.xadd = AsyncMock(return_value="1680000000000-0")
    mock.xreadgroup = AsyncMock(return_value=[])
    mock.xack = AsyncMock(return_value=1)
    mock.xgroup_create = AsyncMock(return_value=True)
    mock.publish = AsyncMock(return_value=1)
    mock.aclose = AsyncMock()
    mock.xpending_range = AsyncMock(return_value=[])
    mock.xautoclaim = AsyncMock(return_value=None)
    mock.xinfo_stream = AsyncMock(return_value={"length": 0})
    return mock


def make_connected_event_bus(mock_redis=None) -> "EventBus":
    """建立已連接的 EventBus 實例（直接注入 _redis）。"""
    from edict.backend.app.services.event_bus import EventBus

    bus = EventBus(redis_url="redis://mock:6379/0")
    bus._redis = mock_redis or make_mock_redis()
    return bus


# ─────────────────────────────────────────────
# 初始化與連接
# ─────────────────────────────────────────────


class TestEventBusInit:
    """EventBus 初始化與連接管理單元測試。"""

    def test_init_with_default_redis_url(self):
        """
        given: 未指定 redis_url，Settings.redis_url 有預設值
        when: 建立 EventBus()
        then: _redis_url 被設定
        """
        with patch("edict.backend.app.services.event_bus.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = "redis://default:6379/0"
            from edict.backend.app.services.event_bus import EventBus
            bus = EventBus()
            assert bus._redis_url == "redis://default:6379/0"

    def test_init_with_custom_redis_url(self):
        """
        given: 明確指定 redis_url
        when: 建立 EventBus(redis_url="redis://custom:6380/1")
        then: _redis_url 為自訂值
        """
        from edict.backend.app.services.event_bus import EventBus
        bus = EventBus(redis_url="redis://custom:6380/1")
        assert bus._redis_url == "redis://custom:6380/1"

    def test_not_connected_raises_assertion_error(self):
        """
        given: EventBus 尚未 connect()
        when: 存取 .redis property
        then: 拋出 AssertionError
        """
        from edict.backend.app.services.event_bus import EventBus
        bus = EventBus(redis_url="redis://localhost:6379/0")

        with pytest.raises(AssertionError, match="not connected"):
            _ = bus.redis

    @pytest.mark.asyncio
    async def test_connect_creates_redis_client(self):
        """
        given: EventBus 尚未連接
        when: 呼叫 connect()
        then: _redis 被設置為 aioredis.Redis 實例
        """
        with patch("edict.backend.app.services.event_bus.aioredis") as mock_aioredis:
            mock_client = make_mock_redis()
            mock_aioredis.from_url.return_value = mock_client

            from edict.backend.app.services.event_bus import EventBus
            bus = EventBus(redis_url="redis://test:6379/0")
            await bus.connect()

            assert bus._redis is mock_client
            mock_aioredis.from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_closes_redis(self):
        """
        given: EventBus 已連接
        when: 呼叫 close()
        then: _redis.aclose() 被呼叫，_redis 設為 None
        """
        mock_redis = make_mock_redis()
        bus = make_connected_event_bus(mock_redis)

        await bus.close()

        mock_redis.aclose.assert_awaited_once()
        assert bus._redis is None


# ─────────────────────────────────────────────
# _stream_key
# ─────────────────────────────────────────────


class TestStreamKey:
    """_stream_key 方法單元測試。"""

    def test_stream_key_prefix(self):
        """
        given: topic = "task.created"
        when: 呼叫 _stream_key("task.created")
        then: 回傳 "edict:stream:task.created"
        """
        bus = make_connected_event_bus()
        key = bus._stream_key("task.created")
        assert key == "edict:stream:task.created"

    def test_stream_key_custom_topic(self):
        """
        given: topic = "agent.heartbeat"
        when: 呼叫 _stream_key
        then: 正確拼接前綴
        """
        bus = make_connected_event_bus()
        key = bus._stream_key("agent.heartbeat")
        assert key == "edict:stream:agent.heartbeat"


# ─────────────────────────────────────────────
# publish
# ─────────────────────────────────────────────


class TestPublish:
    """publish 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_publish_returns_event_id(self):
        """
        given: 已連接的 EventBus，mock xadd 回傳 "1680000000000-0"
        when: 呼叫 publish
        then: 回傳 Redis entry ID
        """
        mock_redis = make_mock_redis()
        mock_redis.xadd.return_value = "1680000000001-0"
        bus = make_connected_event_bus(mock_redis)

        event_id = await bus.publish(
            topic="task.created",
            trace_id=str(uuid.uuid4()),
            event_type="task.created",
            producer="test",
            payload={"key": "value"},
            meta={"version": 1},
        )

        assert event_id == "1680000000001-0"

    @pytest.mark.asyncio
    async def test_publish_calls_xadd_with_correct_stream_key(self):
        """
        given: 已連接的 EventBus
        when: 呼叫 publish(topic="task.created", ...)
        then: xadd 以 "edict:stream:task.created" stream key 呼叫，maxlen=10000
        """
        mock_redis = make_mock_redis()
        bus = make_connected_event_bus(mock_redis)

        await bus.publish(
            topic="task.created",
            trace_id="trace-123",
            event_type="task.created",
            producer="test",
            payload={"action": "create"},
        )

        call_args = mock_redis.xadd.call_args
        # 第一個位置參數是 stream key
        assert call_args[0][0] == "edict:stream:task.created"
        # maxlen 參數
        assert call_args[1]["maxlen"] == 10000

    @pytest.mark.asyncio
    async def test_publish_includes_timestamp_and_uuid(self):
        """
        given: 已連接的 EventBus
        when: 呼叫 publish
        then: xadd 的 event dict 包含 event_id (UUID)、timestamp (ISO)、topic、event_type、producer
        """
        mock_redis = make_mock_redis()
        bus = make_connected_event_bus(mock_redis)

        await bus.publish(
            topic="task.status",
            trace_id="trace-456",
            event_type="state.changed",
            producer="agent-1",
        )

        # 取得 xadd 的第二個參數 (event dict)
        event_dict = mock_redis.xadd.call_args[0][1]

        assert "event_id" in event_dict
        assert "timestamp" in event_dict
        assert event_dict["topic"] == "task.status"
        assert event_dict["event_type"] == "state.changed"
        assert event_dict["producer"] == "agent-1"
        assert event_dict["trace_id"] == "trace-456"
        # 驗證 event_id 是有效 UUID
        uuid.UUID(event_dict["event_id"])

    @pytest.mark.asyncio
    async def test_publish_also_publishes_to_pubsub(self):
        """
        given: 已連接的 EventBus
        when: 呼叫 publish
        then: redis.publish 也被呼叫，頻道為 "edict:pubsub:{topic}"
        """
        mock_redis = make_mock_redis()
        bus = make_connected_event_bus(mock_redis)

        await bus.publish(
            topic="task.created",
            trace_id="trace-789",
            event_type="task.created",
            producer="test",
        )

        mock_redis.publish.assert_awaited_once()
        pubsub_channel = mock_redis.publish.call_args[0][0]
        assert pubsub_channel == "edict:pubsub:task.created"

    @pytest.mark.asyncio
    async def test_publish_with_empty_payload_and_meta(self):
        """
        given: 未提供 payload 和 meta
        when: 呼叫 publish
        then: payload 與 meta 序列化為 "{}"
        """
        mock_redis = make_mock_redis()
        bus = make_connected_event_bus(mock_redis)

        await bus.publish(
            topic="task.status",
            trace_id="trace-000",
            event_type="test",
            producer="test",
        )

        event_dict = mock_redis.xadd.call_args[0][1]
        import json
        assert json.loads(event_dict["payload"]) == {}
        assert json.loads(event_dict["meta"]) == {}


# ─────────────────────────────────────────────
# ensure_consumer_group
# ─────────────────────────────────────────────


class TestEnsureConsumerGroup:
    """ensure_consumer_group 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_creates_consumer_group(self):
        """
        given: 消費者組尚不存在
        when: 呼叫 ensure_consumer_group
        then: xgroup_create 以 mkstream=True 呼叫
        """
        mock_redis = make_mock_redis()
        bus = make_connected_event_bus(mock_redis)

        await bus.ensure_consumer_group("task.created", "dispatch-workers")

        mock_redis.xgroup_create.assert_awaited_once()
        call_args = mock_redis.xgroup_create.call_args
        assert call_args[0][0] == "edict:stream:task.created"
        assert call_args[0][1] == "dispatch-workers"
        assert call_args[1]["mkstream"] is True

    @pytest.mark.asyncio
    async def test_ignores_busygroup_error(self):
        """
        given: 消費者組已存在（xgroup_create 拋出 BUSYGROUP ResponseError）
        when: 呼叫 ensure_consumer_group
        then: 不拋出例外，冪等成功
        """
        import redis.asyncio as aioredis

        mock_redis = make_mock_redis()
        mock_redis.xgroup_create = AsyncMock(
            side_effect=aioredis.ResponseError("BUSYGROUP Consumer Group name already exists")
        )
        bus = make_connected_event_bus(mock_redis)

        # 不應拋出例外
        await bus.ensure_consumer_group("task.created", "dispatch-workers")

    @pytest.mark.asyncio
    async def test_raises_other_errors(self):
        """
        given: xgroup_create 拋出非 BUSYGROUP 的 ResponseError
        when: 呼叫 ensure_consumer_group
        then: 重新拋出該錯誤
        """
        import redis.asyncio as aioredis

        mock_redis = make_mock_redis()
        mock_redis.xgroup_create = AsyncMock(
            side_effect=aioredis.ResponseError("Some other error")
        )
        bus = make_connected_event_bus(mock_redis)

        with pytest.raises(aioredis.ResponseError, match="Some other error"):
            await bus.ensure_consumer_group("task.created", "dispatch-workers")


# ─────────────────────────────────────────────
# consume
# ─────────────────────────────────────────────


class TestConsume:
    """consume 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_consume_returns_empty_list_when_no_events(self):
        """
        given: Stream 中沒有新事件
        when: 呼叫 consume
        then: 回傳空 list
        """
        mock_redis = make_mock_redis()
        mock_redis.xreadgroup.return_value = []
        bus = make_connected_event_bus(mock_redis)

        events = await bus.consume(
            topic="task.created",
            group="dispatch-workers",
            consumer="worker-1",
        )

        assert events == []

    @pytest.mark.asyncio
    async def test_consume_returns_events_with_deserialized_payload(self):
        """
        given: Stream 中有事件，payload/meta 為 JSON 字串
        when: 呼叫 consume
        then: 回傳 (entry_id, event_dict) list，且 payload/meta 已反序列化為 dict
        """
        import json

        mock_redis = make_mock_redis()
        raw_event = {
            "event_id": str(uuid.uuid4()),
            "trace_id": "trace-123",
            "timestamp": "2025-01-01T00:00:00Z",
            "topic": "task.created",
            "event_type": "task.created",
            "producer": "test",
            "payload": json.dumps({"action": "create"}),
            "meta": json.dumps({"version": 1}),
        }
        # xreadgroup returns [[stream_key, [(entry_id, data)]]]
        mock_redis.xreadgroup.return_value = [
            ["edict:stream:task.created", [("1680000000000-0", raw_event)]]
        ]
        bus = make_connected_event_bus(mock_redis)

        events = await bus.consume(
            topic="task.created",
            group="dispatch-workers",
            consumer="worker-1",
        )

        assert len(events) == 1
        entry_id, data = events[0]
        assert entry_id == "1680000000000-0"
        assert data["payload"] == {"action": "create"}
        assert data["meta"] == {"version": 1}

    @pytest.mark.asyncio
    async def test_consume_respects_count_and_block(self):
        """
        given: 已連接的 EventBus
        when: 呼叫 consume 指定 count=5, block_ms=2000
        then: xreadgroup 以對應參數呼叫
        """
        mock_redis = make_mock_redis()
        bus = make_connected_event_bus(mock_redis)

        await bus.consume(
            topic="task.status",
            group="workers",
            consumer="w1",
            count=5,
            block_ms=2000,
        )

        call_kwargs = mock_redis.xreadgroup.call_args[1]
        assert call_kwargs["count"] == 5
        assert call_kwargs["block"] == 2000


# ─────────────────────────────────────────────
# ack
# ─────────────────────────────────────────────


class TestAck:
    """ack 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_ack_calls_xack(self):
        """
        given: 已消費的事件 entry_id
        when: 呼叫 ack
        then: redis.xack 以正確的 stream key、group、entry_id 呼叫
        """
        mock_redis = make_mock_redis()
        bus = make_connected_event_bus(mock_redis)

        await bus.ack(
            topic="task.created",
            group="dispatch-workers",
            entry_id="1680000000000-0",
        )

        mock_redis.xack.assert_awaited_once_with(
            "edict:stream:task.created",
            "dispatch-workers",
            "1680000000000-0",
        )


# ─────────────────────────────────────────────
# get_pending
# ─────────────────────────────────────────────


class TestGetPending:
    """get_pending 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_get_pending_returns_pending_list(self):
        """
        given: Stream 有 pending 事件
        when: 呼叫 get_pending
        then: 回傳 pending 事件列表
        """
        mock_redis = make_mock_redis()
        mock_redis.xpending_range.return_value = [
            {"message_id": "1680000000000-0", "consumer": "w1", "times_delivered": 1}
        ]
        bus = make_connected_event_bus(mock_redis)

        pending = await bus.get_pending("task.created", "dispatch-workers", count=5)

        mock_redis.xpending_range.assert_awaited_once()
        assert len(pending) == 1
        assert pending[0]["message_id"] == "1680000000000-0"


# ─────────────────────────────────────────────
# consume_multi
# ─────────────────────────────────────────────


class TestConsumeMulti:
    """consume_multi 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_consume_multi_returns_topic_entry_data(self):
        """
        given: 多個 topic 的 Stream 中有事件
        when: 呼叫 consume_multi
        then: 回傳 (topic, entry_id, event_dict) 三元組列表
        """
        import json

        mock_redis = make_mock_redis()
        raw_event = {
            "event_id": str(uuid.uuid4()),
            "trace_id": "trace-999",
            "timestamp": "2025-06-01T00:00:00Z",
            "topic": "task.created",
            "event_type": "task.created",
            "producer": "test",
            "payload": json.dumps({"x": 1}),
            "meta": json.dumps({}),
        }
        mock_redis.xreadgroup.return_value = [
            ["edict:stream:task.created", [("1680000000000-0", raw_event)]]
        ]
        bus = make_connected_event_bus(mock_redis)

        events = await bus.consume_multi(
            topics=["task.created", "task.status"],
            group="workers",
            consumer="w1",
        )

        assert len(events) == 1
        topic, entry_id, data = events[0]
        assert topic == "task.created"
        assert entry_id == "1680000000000-0"
        assert data["payload"] == {"x": 1}


# ─────────────────────────────────────────────
# stream_info
# ─────────────────────────────────────────────


class TestStreamInfo:
    """stream_info 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_stream_info_returns_info_dict(self):
        """
        given: Stream 存在
        when: 呼叫 stream_info
        then: 回傳 stream 資訊 dict
        """
        mock_redis = make_mock_redis()
        mock_redis.xinfo_stream.return_value = {"length": 42, "groups": 2}
        bus = make_connected_event_bus(mock_redis)

        info = await bus.stream_info("task.created")

        assert info == {"length": 42, "groups": 2}

    @pytest.mark.asyncio
    async def test_stream_info_returns_empty_on_error(self):
        """
        given: xinfo_stream 拋出 ResponseError（stream 不存在）
        when: 呼叫 stream_info
        then: 回傳空 dict，不拋出例外
        """
        import redis.asyncio as aioredis

        mock_redis = make_mock_redis()
        mock_redis.xinfo_stream = AsyncMock(
            side_effect=aioredis.ResponseError("no such key")
        )
        bus = make_connected_event_bus(mock_redis)

        info = await bus.stream_info("nonexistent")

        assert info == {}


# ─────────────────────────────────────────────
# claim_stale
# ─────────────────────────────────────────────


class TestClaimStale:
    """claim_stale 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_claim_stale_returns_claimed_events(self):
        """
        given: 有超時的 pending 事件
        when: 呼叫 claim_stale
        then: 回傳已認領的事件列表
        """
        import json

        mock_redis = make_mock_redis()
        raw_event = {
            "event_id": str(uuid.uuid4()),
            "trace_id": "trace-claim",
            "timestamp": "2025-06-01T00:00:00Z",
            "topic": "task.status",
            "event_type": "state.changed",
            "producer": "test",
            "payload": json.dumps({"old": "Taizi"}),
            "meta": json.dumps({}),
        }
        # xautoclaim returns (next_id, [(id, data), ...], [deleted_ids])
        mock_redis.xautoclaim.return_value = ("0-0", [("1680000000000-0", raw_event)], [])
        bus = make_connected_event_bus(mock_redis)

        events = await bus.claim_stale(
            topic="task.status",
            group="workers",
            consumer="recovery-worker",
            min_idle_ms=30000,
            count=5,
        )

        assert len(events) == 1
        entry_id, data = events[0]
        assert entry_id == "1680000000000-0"
        assert data["payload"] == {"old": "Taizi"}

    @pytest.mark.asyncio
    async def test_claim_stale_no_events_returns_empty(self):
        """
        given: 沒有超時的 pending 事件
        when: 呼叫 claim_stale
        then: 回傳空列表
        """
        mock_redis = make_mock_redis()
        # xautoclaim with no results: next_id is "0-0" but no events
        mock_redis.xautoclaim.return_value = ("0-0", [], [])
        bus = make_connected_event_bus(mock_redis)

        events = await bus.claim_stale("task.status", "workers", "w1")

        assert events == []


# ─────────────────────────────────────────────
# get_delivery_count
# ─────────────────────────────────────────────


class TestGetDeliveryCount:
    """get_delivery_count 方法單元測試。"""

    @pytest.mark.asyncio
    async def test_get_delivery_count_returns_count(self):
        """
        given: 事件已投遞 3 次
        when: 呼叫 get_delivery_count
        then: 回傳 3
        """
        mock_redis = make_mock_redis()
        mock_redis.xpending_range.return_value = [
            {"times_delivered": 3}
        ]
        bus = make_connected_event_bus(mock_redis)

        count = await bus.get_delivery_count(
            topic="task.created",
            group="workers",
            entry_id="1680000000000-0",
        )

        assert count == 3

    @pytest.mark.asyncio
    async def test_get_delivery_count_returns_zero_when_not_pending(self):
        """
        given: 事件不在 pending 列表中（已 ACK）
        when: 呼叫 get_delivery_count
        then: 回傳 0
        """
        mock_redis = make_mock_redis()
        mock_redis.xpending_range.return_value = []
        bus = make_connected_event_bus(mock_redis)

        count = await bus.get_delivery_count(
            topic="task.created",
            group="workers",
            entry_id="1680000000000-0",
        )

        assert count == 0
