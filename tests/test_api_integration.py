# -*- coding: utf-8 -*-
"""
Edict API 介面測試 + 功能測試

使用 requests 庫對執行中的 backend (localhost:8000) 和 dashboard (localhost:7891)
進行 HTTP 端點測試，驗證回應碼、格式、認證機制。

測試範圍：
  1. Backend API (FastAPI, port 8000)
  2. Dashboard API (Flask-like HTTP server, port 7891)
  3. Auth 驗證

執行方式：
  pytest tests/test_api_integration.py -v --junitxml=_output/junit-api.xml
"""

import json
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests

# ── 測試配置 ──

BACKEND_URL = os.environ.get("EDICT_BACKEND_URL", "http://localhost:8000")
DASHBOARD_URL = os.environ.get("EDICT_DASHBOARD_URL", "http://localhost:7891")

# 用於認證測試的假 API Key
FAKE_API_KEY = "test-api-key-that-should-not-exist-12345"


def _is_backend_available() -> bool:
    """檢查 backend 是否可連通。"""
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


def _is_dashboard_available() -> bool:
    """檢查 dashboard 是否可連通。"""
    try:
        r = requests.get(f"{DASHBOARD_URL}/healthz", timeout=5)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


def _is_backend_auth_required() -> bool:
    """檢查 backend 是否啟用了 API Key 認證（POST 需要 key）。"""
    try:
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "__auth_probe__"},
            timeout=5,
        )
        return r.status_code == 401
    except requests.ConnectionError:
        return False


# ── 全域 skip 條件 ──

_backend_ok = _is_backend_available()
_dashboard_ok = _is_dashboard_available()
_auth_required = _is_backend_auth_required()

pytestmark_requires_backend = pytest.mark.skipif(
    not _backend_ok, reason="Backend (localhost:8000) 未執行"
)
pytestmark_requires_dashboard = pytest.mark.skipif(
    not _dashboard_ok, reason="Dashboard (localhost:7891) 未執行"
)


# ============================================================
#  1. Backend API 測試
# ============================================================


