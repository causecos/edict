"""Regression tests for dashboard DB-mode bridge/action contracts."""

import json
import pathlib
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'dashboard'))
sys.path.insert(0, str(ROOT / 'scripts'))


DB_CFG = {
    'mode': 'db',
    'backendApiBase': 'http://backend.test',
    'timeoutMs': 5000,
}


def _task(task_id: str, *, state: str = 'Taizi', archived: bool = False, minutes_stale: int = 120):
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_stale)
    stale_at = stale_at.replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    return {
        'id': task_id,
        'title': f'task-{task_id}',
        'state': state,
        'archived': archived,
        'updatedAt': stale_at,
        '_scheduler': {
            'enabled': True,
            'stallThresholdSec': 60,
            'retryCount': 0,
            'maxRetry': 1,
            'escalationLevel': 0,
            'rollbackCount': 0,
            'maxRollback': 1,
            'autoRollback': True,
            'lastProgressAt': stale_at,
            'snapshot': {'state': state},
        },
    }


def _filler_tasks(count: int, **task_kwargs):
    return [_task(f'JJC-20260606-{idx:03d}', **task_kwargs) for idx in range(count)]


def _install_backend_stubs(monkeypatch, srv, pages_by_offset):
    calls = []

    def fake_backend_api(method, path, body=None, cfg=None):
        assert method == 'GET'
        parsed = urlparse(path)
        params = parse_qs(parsed.query)
        limit = int(params['limit'][0])
        offset = int(params['offset'][0])
        archived = params.get('archived', ['true'])[0]
        assert limit <= 200, f'dashboard bridge exceeded backend limit: {limit}'
        calls.append({
            'path': path,
            'limit': limit,
            'offset': offset,
            'archived': archived,
        })
        return {'tasks': pages_by_offset.get(offset, [])}

    monkeypatch.setattr(srv, '_backend_api_json', fake_backend_api)
    monkeypatch.setattr(srv, '_fetch_backend_live_status', lambda cfg=None: {'tasks': []})
    monkeypatch.setattr(srv, '_normalize_backend_live_status', lambda payload: payload)
    monkeypatch.setattr(srv, '_sync_shadow_from_backend', lambda cfg=None, payload=None: payload or {'tasks': []})
    monkeypatch.setattr(srv, '_load_task_source_mode', lambda: DB_CFG.copy())
    return calls


def _post_json(handler_cls, path: str, payload: dict):
    from http.server import HTTPServer

    httpd = HTTPServer(('127.0.0.1', 0), handler_cls)
    port = httpd.server_address[1]
    worker = threading.Thread(target=httpd.handle_request, daemon=True)
    worker.start()

    conn = HTTPConnection('127.0.0.1', port, timeout=5)
    body = json.dumps(payload).encode('utf-8')
    conn.request(
        'POST',
        path,
        body=body,
        headers={
            'Content-Type': 'application/json',
            'Connection': 'close',
        },
    )
    resp = conn.getresponse()
    raw = resp.read()
    status = resp.status
    conn.close()

    worker.join(timeout=5)
    httpd.server_close()
    return status, json.loads(raw.decode('utf-8'))


def test_list_task_records_pages_backend_without_exceeding_limit(monkeypatch):
    import server as srv

    first_page = _filler_tasks(200)
    second_page = [_task('JJC-20260606-201')]
    calls = _install_backend_stubs(monkeypatch, srv, {0: first_page, 200: second_page})

    tasks = srv._list_task_records(cfg=DB_CFG, include_archived=False, sync_shadow=False)

    assert len(tasks) == 201
    assert tasks[-1]['id'] == 'JJC-20260606-201'
    assert calls == [
        {
            'path': '/api/tasks?limit=200&offset=0&archived=false',
            'limit': 200,
            'offset': 0,
            'archived': 'false',
        },
        {
            'path': '/api/tasks?limit=200&offset=200&archived=false',
            'limit': 200,
            'offset': 200,
            'archived': 'false',
        },
    ]


