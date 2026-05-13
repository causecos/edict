#!/usr/bin/env python3
"""JSON → Postgres 數據遷移腳本。

讀取舊版 data/tasks_source.json，導入到 Edict Postgres 數據庫。

用法:
  # 確保 Postgres 已運行且 schema 已創建（alembic upgrade head）
  python3 migrate_json_to_pg.py

  # 指定數據文件
  python3 migrate_json_to_pg.py --file /path/to/tasks_source.json

  # Dry run（只分析不寫入）
  python3 migrate_json_to_pg.py --dry-run
"""

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# 添加 backend 路徑
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import text
from app.db import engine, async_session, Base
from app.models.task import Task, TaskState

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("migrate")

# 舊版狀態 → Edict TaskState
STATE_MAP = {
    "Taizi": TaskState.Taizi,
    "Zhongshu": TaskState.Zhongshu,
    "Menxia": TaskState.Menxia,
    "Assigned": TaskState.Assigned,
    "Next": TaskState.Next,
    "Doing": TaskState.Doing,
    "Review": TaskState.Review,
    "Done": TaskState.Done,
    "Blocked": TaskState.Blocked,
    "Cancelled": TaskState.Cancelled,
    "Pending": TaskState.Pending,
    # Fallbacks
    "Inbox": TaskState.Taizi,
    "": TaskState.Taizi,
}


def parse_old_task(old: dict) -> dict:
    """將舊版 task JSON 轉換爲 Edict Task 參數。"""
    state_str = old.get("state", "Taizi")
    state = STATE_MAP.get(state_str, TaskState.Taizi)

    legacy_id = old.get("id", "")
    title = old.get("title", "未命名任務")

    # 解析時間
    updated_str = old.get("updatedAt", "")
    try:
        updated_at = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        updated_at = datetime.now(timezone.utc)

    return {
        "trace_id": str(uuid.uuid4()),
        "title": title,
        "description": old.get("now", ""),
        "priority": "中",
        "state": state,
        "assignee_org": old.get("org", None),
        "creator": old.get("official", "emperor"),
        "tags": [legacy_id] if legacy_id else [],
        "org": old.get("org", Task.org_for_state(state)),
        "official": old.get("official", ""),
        "now": old.get("now", ""),
        "eta": old.get("eta", "-"),
        "block": old.get("block", "無"),
        "output": old.get("output", ""),
        "archived": bool(old.get("archived", False)),
        "flow_log": old.get("flow_log", []),
        "progress_log": old.get("progress_log", []),
        "todos": old.get("todos", []),
        "scheduler": old.get("scheduler", {}),
        "template_id": old.get("templateId", ""),
        "template_params": old.get("templateParams", {}),
        "ac": old.get("ac", ""),
        "target_dept": old.get("targetDept", ""),
        "meta": {
            "legacy_id": legacy_id,
            "legacy_state": state_str,
            "legacy_output": old.get("output", ""),
            "legacy_ac": old.get("ac", ""),
            "legacy_eta": old.get("eta", ""),
            "legacy_block": old.get("block", ""),
        },
        "created_at": updated_at,  # 舊版沒有 created_at，用 updated_at 近似
        "updated_at": updated_at,
    }


async def migrate(file_path: Path, dry_run: bool = False):
    """執行遷移。"""
    if not file_path.exists():
        log.error(f"數據文件不存在: {file_path}")
        return

    # 讀取舊版數據
    raw = file_path.read_text(encoding="utf-8")
    old_tasks = json.loads(raw)
    log.info(f"讀取到 {len(old_tasks)} 個舊版任務")

    # 統計
    stats = {"total": len(old_tasks), "migrated": 0, "skipped": 0, "errors": 0}
    by_state = {}

    for old in old_tasks:
        state_str = old.get("state", "?")
        by_state[state_str] = by_state.get(state_str, 0) + 1

    log.info(f"狀態分布: {by_state}")

    if dry_run:
        log.info("=== DRY RUN 模式，不寫入數據庫 ===")
        for old in old_tasks:
            params = parse_old_task(old)
            log.info(f"  [{params['meta']['legacy_id']}] {params['title'][:40]} → {params['state'].value}")
        log.info(f"Dry run 完成: {stats['total']} 個任務待遷移")
        return

    # 寫入 Postgres
    async with async_session() as db:
        for old in old_tasks:
            try:
                params = parse_old_task(old)
                legacy_id = params["meta"]["legacy_id"]

                # 檢查是否已遷移
                from sqlalchemy import select
                existing = await db.execute(
                    select(Task).where(Task.tags.contains([legacy_id]))
                )
                if existing.scalars().first():
                    log.debug(f"跳過已存在: {legacy_id}")
                    stats["skipped"] += 1
                    continue

                task = Task(**params)
                db.add(task)
                stats["migrated"] += 1
                log.info(f"✅ 遷移: [{legacy_id}] {params['title'][:40]} → {params['state'].value}")

            except Exception as e:
                log.error(f"❌ 遷移失敗: {old.get('id', '?')}: {e}")
                stats["errors"] += 1

        await db.commit()

    log.info(f"遷移完成: 總計 {stats['total']}, 成功 {stats['migrated']}, "
             f"跳過 {stats['skipped']}, 錯誤 {stats['errors']}")


def main():
    parser = argparse.ArgumentParser(description="Migrate JSON tasks to Postgres")
    parser.add_argument(
        "--file", "-f",
        default=str(Path(__file__).parent.parent.parent / "data" / "tasks_source.json"),
        help="Path to tasks_source.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only analyze, don't write")
    args = parser.parse_args()

    asyncio.run(migrate(Path(args.file), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
