"""Redis Streams 事件總線 — 可靠的事件發布/消費。

核心能力：
- publish: XADD 發布事件到 stream
- subscribe: XREADGROUP 消費者組消費，帶 ACK 保證from __future__ import annotations- 未 ACK 的事件在消費者崩潰後會被自動重新投遞
- 解決舊架構 daemon 線程丟失導致派發永久中斷的根因
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from ..config import get_settings

log = logging.getLogger("edict.event_bus")

# ── 標準 Topic 常量 ──
TOPIC_TASK_CREATED = "task.created"
TOPIC_TASK_DISPATCH = "task.dispatch"
TOPIC_TASK_DISPATCH_STARTED = "task.dispatch.started"
TOPIC_TASK_DISPATCH_FAILED = "task.dispatch.failed"
TOPIC_TASK_DISPATCH_ALERT = "task.dispatch.alert"
TOPIC_TASK_AUDIT = "task.audit"
TOPIC_TASK_STATUS = "task.status"
TOPIC_TASK_COMPLETED = "task.completed"
TOPIC_TASK_STALLED = "task.stalled"
TOPIC_TASK_ESCALATED = "task.escalated"

TOPIC_AGENT_THOUGHTS = "agent.thoughts"
TOPIC_AGENT_HEARTBEAT = "agent.heartbeat"

# 所有 topic 對應的 Redis Stream key 前綴
STREAM_PREFIX = "edict:stream:"


class EventBus:
    """Redis Streams 事件總線。"""

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url or get_settings().redis_url
        self._redis: aioredis.Redis | None = None

    async def connect(self):
        """建立 Redis 連接。"""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                max_connections=20,
            )
            log.info(f"EventBus connected to Redis: {self._redis_url}")

    async def close(self):
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    @property
    def redis(self) -> aioredis.Redis:
        assert self._redis is not None, "EventBus not connected. Call connect() first."
        return self._redis

    def _stream_key(self, topic: str) -> str:
        return f"{STREAM_PREFIX}{topic}"

    async def publish(
        self,
        topic: str,
        trace_id: str,
        event_type: str,
        producer: str,
        payload: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """發布事件到 Redis Stream。

        流程：
        1. 組裝事件 JSON（含 event_id / trace_id / timestamp / topic / event_type / producer）
        2. XADD 寫入 Redis Stream（maxlen=10000 限制 stream 長度）
        3. PUBLISH 到 Pub/Sub 頻道（供 WebSocket 實時推送）

        Returns:
            entry_id (str): 由 Redis 自動生成的 Stream entry ID（格式: timestamp-sequence）
        """
        event = {
            "event_id": str(uuid.uuid4()),
            "trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "topic": topic,
            "event_type": event_type,
            "producer": producer,
            "payload": json.dumps(payload or {}, ensure_ascii=False),
            "meta": json.dumps(meta or {}, ensure_ascii=False),
        }
        stream_key = self._stream_key(topic)
        entry_id = await self.redis.xadd(stream_key, event, maxlen=10000)
        log.debug(f"📤 Published {topic}/{event_type} → {stream_key} [{entry_id}] trace={trace_id}")

        # 同時發布到 Pub/Sub 頻道（供 WebSocket 實時推送）
        await self.redis.publish(f"edict:pubsub:{topic}", json.dumps(event, ensure_ascii=False))

        return entry_id

    async def ensure_consumer_group(self, topic: str, group: str):
        """確保消費者組存在（冪等）。

        XGROUP CREATE 若 group 已存在會回傳 BUSYGROUP error，
        捕獲後略過（不拋出異常），保證多次呼叫安全。
        """
        stream_key = self._stream_key(topic)
        try:
            await self.redis.xgroup_create(stream_key, group, id="0", mkstream=True)
            log.info(f"Created consumer group {group} on {stream_key}")
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def consume(
        self,
        topic: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict]]:
        """從消費者組消費事件（XREADGROUP）。

        - 只讀取新增事件（stream key ">" 表示未投遞給此 group 的消息）
        - block_ms: 若無新事件，block 指定毫秒後回傳空列表
        - 回傳前自動反序列化 payload/meta JSON 欄位

        Returns:
            list of (entry_id, event_dict)
        """
        stream_key = self._stream_key(topic)
        results = await self.redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream_key: ">"},
            count=count,
            block=block_ms,
        )
        events = []
        if results:
            for _stream, messages in results:
                for entry_id, data in messages:
                    # 反序列化 JSON 字段 — Redis Stream 只存字串
                    if "payload" in data:
                        data["payload"] = json.loads(data["payload"])
                    if "meta" in data:
                        data["meta"] = json.loads(data["meta"])
                    events.append((entry_id, data))
        return events

    async def ack(self, topic: str, group: str, entry_id: str):
        """確認消費 — XACK 後事件不會被重新投遞。

        必須在業務邏輯成功處理後呼叫，否則事件會停留在 pending 列表，
        被 claim_stale 重新分配給其他 consumer。
        """
        stream_key = self._stream_key(topic)
        await self.redis.xack(stream_key, group, entry_id)
        log.debug(f"✅ ACK {stream_key} [{entry_id}] group={group}")

    async def claim_stale(
        self,
        topic: str,
        group: str,
        consumer: str,
        min_idle_ms: int = 60000,
        count: int = 10,
    ) -> list[tuple[str, dict]]:
        """認領超時的 pending 事件（XAUTOCLAIM）— 消費者崩潰恢復。

        當 consumer 崩潰後，其 pending 事件在超過 min_idle_ms 後，
        可被其他 consumer 透過 XAUTOCLAIM 接管，防止事件永久遺失。
        """
        stream_key = self._stream_key(topic)
        results = await self.redis.xautoclaim(
            stream_key, group, consumer, min_idle_time=min_idle_ms, start_id="0-0", count=count
        )
        # xautoclaim returns (next_id, [(id, data), ...], [deleted_ids])
        if results and len(results) >= 2:
            events = []
            for entry_id, data in results[1]:
                if "payload" in data:
                    data["payload"] = json.loads(data["payload"])
                if "meta" in data:
                    data["meta"] = json.loads(data["meta"])
                events.append((entry_id, data))
            return events
        return []

    async def stream_info(self, topic: str) -> dict:
        """獲取 Stream 信息（長度、消費者組等）。"""
        stream_key = self._stream_key(topic)
        try:
            info = await self.redis.xinfo_stream(stream_key)
            return info
        except aioredis.ResponseError:
            return {}

    async def consume_multi(
        self,
        topics: list[str],
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 2000,
    ) -> list[tuple[str, str, dict]]:
        """從多個 topic 同時消費事件（單次 XREADGROUP 多 stream）。

        Returns:
            list of (topic, entry_id, event_dict)
        """
        streams = {self._stream_key(t): ">" for t in topics}
        results = await self.redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams=streams,
            count=count,
            block=block_ms,
        )
        events = []
        if results:
            # 建立反向映射: stream_key → topic
            key_to_topic = {self._stream_key(t): t for t in topics}
            for stream_key, messages in results:
                topic = key_to_topic.get(stream_key, stream_key)
                for entry_id, data in messages:
                    if "payload" in data:
                        data["payload"] = json.loads(data["payload"])
                    if "meta" in data:
                        data["meta"] = json.loads(data["meta"])
                    events.append((topic, entry_id, data))
        return events

    async def get_pending(
        self,
        topic: str,
        group: str,
        count: int = 20,
    ) -> list[dict]:
        """列出 pending 列表中的事件（診斷用）。

        透過 XPENDING RANGE 查詢，回傳未 ACK 的消息列表。
        """
        stream_key = self._stream_key(topic)
        try:
            results = await self.redis.xpending_range(
                stream_key, group, min="-", max="+", count=count
            )
            return list(results) if results else []
        except aioredis.ResponseError:
            # group 可能尚未建立
            return []

    async def get_delivery_count(self, topic: str, group: str, entry_id: str) -> int:
        """獲取某條消息的累計投遞次數。"""
        stream_key = self._stream_key(topic)
        # XPENDING <stream> <group> <start> <end> <count> 返回每條消息的詳情
        pending = await self.redis.xpending_range(
            stream_key, group, min=entry_id, max=entry_id, count=1
        )
        if pending:
            # 每條 pending 條目格式: {message_id, consumer, idle_time, delivery_count}
            return pending[0].get("times_delivered", 0)
        return 0


# ── 全局單例 ──
_bus: EventBus | None = None


async def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
        await _bus.connect()
    return _bus