def test_handle_archive_task_db_mode_reaches_second_page(monkeypatch):
    import server as srv

    first_page = _filler_tasks(200)
    second_page = [_task('JJC-20260606-201', state='Done', archived=False)]
    _install_backend_stubs(monkeypatch, srv, {0: first_page, 200: second_page})

    patched = []
    monkeypatch.setattr(
        srv,
        '_patch_task_record',
        lambda task_id, patch_payload, cfg=None: patched.append((task_id, patch_payload, cfg)),
    )

    result = srv.handle_archive_task('', True, archive_all_done=True)

    assert result['ok'] is True
    assert result['count'] == 1
    assert patched == [
        (
            'JJC-20260606-201',
            {'fields': {'archived': True}, 'producer': 'dashboard-archive-all'},
            DB_CFG,
        )
    ]


def test_handle_scheduler_scan_db_mode_reaches_second_page(monkeypatch):
    import server as srv

    first_page = _filler_tasks(200, minutes_stale=0)
    second_page = [_task('JJC-20260606-201', state='Assigned', archived=False)]
    _install_backend_stubs(monkeypatch, srv, {0: first_page, 200: second_page})

    retries = []
    monkeypatch.setattr(
        srv,
        'handle_scheduler_retry',
        lambda task_id, reason: retries.append((task_id, reason)) or {'ok': True},
    )
    monkeypatch.setattr(srv, 'handle_scheduler_escalate', lambda *args, **kwargs: {'ok': False})
    monkeypatch.setattr(srv, 'handle_scheduler_rollback', lambda *args, **kwargs: {'ok': False})

    result = srv.handle_scheduler_scan(threshold_sec=60)

    assert result['ok'] is True
    assert result['count'] == 1
    assert result['actions'] == [
        {'taskId': 'JJC-20260606-201', 'action': 'retry', 'stalledSec': result['actions'][0]['stalledSec']}
    ]
    assert retries and retries[0][0] == 'JJC-20260606-201'
    assert '停滯' in retries[0][1]


def test_archive_task_route_db_mode_reaches_second_page(monkeypatch):
    import server as srv

    first_page = _filler_tasks(200)
    second_page = [_task('JJC-20260606-201', state='Done', archived=False)]
    _install_backend_stubs(monkeypatch, srv, {0: first_page, 200: second_page})

    patched = []
    monkeypatch.setattr(
        srv,
        '_patch_task_record',
        lambda task_id, patch_payload, cfg=None: patched.append((task_id, patch_payload, cfg)),
    )

    status, body = _post_json(
        srv.Handler,
        '/api/archive-task',
        {'archiveAllDone': True, 'archived': True},
    )

    assert status == 200
    assert body['ok'] is True
    assert body['count'] == 1
    assert patched == [
        (
            'JJC-20260606-201',
            {'fields': {'archived': True}, 'producer': 'dashboard-archive-all'},
            DB_CFG,
        )
    ]


def test_scheduler_scan_route_db_mode_reaches_second_page(monkeypatch):
    import server as srv

    first_page = _filler_tasks(200, minutes_stale=0)
    second_page = [_task('JJC-20260606-201', state='Assigned', archived=False)]
    _install_backend_stubs(monkeypatch, srv, {0: first_page, 200: second_page})

    retries = []
    monkeypatch.setattr(
        srv,
        'handle_scheduler_retry',
        lambda task_id, reason: retries.append((task_id, reason)) or {'ok': True},
    )
    monkeypatch.setattr(srv, 'handle_scheduler_escalate', lambda *args, **kwargs: {'ok': False})
    monkeypatch.setattr(srv, 'handle_scheduler_rollback', lambda *args, **kwargs: {'ok': False})

    status, body = _post_json(
        srv.Handler,
        '/api/scheduler-scan',
        {'thresholdSec': 60},
    )

    assert status == 200
    assert body['ok'] is True
    assert body['count'] == 1
    assert body['actions'] == [
        {'taskId': 'JJC-20260606-201', 'action': 'retry', 'stalledSec': body['actions'][0]['stalledSec']}
    ]
    assert retries and retries[0][0] == 'JJC-20260606-201'
    assert '停滯' in retries[0][1]


