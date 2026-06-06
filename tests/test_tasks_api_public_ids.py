"""Tasks API public-ID regression tests without a live backend."""

from datetime import datetime
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from edict.backend.app.api import tasks as tasks_api
from edict.backend.app.models.task import Task, TaskState


def make_task(public_id: str, state: TaskState = TaskState.Taizi) -> Task:
    task = Task()
    task.task_id = uuid.uuid4()
    task.trace_id = str(uuid.uuid4())
    task.title = "測試任務"
    task.description = "測試描述"
    task.priority = "中"
    task.state = state
    task.assignee_org = None
    task.creator = "emperor"
    task.tags = []
    task.meta = {"legacy_id": public_id}
    task.org = "太子"
    task.official = ""
    task.now = ""
    task.output = ""
    task.block = "無"
    task.flow_log = []
    task.progress_log = []
    task.todos = []
    task.scheduler = {}
    task.template_id = ""
    task.template_params = {}
    task.ac = ""
    task.target_dept = ""
    task.created_at = datetime(2026, 6, 5)
    task.updated_at = datetime(2026, 6, 5)
    task.archived = False
    return task


class StubService:
    def __init__(self, *, create_task_result=None, get_task_result=None, transition_result=None, transition_error=None):
        self.create_task_result = create_task_result
        self.get_task_result = get_task_result
        self.transition_result = transition_result
        self.transition_error = transition_error
        self.get_task_calls = []
        self.transition_calls = []

    async def create_task(self, **kwargs):
        return self.create_task_result

    async def get_task(self, task_id):
        self.get_task_calls.append(task_id)
        if isinstance(self.get_task_result, Exception):
            raise self.get_task_result
        return self.get_task_result

    async def transition_state(self, **kwargs):
        self.transition_calls.append(kwargs)
        if self.transition_error is not None:
            raise self.transition_error
        return self.transition_result


def make_client(stub: StubService) -> TestClient:
    app = FastAPI()
    app.include_router(tasks_api.router, prefix="/api/tasks")
    app.dependency_overrides[tasks_api.get_task_service] = lambda: stub
    app.dependency_overrides[tasks_api.require_api_key] = lambda: ""
    return TestClient(app)


def test_create_task_returns_public_jjc_id_and_internal_uuid():
    task = make_task("JJC-20260605-001")
    client = make_client(StubService(create_task_result=task))

    response = client.post("/api/tasks", json={"title": "正式旨意"})

    assert response.status_code == 201
    data = response.json()
    assert data["task_id"] == "JJC-20260605-001"
    assert data["state"] == "Taizi"
    uuid.UUID(data["uuid_task_id"])
    assert data["uuid_task_id"] == str(task.task_id)


def test_get_task_accepts_prefixed_public_id():
    task = make_task("TEST-20260605-001")
    stub = StubService(get_task_result=task)
    client = make_client(stub)

    response = client.get("/api/tasks/TEST-20260605-001")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "TEST-20260605-001"
    assert data["uuid_task_id"] == str(task.task_id)
    assert stub.get_task_calls == ["TEST-20260605-001"]


def test_transition_nonexistent_task_returns_404():
    stub = StubService(transition_error=ValueError("Task not found"))
    client = make_client(stub)

    response = client.post(
        "/api/tasks/JJC-20260605-404/transition",
        json={"new_state": "Zhongshu", "agent": "pytest", "reason": "not found"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"