class TestBackendHealth:
    """Backend 健康檢查端點測試。"""

    @pytestmark_requires_backend
    def test_health_returns_200(self):
        """GET /health 應回傳 200 與 JSON 格式回應。"""
        r = requests.get(f"{BACKEND_URL}/health", timeout=10)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        assert r.headers["Content-Type"].startswith("application/json")

    @pytestmark_requires_backend
    def test_health_contains_expected_fields(self):
        """GET /health 回應應包含 status, version, engine 欄位。"""
        r = requests.get(f"{BACKEND_URL}/health", timeout=10)
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert data["engine"] == "edict"
        assert data["version"] == "2.0.0"

    @pytestmark_requires_backend
    def test_api_root_returns_200(self):
        """GET /api 應回傳 API 根訊息。"""
        r = requests.get(f"{BACKEND_URL}/api", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Edict 三省六部 API"
        assert "endpoints" in data


class TestBackendTasksList:
    """Backend 任務列表端點測試。"""

    @pytestmark_requires_backend
    def test_list_tasks_returns_200(self):
        """GET /api/tasks 應回傳 200 與 JSON 格式。"""
        r = requests.get(f"{BACKEND_URL}/api/tasks", timeout=10)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("application/json")

    @pytestmark_requires_backend
    def test_list_tasks_has_correct_structure(self):
        """GET /api/tasks 回應應包含 tasks 陣列與 count 欄位。"""
        r = requests.get(f"{BACKEND_URL}/api/tasks", timeout=10)
        data = r.json()
        assert "tasks" in data
        assert "count" in data
        assert isinstance(data["tasks"], list)
        assert data["count"] == len(data["tasks"])

    @pytestmark_requires_backend
    def test_list_tasks_with_state_filter(self):
        """GET /api/tasks?state=Taizi 應支援狀態過濾。"""
        r = requests.get(f"{BACKEND_URL}/api/tasks", params={"state": "Taizi"}, timeout=10)
        assert r.status_code == 200
        data = r.json()
        for task in data["tasks"]:
            assert task["state"] == "Taizi"

    @pytestmark_requires_backend
    def test_list_tasks_with_limit(self):
        """GET /api/tasks?limit=5 應遵守 limit 參數。"""
        r = requests.get(f"{BACKEND_URL}/api/tasks", params={"limit": 5}, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert len(data["tasks"]) <= 5

    @pytestmark_requires_backend
    def test_task_stats_returns_200(self):
        """GET /api/tasks/stats 應回傳任務統計資訊。"""
        r = requests.get(f"{BACKEND_URL}/api/tasks/stats", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "by_state" in data
        assert isinstance(data["by_state"], dict)


class TestBackendTaskCreate:
    """Backend 任務建立端點測試。"""

    @pytestmark_requires_backend
    def test_create_task_returns_201(self):
        """POST /api/tasks 正確請求應回傳 201 並建立任務。"""
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "API 測試任務", "description": "自動化測試建立的任務"},
            timeout=10,
        )
        # auth 未啟用時應回 201，啟用時回 401
        if _auth_required:
            assert r.status_code == 401
        else:
            assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
            data = r.json()
            assert "task_id" in data
            assert "uuid_task_id" in data
            assert "trace_id" in data
            assert data["state"] == "Taizi"
            assert data["task_id"].startswith("JJC-")
            uuid.UUID(data["uuid_task_id"])

    @pytestmark_requires_backend
    def test_create_task_with_all_fields(self):
        """POST /api/tasks 含完整欄位應正確建立任務。"""
        if _auth_required:
            pytest.skip("API Key 認證已啟用，需提供有效 key")

        payload = {
            "title": "完整欄位測試任務",
            "description": "包含所有可選欄位的測試",
            "priority": "高",
            "assignee_org": "兵部",
            "creator": "emperor",
            "tags": ["測試", "API"],
            "meta": {"source": "pytest"},
        }
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json=payload,
            timeout=10,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["state"] == "Taizi"

    @pytestmark_requires_backend
    def test_create_task_missing_title_returns_422(self):
        """POST /api/tasks 缺標題應回傳 422 驗證錯誤。"""
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"description": "沒有標題"},
            timeout=10,
        )
        if _auth_required:
            assert r.status_code == 401
        else:
            assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

    @pytestmark_requires_backend
    def test_create_task_empty_body_returns_422(self):
        """POST /api/tasks 空請求體應回傳 422。"""
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={},
            timeout=10,
        )
        if _auth_required:
            assert r.status_code == 401
        else:
            assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

    @pytestmark_requires_backend
    def test_create_task_title_too_long_returns_422(self):
        """POST /api/tasks 標題超過 500 字元應回傳 422。"""
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "x" * 501},
            timeout=10,
        )
        if _auth_required:
            assert r.status_code == 401
        else:
            assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

    @pytestmark_requires_backend
    def test_create_task_empty_title_returns_422(self):
        """POST /api/tasks 空標題應回傳 422。"""
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": ""},
            timeout=10,
        )
        if _auth_required:
            assert r.status_code == 401
        else:
            assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