def test_transition_task_record_db_mode_uses_backend_new_state_field(monkeypatch):
    import server as srv

    captured = {}

    def fake_backend_api(method, path, body=None, cfg=None):
        captured['method'] = method
        captured['path'] = path
        captured['body'] = body
        captured['cfg'] = cfg
        return {'task_id': 'JJC-TRANS-001', 'state': 'Blocked'}

    monkeypatch.setattr(srv, '_backend_api_json', fake_backend_api)
    monkeypatch.setattr(srv, '_sync_shadow_from_backend', lambda cfg=None: {'tasks': []})
    monkeypatch.setattr(srv, '_load_task_source_mode', lambda: DB_CFG.copy())

    result = srv._transition_task_record('JJC-TRANS-001', 'Blocked', reason='皇上叫停', agent='皇上', cfg=DB_CFG)

    assert result['state'] == 'Blocked'
    assert captured == {
        'method': 'POST',
        'path': '/api/tasks/JJC-TRANS-001/transition',
        'body': {
            'new_state': 'Blocked',
            'agent': '皇上',
            'reason': '皇上叫停',
        },
        'cfg': DB_CFG,
    }


def test_create_task_record_db_mode_does_not_retransition_taizi(monkeypatch):
    import server as srv

    backend_calls = []
    patched_payloads = []

    def fake_backend_api(method, path, body=None, cfg=None):
        backend_calls.append((method, path, body, cfg))
        if path == '/api/tasks':
            return {
                'task_id': 'JJC-CREATE-001',
                'state': 'Taizi',
                'org': '太子',
                'todos': [],
            }
        raise AssertionError(f'unexpected backend call: {(method, path, body, cfg)}')

    def fake_patch(task_id, patch_payload, cfg=None):
        patched_payloads.append((task_id, patch_payload, cfg))
        return {'task_id': task_id, 'state': 'Taizi', 'org': '太子'}

    monkeypatch.setattr(srv, '_backend_api_json', fake_backend_api)
    monkeypatch.setattr(srv, '_patch_task_record', fake_patch)
    monkeypatch.setattr(srv, '_load_task_source_mode', lambda: DB_CFG.copy())

    result = srv._create_task_record(
        '測試任務',
        org='中書省',
        official='中書令',
        priority='normal',
        template_id='tpl-001',
        params={'x': 1},
        target_dept='工部',
        cfg=DB_CFG,
    )

    assert result['task_id'] == 'JJC-CREATE-001'
    assert backend_calls == [
        (
            'POST',
            '/api/tasks',
            {
                'title': '測試任務',
                'description': '下旨：測試任務',
                'priority': '中',
                'creator': 'dashboard',
                'assignee_org': '工部',
                'meta': {
                    'source': 'dashboard',
                    'official': '中書令',
                    'target_dept': '工部',
                    'template_id': 'tpl-001',
                    'template_params': {'x': 1},
                },
            },
            DB_CFG,
        )
    ]
    assert len(patched_payloads) == 1
    task_id, patch_payload, cfg = patched_payloads[0]
    assert task_id == 'JJC-CREATE-001'
    assert cfg == DB_CFG
    assert patch_payload['fields'] == {
        'org': '太子',
        'official': '中書令',
        'template_id': 'tpl-001',
        'template_params': {'x': 1},
        'target_dept': '工部',
        'review_round': 0,
    }
    assert patch_payload['producer'] == 'dashboard-create'
    assert patch_payload['progress_entry']['agent'] == 'emperor'
    assert patch_payload['progress_entry']['agentLabel'] == '皇上'
    assert patch_payload['progress_entry']['text'] == '任務創建'
    assert patch_payload['progress_entry']['state'] == 'Taizi'
    assert patch_payload['progress_entry']['org'] == '太子'
    assert patch_payload['progress_entry']['todos'] == []
    assert patch_payload['progress_entry']['at']
