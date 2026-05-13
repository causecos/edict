"""Outbox Relay Worker — 輪詢 outbox_events 表，投遞未發布事件到 Redis Streams。

Transactional Outbox Pattern 的投遞端：
- 事務層把事件寫入 outbox 表（與業務數據同一事務）
- 本 worker 輪詢 unpublished 事件，調用 EventBus.publish 投遞到 Redis
- 投遞成功標記 published=True；失敗累計 attempts，達到上限進入 DLQ
- 消費者必須用 event_id 做冪等，防止 relay 重啓造成重複投遞
"""

import asyncio
import logging
import signal
from datetime import datetime, timezone

from sqlalchemy import select, update

from ..db import async_session
from ..models.outbox import OutboxEvent
from ..services.event_bus import EventBus

log = logging.getLogger("edict.outbox_relay")

MAX_ATTEMPTS = 5
BATCH_SIZE = 50
POLL_INTERVAL = 1.0  # 秒


class OutboxRelay:
    """輪詢 outbox_events 表，投遞到 Redis Streams。"""

    def __init__(self):
        self.bus = EventBus()
        self._running = False

    async def start(self):
        await self.bus.connect()
        self._running = True
        log.info("🚀 Outbox Relay started")

        while self._running:
            try:
                relayed = await self._relay_cycle()
                if relayed == 0:
                    await asyncio.sleep(POLL_INTERVAL)
            except Exception as e:
                log.error(f"Outbox relay error: {e}", exc_info=True)
                await asyncio.sleep(POLL_INTERVAL * 2)

    async def stop(self):
        self._running = False
        await self.bus.close()
        log.info("Outbox Relay stopped")

    async def _relay_cycle(self) -> int:
        """處理一批未投遞事件。返回本輪處理數量。"""
        async with async_session() as db:
            # FOR UPDATE SKIP LOCKED 允許多 relay 實例並行
            stmt = (
                select(OutboxEvent)
                .where(OutboxEvent.published == False)  # noqa: E712
                .order_by(OutboxEvent.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            result = await db.execute(stmt)
            events = list(result.scalars().all())

            if not events:
                return 0

            for event in events:
                try:
                    await self.bus.publish(
                        topic=event.topic,
                        trace_id=event.trace_id,
                        event_type=event.event_type,
                        producer=event.producer,
                        payload=event.payload or {},
                        meta=event.meta or {},
                    )
                    event.published = True
                    event.published_at = datetime.now(timezone.utc)
                    log.debug(f"📤 Relayed outbox #{event.id} → {event.topic}")

                except Exception as exc:
                    event.attempts += 1
                    event.last_error = str(exc)[:500]
                    log.warning(
                        f"Outbox #{event.id} relay failed (attempt {event.attempts}): {exc}"
                    )

                    if event.attempts >= MAX_ATTEMPTS:
                        # 投遞到 DLQ
                        try:
                            await self.bus.publish(
                                topic="dead_letter",
                                trace_id=event.trace_id,
                                event_type="outbox.dead_letter",
                                producer="outbox_relay",
                                payload={
                                    "outbox_id": event.id,
                                    "event_id": event.event_id,
                                    "topic": event.topic,
                                    "event_type": event.event_type,
                                    "payload": event.payload,
                                    "error": event.last_error,
                                    "attempts": event.attempts,
                                },
                            )
                        except Exception as dlq_err:
                            log.error(f"Failed to publish DLQ for outbox #{event.id}: {dlq_err}")

            await db.commit()
            return len(events)


async def run_outbox_relay():
    """入口函數 — 用於直接運行 worker。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    relay = OutboxRelay()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(relay.stop()))

    await relay.start()


if __name__ == "__main__":
    asyncio.run(run_outbox_relay())
