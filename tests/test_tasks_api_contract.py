"""Contract tests for tasks API parameter validation."""

import pathlib
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from edict.backend.app.api import tasks as tasks_api


class StubService:
    async def list_tasks(self, **kwargs):
        return []


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(tasks_api.router, prefix='/api/tasks')
    app.dependency_overrides[tasks_api.get_task_service] = lambda: StubService()
    app.dependency_overrides[tasks_api.require_api_key] = lambda: ''
    return TestClient(app)


def test_list_tasks_rejects_limit_above_200():
    client = make_client()

    response = client.get('/api/tasks', params={'limit': 201})

    assert response.status_code == 422
    detail = response.json()['detail']
    assert any(
        item['loc'] == ['query', 'limit'] and 'less than or equal to 200' in item['msg']
        for item in detail
    )
