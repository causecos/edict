"""Tasks API — 任務的 CRUD 和狀態流轉。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..auth import require_api_key
from ..models.task import TaskState
from ..services.event_bus import get_event_bus
from ..services.task_service import TaskService

log = logging.getLogger("edict.api.tasks")
router = APIRouter()


# ── Schemas ──

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="任務標題")
    description: str = Field(default="", max_length=5000, description="任務描述")
    priority: str = "中"
    assignee_org: str | None = None
    creator: str = "emperor"
    tags: list[str] = []
    meta: dict | None = None


class TaskTransition(BaseModel):
    new_state: str
    agent: str = "system"
    reason: str = ""


class TaskProgress(BaseModel):
    agent: str
    content: str


class TaskTodoUpdate(BaseModel):
    todos: list[dict]


class TaskSchedulerUpdate(BaseModel):
    scheduler: dict


class TaskDashboardPatch(BaseModel):
    fields: dict = Field(default_factory=dict)
    flow_entry: dict | None = None
    progress_entry: dict | None = None
    meta_updates: dict | None = None
    producer: str = "dashboard"


class TaskOut(BaseModel):
    task_id: str
    uuid_task_id: str
    trace_id: str
    title: str
    description: str
    priority: str
    state: str
    assignee_org: str | None
    creator: str
    tags: list[str]
    flow_log: list
    progress_log: list
    todos: list
    scheduler: dict | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ── 依賴注入 helper ──

async def get_task_service(
    db: AsyncSession = Depends(get_db),
) -> TaskService:
    """建立 TaskService 實例，注入 DB session 與 EventBus。

    透過 FastAPI Depends 機制，每個 request 自動取得獨立的 DB session
    （由 get_db 的 async_scoped_session 管理生命週期）。
    """
    bus = await get_event_bus()
    return TaskService(db, bus)


# ── Endpoints ──

@router.get("")
async def list_tasks(
    state: str | None = None,
    assignee_org: str | None = None,
    priority: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    svc: TaskService = Depends(get_task_service),
):
    """獲取任務列表 — 支援多重過濾與分頁。

    查詢參數均可選：state/assignee_org/priority 任一未填則不過濾該維度。
    limit 上限 200，防止單次查詢載入過多資料。
    """
    task_state = TaskState(state) if state else None
    tasks = await svc.list_tasks(
        state=task_state,
        assignee_org=assignee_org,
        priority=priority,
        limit=limit,
        offset=offset,
    )
    return {"tasks": [t.to_dict() for t in tasks], "count": len(tasks)}


@router.get("/live-status")
async def live_status(svc: TaskService = Depends(get_task_service)):
    """兼容舊 live_status.json 格式的全局狀態。

    將 active/completed 任務分開回傳，格式與舊版 Dashboard 預期一致。
    """
    return await svc.get_live_status()


@router.get("/stats")
async def task_stats(svc: TaskService = Depends(get_task_service)):
    """任務統計 — 按狀態彙總數量。"""
    stats = {}
    for s in TaskState:
        stats[s.value] = await svc.count_tasks(s)
    total = sum(stats.values())
    return {"total": total, "by_state": stats}


@router.post("", status_code=201, dependencies=[Depends(require_api_key)])
async def create_task(
    body: TaskCreate,
    svc: TaskService = Depends(get_task_service),
):
    """創建新任務 — 需 API Key 驗證。

    寫入 task 的同時會在同一個事務中寫入 outbox 事件，
    確保 task 建立與事件發佈的原子性。
    """
    task = await svc.create_task(
        title=body.title,
        description=body.description,
        priority=body.priority,
        assignee_org=body.assignee_org,
        creator=body.creator,
        tags=body.tags,
        meta=body.meta,
    )
    response = task.to_dict()
    return {"task_id": response["task_id"], "uuid_task_id": response["uuid_task_id"], "trace_id": str(task.trace_id), "state": task.state.value}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    svc: TaskService = Depends(get_task_service),
):
    """獲取任務詳情 — 支援對外 JJC/TEST/OC/MC ID 與內部 UUID。"""
    try:
        task = await svc.get_task(task_id)
        return task.to_dict()
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")


@router.post("/{task_id}/transition", dependencies=[Depends(require_api_key)])
async def transition_task(
    task_id: str,
    body: TaskTransition,
    svc: TaskService = Depends(get_task_service),
):
    """執行狀態流轉 — 需 API Key 驗證。

    校驗 new_state 是否為合法的 TaskState 枚舉值，
    再由 TaskService.transition_state 檢查狀態轉換矩陣。
    """
    try:
        new_state = TaskState(body.new_state)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid state: {body.new_state}")

    try:
        task = await svc.transition_state(
            task_id=task_id,
            new_state=new_state,
            agent=body.agent,
            reason=body.reason,
        )
        response = task.to_dict()
        return {"task_id": response["task_id"], "uuid_task_id": response["uuid_task_id"], "state": task.state.value, "message": "ok"}
    except ValueError as e:
        detail = str(e)
        status_code = 404 if "Task not found" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail)


@router.post("/{task_id}/dispatch", dependencies=[Depends(require_api_key)])
async def dispatch_task(
    task_id: str,
    agent: str = Query(description="目標 agent"),
    message: str = Query(default="", description="派發消息"),
    svc: TaskService = Depends(get_task_service),
):
    """手動派發任務給指定 agent — 需 API Key 驗證。

    事件寫入 outbox 後，由 OutboxRelay 投遞至 Redis Stream，
    DispatchWorker 消費後執行實際派發。
    """
    try:
        await svc.request_dispatch(task_id, agent, message)
        return {"message": "dispatch requested", "agent": agent}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{task_id}/progress", dependencies=[Depends(require_api_key)])
async def add_progress(
    task_id: str,
    body: TaskProgress,
    svc: TaskService = Depends(get_task_service),
):
    """添加進度記錄。"""
    try:
        await svc.add_progress(task_id, body.agent, body.content)
        return {"message": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{task_id}/todos", dependencies=[Depends(require_api_key)])
async def update_todos(
    task_id: str,
    body: TaskTodoUpdate,
    svc: TaskService = Depends(get_task_service),
):
    """更新任務 TODO 清單。"""
    try:
        await svc.update_todos(task_id, body.todos)
        return {"message": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{task_id}/scheduler", dependencies=[Depends(require_api_key)])
async def update_scheduler(
    task_id: str,
    body: TaskSchedulerUpdate,
    svc: TaskService = Depends(get_task_service),
):
    """更新任務排期信息。"""
    try:
        await svc.update_scheduler(task_id, body.scheduler)
        return {"message": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{task_id}/dashboard", dependencies=[Depends(require_api_key)])
async def patch_dashboard_task(
    task_id: str,
    body: TaskDashboardPatch,
    svc: TaskService = Depends(get_task_service),
):
    """Dashboard 專用兼容補丁：統一更新 legacy 欄位 / scheduler / meta / flow / progress。"""
    try:
        task = await svc.patch_dashboard_fields(
            task_id,
            fields=body.fields,
            flow_entry=body.flow_entry,
            progress_entry=body.progress_entry,
            meta_updates=body.meta_updates,
            producer=body.producer,
        )
        return task.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
