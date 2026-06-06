"""Edict 端到端流程測試。

測試任務完整生命週期：建立 → 查詢 → 狀態轉換 → 進度記錄 → 驗證。
使用 requests 對執行中的 backend 進行真實 HTTP 呼叫。
"""

import uuid
import pytest
import requests

BASE = "http://localhost:8000"
def _api_key_headers():
    """若設定了 API_KEY 則回傳認證 header，否則空 dict。"""
    import os
    key = os.environ.get("EDICT_API_KEY", "")
    if not key:
        try:
            # Fallback: read from config Settings
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "edict", "backend"))
            from app.config import get_settings
            key = get_settings().api_key
        except Exception:
            pass
    if key:
        return {"X-API-Key": key}
    return {}


class TestTaskLifecycle:
    """任務完整生命週期測試。"""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """測試後清理建立的任務。"""
        self._created_ids = []
        yield
        headers = _api_key_headers()
        for tid in self._created_ids:
            try:
                requests.get(f"{BASE}/api/tasks/{tid}", timeout=5)
            except Exception:
                pass

    def _create(self, title, assignee_org="zhongshu"):
        """建立任務並記錄 ID。"""
        resp = requests.post(
            f"{BASE}/api/tasks",
            json={"title": title, "assignee_org": assignee_org},
            headers=_api_key_headers(),
        )
        if resp.status_code == 201:
            self._created_ids.append(resp.json()["task_id"])
        return resp

    def test_full_lifecycle(self):
        """完整生命週期：建立 → 查詢 → 轉換 → 進度 → 驗證。"""
        # Given: 建立一個新任務
        resp = self._create(f"e2e-test-{uuid.uuid4().hex[:8]}")
        assert resp.status_code == 201, f"建立失敗: {resp.text}"
        task = resp.json()
        task_id = task["task_id"]
        uuid_task_id = task["uuid_task_id"]
        trace_id = task["trace_id"]

        # Then: 正式旨意對外 ID 改回 JJC，內部 UUID 另存 uuid_task_id
        assert task_id.startswith("JJC-")
        uuid.UUID(uuid_task_id)

        # Then: trace_id 為 36 字元 UUID
        assert len(trace_id) == 36

        # When: 查詢任務
        resp = requests.get(f"{BASE}/api/tasks/{task_id}")
        assert resp.status_code == 200
        fetched = resp.json()
        assert fetched["task_id"] == task_id
        assert fetched["uuid_task_id"] == uuid_task_id
        assert fetched["title"].startswith("e2e-test-")

        # When: 第一次轉換 Taizi → Zhongshu
        resp = requests.post(
            f"{BASE}/api/tasks/{task_id}/transition",
            json={"new_state": "Zhongshu", "reason": "E2E test step 1"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 200, f"Taizi→Zhongshu 失敗: {resp.text}"
        assert resp.json()["state"] == "Zhongshu"

        # When: 第二次轉換 Zhongshu → Menxia
        resp = requests.post(
            f"{BASE}/api/tasks/{task_id}/transition",
            json={"new_state": "Menxia", "reason": "E2E test step 2"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 200, f"Zhongshu→Menxia 失敗: {resp.text}"
        assert resp.json()["state"] == "Menxia"

        # When: 第三次轉換 Menxia → Assigned
        resp = requests.post(
            f"{BASE}/api/tasks/{task_id}/transition",
            json={"new_state": "Assigned", "reason": "E2E test step 3"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 200, f"Menxia→Assigned 失敗: {resp.text}"

        # When: 新增進度
        resp = requests.post(
            f"{BASE}/api/tasks/{task_id}/progress",
            json={"content": "E2E test progress", "agent": "e2e-tester"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 200

        # Then: 查詢確認進度已記錄
        resp = requests.get(f"{BASE}/api/tasks/{task_id}")
        assert resp.status_code == 200
        final = resp.json()
        assert len(final.get("progress_log", [])) >= 1

    def test_three_transitions_then_done(self):
        """五階段轉換：Taizi → Zhongshu → Menxia → Assigned → Doing → Done。"""
        resp = self._create(f"e2e-transition-{uuid.uuid4().hex[:8]}")
        assert resp.status_code == 201
        task_id = resp.json()["task_id"]

        transitions = [
            ("Zhongshu", "中書起草"),
            ("Menxia", "門下審核"),
            ("Assigned", "派發三省"),
            ("Doing", "開始執行"),
            ("Done", "任務完成"),
        ]
        for state, reason in transitions:
            resp = requests.post(
                f"{BASE}/api/tasks/{task_id}/transition",
                json={"new_state": state, "reason": reason},
                headers=_api_key_headers(),
            )
            assert resp.status_code == 200, f"→{state} 失敗: {resp.text}"
            assert resp.json()["state"] == state

        # 確認為 Done
        resp = requests.get(f"{BASE}/api/tasks/{task_id}")
        assert resp.json()["state"] == "Done"


class TestStateMachineEdgeCases:
    """狀態機邊界條件測試。"""

    def test_invalid_transition_returns_400(self):
        """非法轉換應回 400。"""
        # Given: 建立任務（初始 Taizi）
        resp = requests.post(
            f"{BASE}/api/tasks",
            json={"title": f"edge-invalid-{uuid.uuid4().hex[:8]}", "assignee_org": "zhongshu"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 201
        task_id = resp.json()["task_id"]

        # When: 嘗試非法轉換 Taizi → Done（跳過中間狀態）
        resp = requests.post(
            f"{BASE}/api/tasks/{task_id}/transition",
            json={"new_state": "Done", "reason": "should fail"},
            headers=_api_key_headers(),
        )
        # Then: 應回 400
        assert resp.status_code == 400, f"預期 400，得到 {resp.status_code}: {resp.text}"

    def test_nonexistent_uuid_returns_404(self):
        """不存在的 UUID 應回 404。"""
        fake_id = str(uuid.uuid4())
        resp = requests.get(f"{BASE}/api/tasks/{fake_id}")
        assert resp.status_code == 404

    def test_non_public_or_uuid_task_id_returns_404(self):
        """非 UUID / 非已存在 public id 的 task_id 應回 404。"""
        resp = requests.get(f"{BASE}/api/tasks/not-a-uuid")
        assert resp.status_code == 404


class TestFieldValidation:
    """欄位驗證測試。"""

    def test_title_over_500_chars_returns_422(self):
        """標題超過 500 字元應回 422。"""
        resp = requests.post(
            f"{BASE}/api/tasks",
            json={"title": "A" * 501, "assignee_org": "zhongshu"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 422

    def test_empty_title_returns_422(self):
        """空白標題應回 422。"""
        resp = requests.post(
            f"{BASE}/api/tasks",
            json={"title": "", "assignee_org": "zhongshu"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 422

    def test_missing_title_returns_422(self):
        """缺少標題欄位應回 422。"""
        resp = requests.post(
            f"{BASE}/api/tasks",
            json={"assignee_org": "zhongshu"},
            headers=_api_key_headers(),
        )
        assert resp.status_code == 422


class TestAuthFlow:
    """認證流程測試。"""

    def test_auth_enforced_when_api_key_set(self):
        """API_KEY 設定時，POST 無 key 應回 401。"""
        import os
        api_key = os.environ.get("EDICT_API_KEY", "")
        if not api_key:
            pytest.skip("API_KEY 未設定，略過認證測試")

        resp = requests.post(
            f"{BASE}/api/tasks",
            json={"title": "no-auth-test", "assignee_org": "zhongshu"},
        )
        assert resp.status_code == 401, f"預期 401，得到 {resp.status_code}"

    def test_auth_passes_with_correct_key(self):
        """正確 API key 的 POST 應成功。"""
        import os
        api_key = os.environ.get("EDICT_API_KEY", "")
        if not api_key:
            pytest.skip("API_KEY 未設定，略過認證測試")

        resp = requests.post(
            f"{BASE}/api/tasks",
            json={"title": f"auth-test-{uuid.uuid4().hex[:8]}", "assignee_org": "zhongshu"},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 201, f"預期 201，得到 {resp.status_code}: {resp.text}"
