#!/usr/bin/env python3
"""Telegram-friendly task CLI.

A thin wrapper around:
- scripts/kanban_update.py (看板任務)
- openclaw tasks flow ... (TaskFlow 查詢/取消)

Examples:
  python3 scripts/tg_cli.py tasks list --active --full
  python3 scripts/tg_cli.py tasks create JJC-20260514-001 "整理 Telegram 任務指令" \
      --state Zhongshu --org 中書省 --official 中書令 --source telegram:493683906
  python3 scripts/tg_cli.py flow list --status running --limit 5
  python3 scripts/tg_cli.py flow show <flow_id>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kanban_update as ku  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg",
        description="Telegram-friendly CLI for task board and TaskFlow operations.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_tasks = sub.add_parser("kanban", aliases=["tasks"], help="看板任務指令")
    sub2 = p_tasks.add_subparsers(dest="action", required=True)

    p_list = sub2.add_parser("read", aliases=["list"], help="Read/list tasks")
    p_list.add_argument("--state", default="")
    p_list.add_argument("--active", action="store_true")
    p_list.add_argument("--show-id", action="store_true")
    p_list.add_argument("--limit", type=int, default=0)
    p_list.add_argument("--brief", action="store_true")
    p_list.add_argument("--full", action="store_true")
    p_list.add_argument("--include-session", action="store_true")

    p_create = sub2.add_parser("create", help="Create a task")
    p_create.add_argument("task_id")
    p_create.add_argument("title")
    p_create.add_argument("--state", default="Zhongshu")
    p_create.add_argument("--org", default="中書省")
    p_create.add_argument("--official", default="中書令")
    p_create.add_argument("--remark", default=None)
    p_create.add_argument("--source", default=None)

    p_state = sub2.add_parser("update-state", aliases=["state"], help="Update task state")
    p_state.add_argument("task_id")
    p_state.add_argument("state")
    p_state.add_argument("note", nargs="?", default="")

    p_flow = sub2.add_parser("update-flow", aliases=["flow"], help="Record task flow")
    p_flow.add_argument("task_id")
    p_flow.add_argument("from_dept")
    p_flow.add_argument("to_dept")
    p_flow.add_argument("remark")

    p_progress = sub2.add_parser("update-progress", aliases=["progress"], help="Report task progress")
    p_progress.add_argument("task_id")
    p_progress.add_argument("now")
    p_progress.add_argument("--todos", default="")
    p_progress.add_argument("--tokens", type=int, default=0)
    p_progress.add_argument("--cost", type=float, default=0.0)
    p_progress.add_argument("--elapsed", type=int, default=0)

    p_done = sub2.add_parser("update-done", aliases=["done", "close"], help="Mark task done")
    p_done.add_argument("task_id")
    p_done.add_argument("--output", default="")
    p_done.add_argument("--summary", default="")

    p_delete = sub2.add_parser("delete", aliases=["cancel"], help="Cancel a task (state -> Cancelled)")
    p_delete.add_argument("task_id")
    p_delete.add_argument("note", nargs="?", default="由 TG CLI 取消")

    # 注意：taskflow 是本工具別名（文字意圖轉譯），實際來源是 openclaw tasks flow
    p_tf = sub.add_parser("flow", aliases=["taskflow", "tf"], help="TaskFlow 指令（實際走 openclaw tasks flow ...）")
    tf_sub = p_tf.add_subparsers(dest="flow_action", required=True)

    tf_list = tf_sub.add_parser("read", aliases=["list"], help="Read/list TaskFlow records")
    tf_list.add_argument("--status", default="")
    tf_list.add_argument("--limit", type=int, default=10)
    tf_list.add_argument("--json", action="store_true")

    tf_show = tf_sub.add_parser("read-one", aliases=["show", "get"], help="Show one TaskFlow")
    tf_show.add_argument("lookup")
    tf_show.add_argument("--json", action="store_true")

    tf_cancel = tf_sub.add_parser("delete", aliases=["cancel"], help="Cancel one TaskFlow")
    tf_cancel.add_argument("lookup")

    return parser


def _run_openclaw(args: list[str]) -> str:
    proc = subprocess.run(["openclaw", *args], capture_output=True, text=True)
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    if proc.returncode != 0:
        msg = err or out or f"openclaw exited {proc.returncode}"
        raise RuntimeError(msg)
    # openclaw CLI 某些子命令會把 JSON 寫到 stderr
    return out or err


def _ts(ms: Any) -> str:
    if not isinstance(ms, (int, float)) or ms <= 0:
        return "-"
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


def _short(s: Any, n: int = 64) -> str:
    text = str(s or "").replace("\n", " ").strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _extract_task_id(text: Any) -> str:
    m = re.search(r"\b(JJC-[0-9]{8}-[0-9]{3}|JJC-TEST-[A-Z0-9-]+)\b", str(text or ""), re.I)
    return m.group(1) if m else ""


def _agent_from_owner_key(owner_key: Any) -> str:
    m = re.search(r"agent:([^:]+):", str(owner_key or ""))
    return m.group(1) if m else "-"


def _age(ms: Any) -> str:
    if not isinstance(ms, (int, float)) or ms <= 0:
        return "-"
    delta = int(dt.datetime.now().timestamp() - (ms / 1000))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def _task_preview(text: Any, max_lines: int = 4, max_cols: int = 80) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    lines = []
    for line in raw.splitlines():
        t = line.strip()
        if not t:
            continue
        if len(t) <= max_cols:
            lines.append(t)
        else:
            chunks = re.split(r"(?<=[。；;.!?！？])\s+", t)
            if len(chunks) == 1:
                chunks = [t[i : i + max_cols] for i in range(0, len(t), max_cols)]
            for c in chunks:
                cc = c.strip()
                if cc:
                    lines.append(_short(cc, max_cols))
                    if len(lines) >= max_lines:
                        return lines
        if len(lines) >= max_lines:
            break
    return lines


def _flow_list(status: str, limit: int, as_json: bool) -> None:
    cmd = ["tasks", "flow", "list"]
    if status:
        cmd += ["--status", status]
    cmd += ["--json"]
    raw = _run_openclaw(cmd)
    if as_json:
        print(raw.rstrip())
        return

    data = json.loads(raw)
    flows = data.get("flows", []) if isinstance(data, dict) else []
    flows = sorted(flows, key=lambda x: x.get("updatedAt", 0), reverse=True)
    show = flows[: max(1, limit)] if limit > 0 else flows

    print(f"TaskFlow 清單（共 {len(flows)} 筆，顯示 {len(show)} 筆）")
    for i, f in enumerate(show, 1):
        flow_id = f.get("flowId", "")
        stat = f.get("status", "-")
        ts = _ts(f.get("updatedAt"))
        age = _age(f.get("updatedAt"))
        summary = f.get("taskSummary") or {}
        active = summary.get("active", 0)
        total = summary.get("total", 0)
        failures = summary.get("failures", 0)
        by_status = summary.get("byStatus") or {}
        running = by_status.get("running", 0)
        queued = by_status.get("queued", 0)
        owner = _agent_from_owner_key(f.get("ownerKey"))
        tasks = f.get("tasks") or []
        first = tasks[0] if tasks else {}
        label = _short(first.get("label", ""), 56)
        goal = _short(f.get("goal", ""), 56)
        task_text = first.get("task") or ""
        task_id = _extract_task_id(task_text or f.get("goal"))
        child_status = first.get("status") or "-"
        child_agent = first.get("agentId") or owner

        print(f"{i}. [{stat}] {task_id or '-'}｜{owner}｜更新 {ts} ({age}前)")
        print(f"   flowId: {flow_id}")
        print(f"   子任務: {active}/{total} active，running={running} queued={queued} fail={failures}")
        if tasks:
            print(f"   當前: {child_agent}/{child_status}｜{label or '-'}")
        preview = _task_preview(task_text)
        if preview:
            print("   任務內容:")
            for ln in preview:
                print(f"   - {ln}")
        elif goal:
            print(f"   摘要: {goal}")


def _flow_show(lookup: str, as_json: bool) -> None:
    raw = _run_openclaw(["tasks", "flow", "show", lookup, "--json"])
    if as_json:
        print(raw.rstrip())
        return

    f = json.loads(raw)
    tasks = f.get("tasks") or []
    first = tasks[0] if tasks else {}
    task_id = _extract_task_id(first.get("task") or f.get("goal"))

    print(f"flowId: {f.get('flowId', '-')}")
    print(f"status: {f.get('status', '-')}")
    print(f"revision: {f.get('revision', '-')}")
    print(f"syncMode: {f.get('syncMode', '-')}")
    if task_id:
        print(f"taskId: {task_id}")
    if first.get("label"):
        print(f"label: {_short(first.get('label', ''), 120)}")
    print(f"goal: {_short(f.get('goal', ''), 120)}")
    print(f"updated: {_ts(f.get('updatedAt'))}")
    summary = f.get("taskSummary") or {}
    print(
        "taskSummary: "
        f"total={summary.get('total', 0)} "
        f"active={summary.get('active', 0)} "
        f"failures={summary.get('failures', 0)}"
    )


def _flow_cancel(lookup: str) -> None:
    out = _run_openclaw(["tasks", "flow", "cancel", lookup])
    print(out.rstrip())


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd in ("kanban", "tasks"):
            if args.action in ("read", "list"):
                # Telegram 路徑固定顯示完整內容（不再使用 brief）
                ku.cmd_list(
                    state=args.state,
                    active_only=args.active,
                    show_id=args.show_id,
                    limit=args.limit,
                    brief=False,
                    full=True,
                    include_session=args.include_session,
                )
                return 0
            if args.action == "create":
                ku.cmd_create(
                    args.task_id,
                    args.title,
                    args.state,
                    args.org,
                    args.official,
                    remark=args.remark,
                    source=args.source,
                )
                return 0
            if args.action in ("update-state", "state"):
                ku.cmd_state(args.task_id, args.state, args.note)
                return 0
            if args.action in ("update-flow", "flow"):
                ku.cmd_flow(args.task_id, args.from_dept, args.to_dept, args.remark)
                return 0
            if args.action in ("update-progress", "progress"):
                ku.cmd_progress(
                    args.task_id,
                    args.now,
                    args.todos,
                    tokens=args.tokens,
                    cost=args.cost,
                    elapsed=args.elapsed,
                )
                return 0
            if args.action in ("update-done", "done", "close"):
                ku.cmd_done(args.task_id, args.output, args.summary)
                return 0
            if args.action in ("delete", "cancel"):
                ku.cmd_state(args.task_id, "Cancelled", args.note)
                return 0

        if args.cmd in ("flow", "taskflow", "tf"):
            if args.flow_action in ("read", "list"):
                _flow_list(status=args.status, limit=args.limit, as_json=args.json)
                return 0
            if args.flow_action in ("read-one", "show", "get"):
                _flow_show(lookup=args.lookup, as_json=args.json)
                return 0
            if args.flow_action in ("delete", "cancel"):
                _flow_cancel(lookup=args.lookup)
                return 0

    except Exception as e:  # pragma: no cover
        print(f"❌ {e}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