class TestBackendTaskTransition:
    """Backend 任務狀態流轉端點測試。"""

    @pytestmark_requires_backend
    def test_transition_valid_state_succeeds(self):
        """POST /api/tasks/{id}/transition 有效狀態轉換應成功。"""
        if _auth_required:
            pytest.skip("API Key 認證已啟用，需提供有效 key")

        # 先建立一個任務
        create_r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "流轉測試任務"},
            timeout=10,
        )
        if create_r.status_code != 201:
            pytest.skip(f"無法建立測試任務 (status={create_r.status_code})")

        task_id = create_r.json()["task_id"]

        # Taizi → Zhongshu (有效轉換)
        r = requests.post(
            f"{BACKEND_URL}/api/tasks/{task_id}/transition",
            json={"new_state": "Zhongshu", "agent": "test", "reason": "自動化測試流轉"},
            timeout=10,
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["state"] == "Zhongshu"
        assert data["message"] == "ok"

    @pytestmark_requires_backend
    def test_transition_invalid_state_fails(self):
        """POST /api/tasks/{id}/transition 無效狀態轉換應回 400。"""
        if _auth_required:
            pytest.skip("API Key 認證已啟用，需提供有效 key")

        # 先建立一個任務
        create_r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "無效流轉測試任務"},
            timeout=10,
        )
        if create_r.status_code != 201:
            pytest.skip(f"無法建立測試任務 (status={create_r.status_code})")

        task_id = create_r.json()["task_id"]

        # Taizi → Done (無效轉換，Taizi 不能直接到 Done)
        r = requests.post(
            f"{BACKEND_URL}/api/tasks/{task_id}/transition",
            json={"new_state": "Done", "agent": "test", "reason": "嘗試無效轉換"},
            timeout=10,
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        data = r.json()
        assert "detail" in data

    @pytestmark_requires_backend
    def test_transition_invalid_state_name_returns_400(self):
        """POST /api/tasks/{id}/transition 不存在的狀態名應回 400。"""
        if _auth_required:
            pytest.skip("API Key 認證已啟用，需提供有效 key")

        # 先建立一個任務
        create_r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "不存在狀態流轉測試"},
            timeout=10,
        )
        if create_r.status_code != 201:
            pytest.skip(f"無法建立測試任務 (status={create_r.status_code})")

        task_id = create_r.json()["task_id"]

        r = requests.post(
            f"{BACKEND_URL}/api/tasks/{task_id}/transition",
            json={"new_state": "NonExistentState", "agent": "test"},
            timeout=10,
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"

    @pytestmark_requires_backend
    def test_transition_nonexistent_task_returns_404(self):
        """POST /api/tasks/{id}/transition 對不存在任務應回 404。"""
        if _auth_required:
            pytest.skip("API Key 認證已啟用，需提供有效 key")

        fake_id = "00000000-0000-0000-0000-000000000000"
        r = requests.post(
            f"{BACKEND_URL}/api/tasks/{fake_id}/transition",
            json={"new_state": "Zhongshu", "agent": "test"},
            timeout=10,
        )
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
        data = r.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    @pytestmark_requires_backend
    def test_get_task_by_id_returns_200(self):
        """GET /api/tasks/{id} 應回傳任務詳情。"""
        if _auth_required:
            pytest.skip("API Key 認證已啟用，需提供有效 key")

        # 先建立一個任務
        create_r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "取得任務詳情測試"},
            timeout=10,
        )
        if create_r.status_code != 201:
            pytest.skip(f"無法建立測試任務 (status={create_r.status_code})")

        task_id = create_r.json()["task_id"]

        r = requests.get(f"{BACKEND_URL}/api/tasks/{task_id}", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"] == task_id
        assert "uuid_task_id" in data
        uuid.UUID(data["uuid_task_id"])
        assert data["title"] == "取得任務詳情測試"

    @pytestmark_requires_backend
    def test_get_task_nonexistent_returns_404(self):
        """GET /api/tasks/{id} 對不存在任務應回 404。"""
        fake_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        r = requests.get(f"{BACKEND_URL}/api/tasks/{fake_id}", timeout=10)
        assert r.status_code == 404


class TestBackendAdminSourceMode:
    """Backend Admin 來源模式 API 測試。"""

    @pytestmark_requires_backend
    def test_get_source_mode_returns_200(self):
        """GET /api/admin/source-mode 應回傳 200 與來源模式配置。"""
        r = requests.get(f"{BACKEND_URL}/api/admin/source-mode", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "config" in data
        assert "effective" in data
        assert data["config"]["mode"] in ("auto", "json", "db")

    @pytestmark_requires_backend
    def test_post_source_mode_requires_auth(self):
        """POST /api/admin/source-mode 在 API_KEY 啟用時應需認證。"""
        r = requests.post(
            f"{BACKEND_URL}/api/admin/source-mode",
            json={"mode": "json"},
            timeout=10,
        )
        if _auth_required:
            # API_KEY 已設定時應回 401
            assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
        else:
            # 開發模式：直接成功
            assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
            data = r.json()
            assert data["ok"] is True

    @pytestmark_requires_backend
    def test_post_source_mode_invalid_mode_returns_400(self):
        """POST /api/admin/source-mode 無效 mode 值應回 400。"""
        if _auth_required:
            pytest.skip("API Key 認證已啟用，需提供有效 key")

        r = requests.post(
            f"{BACKEND_URL}/api/admin/source-mode",
            json={"mode": "invalid_mode"},
            timeout=10,
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"


class TestBackendAdminConfig:
    """Backend Admin 配置端點測試。"""

    @pytestmark_requires_backend
    def test_get_config_returns_200(self):
        """GET /api/admin/config 應回傳當前配置資訊。"""
        r = requests.get(f"{BACKEND_URL}/api/admin/config", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "port" in data
        assert "debug" in data

    @pytestmark_requires_backend
    def test_deep_health_returns_200(self):
        """GET /api/admin/health/deep 應回傳深度健康檢查結果。"""
        r = requests.get(f"{BACKEND_URL}/api/admin/health/deep", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "checks" in data
        assert "postgres" in data["checks"]
        assert "redis" in data["checks"]


# ============================================================
#  2. Dashboard API 測試
# ============================================================


class TestDashboardHealth:
    """Dashboard 健康檢查端點測試。"""

    @pytestmark_requires_dashboard
    def test_healthz_returns_200(self):
        """GET /healthz 應回傳 200 與 JSON 格式。"""
        r = requests.get(f"{DASHBOARD_URL}/healthz", timeout=10)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("application/json")

    @pytestmark_requires_dashboard
    def test_healthz_contains_expected_fields(self):
        """GET /healthz 回應應包含 status, ts, checks 欄位。"""
        r = requests.get(f"{DASHBOARD_URL}/healthz", timeout=10)
        data = r.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded")
        assert "ts" in data
        assert "checks" in data
        assert "dataDir" in data["checks"]
        assert "tasksReadable" in data["checks"]
        assert "dataWritable" in data["checks"]


class TestDashboardLiveStatus:
    """Dashboard 任務即時狀態端點測試。"""

    @pytestmark_requires_dashboard
    def test_live_status_returns_200(self):
        """GET /api/live-status 應回傳 200 與 JSON 格式。"""
        r = requests.get(f"{DASHBOARD_URL}/api/live-status", timeout=10)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("application/json")

    @pytestmark_requires_dashboard
    def test_live_status_has_expected_structure(self):
        """GET /api/live-status 回應應包含 tasks 陣列與來源元資訊。"""
        r = requests.get(f"{DASHBOARD_URL}/api/live-status", timeout=10)
        data = r.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)
        assert "_sourceMeta" in data
        assert "effective" in data["_sourceMeta"]

    @pytestmark_requires_dashboard
    def test_live_status_tasks_have_required_fields(self):
        """GET /api/live-status 中的每個任務應包含基本欄位。"""
        r = requests.get(f"{DASHBOARD_URL}/api/live-status", timeout=10)
        data = r.json()
        tasks = data.get("tasks", [])
        if tasks:
            task = tasks[0]
            task_id = task.get("id") or task.get("task_id")
            assert task_id
            assert "title" in task or "name" in task
            assert "state" in task
            # 正式任務應為 JJC-*；其他保留 TEST/OC/MC 等 prefix，相容舊 UUID 陰影資料
            assert (
                task_id.startswith(("JJC-", "TEST-", "OC-", "MC-"))
                or task_id.count("-") == 4
            )


class TestDashboardI18n:
    """Dashboard 多語言端點測試。"""

    @pytestmark_requires_dashboard
    def test_i18n_returns_200(self):
        """GET /api/i18n 應回傳 200 與 JSON 格式。"""
        r = requests.get(f"{DASHBOARD_URL}/api/i18n", timeout=10)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("application/json")

    @pytestmark_requires_dashboard
    def test_i18n_contains_language_keys(self):
        """GET /api/i18n 回應中的翻譯條目應包含 zh_TW、zh_CN、en 語言鍵。"""
        r = requests.get(f"{DASHBOARD_URL}/api/i18n", timeout=10)
        data = r.json()
        assert isinstance(data, dict)
        assert len(data) > 0, "i18n 資料不應為空"

        # 取第一個翻譯條目檢查語言鍵
        first_value = next(iter(data.values()))
        assert isinstance(first_value, dict), (
            f"i18n 條目應為 dict，實際為 {type(first_value).__name__}"
        )
        # 至少應包含 zh_TW 或 zh_CN 或 en 其中之一
        lang_keys_present = set(first_value.keys()) & {"zh_TW", "zh_CN", "en"}
        assert len(lang_keys_present) > 0, (
            f"翻譯條目缺少語言鍵 (zh_TW/zh_CN/en)，現有鍵: {list(first_value.keys())}"
        )

    @pytestmark_requires_dashboard
    def test_i18n_has_common_keys(self):
        """GET /api/i18n 應包含常見頁面翻譯鍵。"""
        r = requests.get(f"{DASHBOARD_URL}/api/i18n", timeout=10)
        data = r.json()
        # 檢查常見的頁面標題鍵
        common_keys = ["page.title", "header.logo", "header.sync"]
        found = [k for k in common_keys if k in data]
        assert len(found) >= 1, f"缺少常見翻譯鍵。已找到: {found}"


class TestDashboardSourceMode:
    """Dashboard 來源模式端點測試。"""

    @pytestmark_requires_dashboard
    def test_source_mode_get_returns_200(self):
        """GET /api/source-mode 應回傳 200 與來源模式資訊。"""
        r = requests.get(f"{DASHBOARD_URL}/api/source-mode", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "config" in data
        assert "backend" in data

    @pytestmark_requires_dashboard
    def test_source_mode_post_returns_200(self):
        """POST /api/source-mode 應回傳 200（dashboard API 使用獨立認證系統）。"""
        # Dashboard 使用 JWT 認證，非後端 API Key。
        # 若未設定 JWT 密碼則無需認證
        r = requests.post(
            f"{DASHBOARD_URL}/api/source-mode",
            json={"mode": "auto"},
            timeout=10,
        )
        # 未設定 JWT 時直接成功，已設定時回 401
        assert r.status_code in (200, 401), (
            f"Expected 200 or 401, got {r.status_code}: {r.text}"
        )
        if r.status_code == 200:
            data = r.json()
            assert data["ok"] is True


class TestDashboardAgentConfig:
    """Dashboard Agent 配置端點測試。"""

    @pytestmark_requires_dashboard
    def test_agent_config_returns_200(self):
        """GET /api/agent-config 應回傳 200。"""
        r = requests.get(f"{DASHBOARD_URL}/api/agent-config", timeout=10)
        assert r.status_code == 200
        data = r.json()
        # 應為 dict，可能包含 agents 列表
        assert isinstance(data, dict)


# ============================================================
#  3. Auth 認證驗證測試
# ============================================================


class TestAuthGetEndpoints:
    """認證：GET 端點應始終開放。"""

    @pytestmark_requires_backend
    def test_get_health_without_api_key_succeeds(self):
        """無 API key 的 GET /health 請求應成功回傳 200。"""
        r = requests.get(f"{BACKEND_URL}/health", timeout=10)
        assert r.status_code == 200

    @pytestmark_requires_backend
    def test_get_tasks_without_api_key_succeeds(self):
        """無 API key 的 GET /api/tasks 請求應成功回傳 200。"""
        r = requests.get(f"{BACKEND_URL}/api/tasks", timeout=10)
        assert r.status_code == 200

    @pytestmark_requires_backend
    def test_get_admin_source_mode_without_api_key_succeeds(self):
        """無 API key 的 GET /api/admin/source-mode 請求應成功回傳 200。"""
        r = requests.get(f"{BACKEND_URL}/api/admin/source-mode", timeout=10)
        assert r.status_code == 200

    @pytestmark_requires_backend
    def test_get_admin_config_without_api_key_succeeds(self):
        """無 API key 的 GET /api/admin/config 請求應成功回傳 200。"""
        r = requests.get(f"{BACKEND_URL}/api/admin/config", timeout=10)
        assert r.status_code == 200

    @pytestmark_requires_dashboard
    def test_get_dashboard_healthz_without_auth_succeeds(self):
        """無認證的 GET /healthz (dashboard) 請求應成功回傳 200。"""
        r = requests.get(f"{DASHBOARD_URL}/healthz", timeout=10)
        assert r.status_code == 200

    @pytestmark_requires_dashboard
    def test_get_dashboard_i18n_without_auth_succeeds(self):
        """無認證的 GET /api/i18n (dashboard) 請求應成功回傳 200。"""
        r = requests.get(f"{DASHBOARD_URL}/api/i18n", timeout=10)
        assert r.status_code == 200


class TestAuthPostEndpoints:
    """認證：POST 端點的 API Key 驗證。"""

    @pytestmark_requires_backend
    def test_post_without_api_key_behavior(self):
        """無 API key 的 POST /api/tasks：當 API_KEY 設定時應回 401，否則應成功。"""
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "auth-test-no-key"},
            timeout=10,
        )
        if _auth_required:
            assert r.status_code == 401, (
                f"API_KEY 已設定，無 key 應回 401，實際回 {r.status_code}"
            )
        else:
            assert r.status_code == 201, (
                f"API_KEY 未設定，無 key 應回 201，實際回 {r.status_code}: {r.text}"
            )

    @pytestmark_requires_backend
    def test_post_with_wrong_api_key_returns_401(self):
        """錯誤 API key 的 POST /api/tasks 應回 401（當 API_KEY 設定時）。"""
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "auth-test-wrong-key"},
            headers={"X-API-Key": FAKE_API_KEY},
            timeout=10,
        )
        if _auth_required:
            assert r.status_code == 401, (
                f"錯誤 API key 應回 401，實際回 {r.status_code}: {r.text}"
            )
        else:
            # 開發模式：即使帶 key 也不會拒絕
            assert r.status_code == 201, (
                f"開發模式應回 201，實際回 {r.status_code}: {r.text}"
            )

    @pytestmark_requires_backend
    def test_post_with_wrong_bearer_token_returns_401(self):
        """使用錯誤 Bearer token 的 POST /api/tasks 應回 401（當 API_KEY 設定時）。"""
        r = requests.post(
            f"{BACKEND_URL}/api/tasks",
            json={"title": "auth-test-wrong-bearer"},
            headers={"Authorization": f"Bearer {FAKE_API_KEY}"},
            timeout=10,
        )
        if _auth_required:
            assert r.status_code == 401, (
                f"錯誤 Bearer token 應回 401，實際回 {r.status_code}: {r.text}"
            )
        else:
            assert r.status_code == 201, (
                f"開發模式應回 201，實際回 {r.status_code}: {r.text}"
            )

    @pytestmark_requires_backend
    def test_post_admin_source_mode_without_key(self):
        """無 API key 的 POST /api/admin/source-mode 行為驗證。"""
        r = requests.post(
            f"{BACKEND_URL}/api/admin/source-mode",
            json={"mode": "auto"},
            timeout=10,
        )
        if _auth_required:
            assert r.status_code == 401, (
                f"API_KEY 已設定，無 key 應回 401，實際回 {r.status_code}"
            )
        else:
            assert r.status_code == 200, (
                f"開發模式應回 200，實際回 {r.status_code}: {r.text}"
            )


# ============================================================
#  4. 回應格式與內容類型驗證
# ============================================================


class TestResponseFormat:
    """HTTP 回應格式驗證。"""

    @pytestmark_requires_backend
    def test_backend_json_content_type(self):
        """Backend JSON 端點應回傳 Content-Type: application/json。"""
        endpoints = [
            "/health",
            "/api",
            "/api/tasks",
            "/api/tasks/stats",
            "/api/admin/source-mode",
            "/api/admin/config",
        ]
        for endpoint in endpoints:
            r = requests.get(f"{BACKEND_URL}{endpoint}", timeout=10)
            assert r.status_code == 200, f"{endpoint} returned {r.status_code}"
            ct = r.headers.get("Content-Type", "")
            assert ct.startswith("application/json"), (
                f"{endpoint}: expected application/json, got {ct}"
            )

    @pytestmark_requires_dashboard
    def test_dashboard_json_content_type(self):
        """Dashboard JSON 端點應回傳 Content-Type: application/json; charset=utf-8。"""
        endpoints = [
            "/healthz",
            "/api/live-status",
            "/api/i18n",
            "/api/source-mode",
            "/api/agent-config",
        ]
        for endpoint in endpoints:
            r = requests.get(f"{DASHBOARD_URL}{endpoint}", timeout=10)
            assert r.status_code == 200, f"{endpoint} returned {r.status_code}"
            ct = r.headers.get("Content-Type", "")
            assert "application/json" in ct, (
                f"{endpoint}: expected application/json, got {ct}"
            )

    @pytestmark_requires_backend
    def test_error_response_is_json(self):
        """錯誤回應也應為 JSON 格式。"""
        # 測試 404
        r = requests.get(
            f"{BACKEND_URL}/api/tasks/00000000-0000-0000-0000-000000000000",
            timeout=10,
        )
        assert r.status_code == 404
        ct = r.headers.get("Content-Type", "")
        assert "application/json" in ct, f"404 error should be JSON, got {ct}"
        data = r.json()
        assert "detail" in data
