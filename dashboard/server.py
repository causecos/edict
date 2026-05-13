#!/usr/bin/env python3
"""
三省六部 · 看板本地 API 服務器
Port: 7891 (可通過 --port 修改)

Endpoints:
  GET  /                       → dashboard.html
  GET  /api/live-status        → data/live_status.json
  GET  /api/agent-config       → data/agent_config.json
  POST /api/set-model          → {agentId, model}
  GET  /api/model-change-log   → data/model_change_log.json
  GET  /api/last-result        → data/last_model_change_result.json
"""
import json, pathlib, subprocess, sys, threading, argparse, datetime, logging, re, os, socket, shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# JWT 認證模塊
from auth import init as auth_init, requires_auth, extract_token, verify_token, \
    is_enabled as auth_enabled, is_configured as auth_configured, \
    setup_password, verify_password, create_token

# 引入文件鎖工具，確保與其他腳本並發安全
scripts_dir = str(pathlib.Path(__file__).parent.parent / 'scripts')
sys.path.insert(0, scripts_dir)
from file_lock import atomic_json_read, atomic_json_write, atomic_json_update
from utils import validate_url, read_json, now_iso, python_bin
from kanban_update import create_task_from_intent, set_task_state, record_task_flow
from court_discuss import (
    create_session as cd_create, advance_discussion as cd_advance,
    get_session as cd_get, conclude_session as cd_conclude,
    list_sessions as cd_list, destroy_session as cd_destroy,
    get_fate_event as cd_fate, OFFICIAL_PROFILES as CD_PROFILES,
)

log = logging.getLogger('server')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

CHANNELS_DIR = pathlib.Path(__file__).parent.parent / 'edict' / 'backend' / 'app' / 'channels'
if str(CHANNELS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(CHANNELS_DIR.parent))
from channels import get_channel, get_channel_info, CHANNELS as NOTIFICATION_CHANNELS

OCLAW_HOME = pathlib.Path.home() / '.openclaw'
MAX_REQUEST_BODY = 1 * 1024 * 1024  # 1 MB
ALLOWED_ORIGIN = None  # Set via --cors; None means restrict to localhost
_DASHBOARD_PORT = 7891  # Updated at startup from --port arg
_DEFAULT_ORIGINS = {
    'http://127.0.0.1:7891', 'http://localhost:7891',
    'http://127.0.0.1:5173', 'http://localhost:5173',  # Vite dev server
}
_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-\u4e00-\u9fff]+$')

BASE = pathlib.Path(__file__).parent
DIST = BASE / 'dist'          # React 構建產物 (npm run build)
DATA = BASE.parent / "data"
SCRIPTS = BASE.parent / 'scripts'
_ACTIVE_TASK_DATA_DIR = None
TASK_SOURCE_MODE_FILE = DATA / 'task_source_mode.json'
DEFAULT_TASK_SOURCE_MODE = {
    'mode': 'db',  # auto|json|db
    'backendApiBase': 'http://127.0.0.1:8000',
    'timeoutMs': 3000,
}

# 靜態資源 MIME 類型
_MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js':   'application/javascript; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif':  'image/gif',
    '.svg':  'image/svg+xml',
    '.ico':  'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf':  'font/ttf',
    '.map':  'application/json',
}


def cors_headers(h):
    req_origin = h.headers.get('Origin', '')
    if ALLOWED_ORIGIN:
        origin = ALLOWED_ORIGIN
    elif req_origin in _DEFAULT_ORIGINS:
        origin = req_origin
    else:
        origin = f'http://127.0.0.1:{_DASHBOARD_PORT}'
    h.send_header('Access-Control-Allow-Origin', origin)
    h.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    h.send_header('Access-Control-Allow-Headers', 'Content-Type')


def _iter_task_data_dirs():
    """返回可用的任務數據目錄候選（優先 workspace，其次本地 data）。"""
    dirs = [DATA]
    for p in sorted(OCLAW_HOME.glob('workspace-*/data')):
        if p.is_dir():
            dirs.append(p)
    return dirs


def _task_source_score(task_file: pathlib.Path):
    """給任務源打分：優先非 demo 任務，其次任務數，再按文件更新時間。"""
    try:
        tasks = atomic_json_read(task_file, [])
    except Exception:
        tasks = []
    if not isinstance(tasks, list):
        tasks = []
    non_demo = sum(1 for t in tasks if str((t or {}).get('id', '')) and not str((t or {}).get('id', '')).startswith('JJC-DEMO'))
    try:
        mtime = task_file.stat().st_mtime
    except Exception:
        mtime = 0
    return (1 if non_demo > 0 else 0, non_demo, len(tasks), mtime)


def get_task_data_dir():
    """自動選擇當前任務數據目錄，並緩存結果以保持一次服務期內穩定。"""
    global _ACTIVE_TASK_DATA_DIR
    if _ACTIVE_TASK_DATA_DIR and _ACTIVE_TASK_DATA_DIR.is_dir():
        return _ACTIVE_TASK_DATA_DIR
    best_dir = DATA
    best_score = (-1, -1, -1, -1)
    for d in _iter_task_data_dirs():
        tf = d / 'tasks_source.json'
        if not tf.exists():
            continue
        score = _task_source_score(tf)
        if score > best_score:
            best_score = score
            best_dir = d
    _ACTIVE_TASK_DATA_DIR = best_dir
    log.info(f'任務數據源: {_ACTIVE_TASK_DATA_DIR}')
    return _ACTIVE_TASK_DATA_DIR


def load_tasks():
    task_data_dir = get_task_data_dir()
    return atomic_json_read(task_data_dir / 'tasks_source.json', [])


def _normalize_task_source_mode(cfg):
    """清洗來源模式配置，防止配置污染。"""
    if not isinstance(cfg, dict):
        cfg = {}
    mode = str(cfg.get('mode') or DEFAULT_TASK_SOURCE_MODE['mode']).lower().strip()
    if mode not in ('auto', 'json', 'db'):
        mode = 'auto'

    base = str(cfg.get('backendApiBase') or DEFAULT_TASK_SOURCE_MODE['backendApiBase']).strip().rstrip('/')
    if not base.startswith('http://') and not base.startswith('https://'):
        base = DEFAULT_TASK_SOURCE_MODE['backendApiBase']

    try:
        timeout_ms = int(cfg.get('timeoutMs', DEFAULT_TASK_SOURCE_MODE['timeoutMs']))
    except Exception:
        timeout_ms = DEFAULT_TASK_SOURCE_MODE['timeoutMs']
    timeout_ms = max(500, min(timeout_ms, 15000))

    return {
        'mode': mode,
        'backendApiBase': base,
        'timeoutMs': timeout_ms,
    }


def _load_task_source_mode():
    """加載看板資料來源模式配置。"""
    cfg = atomic_json_read(TASK_SOURCE_MODE_FILE, DEFAULT_TASK_SOURCE_MODE.copy())
    return _normalize_task_source_mode(cfg)


def _save_task_source_mode(cfg):
    """保存看板資料來源模式配置。"""
    atomic_json_write(TASK_SOURCE_MODE_FILE, _normalize_task_source_mode(cfg))


def _backend_health(cfg=None):
    """檢測 backend API 健康。"""
    cfg = _normalize_task_source_mode(cfg or _load_task_source_mode())
    health_url = cfg['backendApiBase'] + '/health'
    try:
        req = Request(health_url, headers={'Accept': 'application/json'})
        with urlopen(req, timeout=max(1, cfg['timeoutMs'] / 1000)) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            payload = json.loads(raw) if raw else {}
            return {
                'ok': resp.status == 200,
                'statusCode': resp.status,
                'payload': payload,
                'url': health_url,
            }
    except Exception as e:
        return {
            'ok': False,
            'statusCode': 0,
            'error': str(e),
            'url': health_url,
        }


def _effective_source_mode(cfg, backend_ok=None):
    """根據 mode+backend 健康度推斷實際使用模式。"""
    mode = (cfg or {}).get('mode', 'auto')
    if mode != 'auto':
        return mode
    return 'db' if bool(backend_ok) else 'json'


def _fetch_backend_live_status(cfg):
    """從 edict backend 讀取 DB 路線 live-status。"""
    url = cfg['backendApiBase'] + '/api/tasks/live-status'
    req = Request(url, headers={'Accept': 'application/json'})
    with urlopen(req, timeout=max(1, cfg['timeoutMs'] / 1000)) as resp:
        raw = resp.read().decode('utf-8', errors='replace')
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            raise ValueError('backend live-status is not JSON object')
        return data


def _normalize_backend_live_status(payload):
    """把 backend /api/tasks/live-status 轉成 dashboard 可用結構。"""
    tasks = payload.get('tasks', {})
    completed = payload.get('completed_tasks', {})
    merged = []

    if isinstance(tasks, dict):
        merged.extend(tasks.values())
    elif isinstance(tasks, list):
        merged.extend(tasks)

    if isinstance(completed, dict):
        merged.extend(completed.values())
    elif isinstance(completed, list):
        merged.extend(completed)

    by_id = {}
    for t in merged:
        if not isinstance(t, dict):
            continue
        tid = str(t.get('id') or t.get('task_id') or '').strip()
        if not tid:
            continue
        if tid not in by_id:
            by_id[tid] = t

    def _ts(x):
        return x.get('updatedAt') or x.get('updated_at') or ''

    arr = sorted(by_id.values(), key=_ts, reverse=True)
    return {
        'tasks': arr,
        'lastSyncAt': payload.get('last_updated') or now_iso(),
        'source': 'db-api',
    }


def _live_status_from_json():
    """走舊 JSON 路線讀取 live_status。"""
    task_data_dir = get_task_data_dir()
    data = read_json(task_data_dir / 'live_status.json', {'tasks': []})
    if not isinstance(data, dict):
        data = {'tasks': []}
    data.setdefault('source', 'json')
    return data


def _inject_source_meta(payload, meta):
    """在 payload 注入來源元信息。"""
    if not isinstance(payload, dict):
        payload = {'tasks': []}
    payload['_sourceMeta'] = meta
    return payload


def get_live_status_with_mode():
    """按 mode 開關選擇資料來源：json / db / auto。

    規則：
    - db: 嚴格走 DB API，失敗直接回錯誤（不自動切 json）
    - auto: 也先檢查 DB，若失敗回錯誤並要求人工處置（保持一致性）
    - json: 僅在明確指定時使用
    """
    cfg = _load_task_source_mode()
    mode = cfg['mode']

    if mode == 'json':
        return _inject_source_meta(_live_status_from_json(), {
            'configured': mode,
            'effective': 'json',
            'backendApiBase': cfg['backendApiBase'],
            'fallback': None,
        })

    # db / auto 都先走 DB，失敗不自動降級
    try:
        db_payload = _fetch_backend_live_status(cfg)
        return _inject_source_meta(_normalize_backend_live_status(db_payload), {
            'configured': mode,
            'effective': 'db',
            'backendApiBase': cfg['backendApiBase'],
            'fallback': None,
        })
    except Exception as e:
        health = _backend_health(cfg)
        return {
            'tasks': [],
            'source': 'db-api',
            'error': f'db source failed: {e}',
            'action': '請先排查 DB/API 連通後再重試；不要直接切回 json。',
            '_sourceMeta': {
                'configured': mode,
                'effective': 'db',
                'backendApiBase': cfg['backendApiBase'],
                'fallback': None,
                'backendHealth': health,
            }
        }


def save_tasks(tasks):
    task_data_dir = get_task_data_dir()
    atomic_json_write(task_data_dir / 'tasks_source.json', tasks)
    _trigger_refresh()


def _trigger_refresh():
    """Trigger live data refresh in background."""
    task_data_dir = get_task_data_dir()
    script = task_data_dir.parent / 'scripts' / 'refresh_live_data.py'
    if not script.exists():
        script = SCRIPTS / 'refresh_live_data.py'

    def _refresh():
        try:
            subprocess.run([python_bin(), str(script)], timeout=30)
        except Exception as e:
            log.warning(f'refresh_live_data.py 觸發失敗: {e}')
    threading.Thread(target=_refresh, daemon=True).start()


def modify_tasks(modifier):
    """Atomically read-modify-write the tasks file.

    ``modifier(tasks)`` receives the current task list, mutates it in place
    (or returns a new list), and the result is persisted while the file lock
    is held.  This avoids the TOCTOU race inherent in separate
    ``load_tasks()`` / ``save_tasks()`` calls when background threads
    (dispatch callbacks, periodic scanner) and the HTTP handler mutate tasks
    concurrently.
    """
    task_data_dir = get_task_data_dir()
    path = task_data_dir / 'tasks_source.json'
    atomic_json_update(path, modifier, default=[])
    _trigger_refresh()


def modify_task(task_id, updater):
    """Atomically update a single task identified by *task_id*.

    ``updater(task)`` receives the task dict and should mutate it in place.
    Returns ``True`` if the task was found and updated, ``False`` otherwise.
    """
    found = [False]

    def _modifier(tasks):
        task = next((t for t in tasks if t.get('id') == task_id), None)
        if task is None:
            return tasks
        updater(task)
        task['updatedAt'] = now_iso()
        found[0] = True
        return tasks

    modify_tasks(_modifier)
    return found[0]


def handle_task_action(task_id, action, reason):
    """Stop/cancel/resume a task from the dashboard."""
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}

    old_state = task.get('state', '')
    _ensure_scheduler(task)
    _scheduler_snapshot(task, f'task-action-before-{action}')

    if action == 'stop':
        new_state = 'Blocked'
        now_text = f'⏸️ 已暫停：{reason}'
        flow_remark = f'⏸️ 叫停：{reason}'
    elif action == 'cancel':
        new_state = 'Cancelled'
        now_text = f'🚫 已取消：{reason}'
        flow_remark = f'🚫 取消：{reason}'
    elif action == 'resume':
        # Resume to previous active state or Doing
        new_state = task.get('_prev_state', 'Doing')
        now_text = '▶️ 已恢復執行'
        flow_remark = f'▶️ 恢復：{reason}'

    # 統一狀態/流轉寫入入口
    set_task_state(task_id, new_state, now_text)
    record_task_flow(task_id, '皇上', task.get('org', ''), flow_remark)

    # Dashboard 擴展欄位
    tasks2 = load_tasks()
    task2 = next((t for t in tasks2 if t.get('id') == task_id), None)
    if not task2:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}

    if action in ('stop', 'cancel'):
        task2['_prev_state'] = old_state  # Save for resume
        task2['block'] = reason or ('皇上叫停' if action == 'stop' else '皇上取消')
    elif action == 'resume':
        task2['block'] = '無'

    if action == 'resume':
        _scheduler_mark_progress(task2, f'恢復到 {task2.get("state", "Doing")}')
    else:
        _scheduler_add_flow(task2, f'皇上{action}：{reason or "無"}')

    task2['updatedAt'] = now_iso()
    save_tasks(tasks2)

    label = {'stop': '已叫停', 'cancel': '已取消', 'resume': '已恢復'}[action]
    return {'ok': True, 'message': f'{task_id} {label}'}


def handle_archive_task(task_id, archived, archive_all_done=False):
    """Archive or unarchive a task, or batch-archive all Done/Cancelled tasks."""
    tasks = load_tasks()
    if archive_all_done:
        count = 0
        for t in tasks:
            if t.get('state') in ('Done', 'Cancelled') and not t.get('archived'):
                t['archived'] = True
                t['archivedAt'] = now_iso()
                count += 1
        save_tasks(tasks)
        return {'ok': True, 'message': f'{count} 道旨意已歸檔', 'count': count}
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}
    task['archived'] = archived
    if archived:
        task['archivedAt'] = now_iso()
    else:
        task.pop('archivedAt', None)
    task['updatedAt'] = now_iso()
    save_tasks(tasks)
    label = '已歸檔' if archived else '已取消歸檔'
    return {'ok': True, 'message': f'{task_id} {label}'}


def update_task_todos(task_id, todos):
    """Update the todos list for a task."""
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}

    task['todos'] = todos
    task['updatedAt'] = now_iso()
    save_tasks(tasks)
    return {'ok': True, 'message': f'{task_id} todos 已更新'}


def read_skill_content(agent_id, skill_name):
    """Read SKILL.md content for a specific skill."""
    # 輸入校驗：防止路徑遍歷
    if not _SAFE_NAME_RE.match(agent_id) or not _SAFE_NAME_RE.match(skill_name):
        return {'ok': False, 'error': '參數含非法字符'}
    cfg = read_json(DATA / 'agent_config.json', {})
    agents = cfg.get('agents', [])
    ag = next((a for a in agents if a.get('id') == agent_id), None)
    if not ag:
        return {'ok': False, 'error': f'Agent {agent_id} 不存在'}
    sk = next((s for s in ag.get('skills', []) if s.get('name') == skill_name), None)
    if not sk:
        return {'ok': False, 'error': f'技能 {skill_name} 不存在'}
    skill_path = pathlib.Path(sk.get('path', '')).resolve()
    # 路徑遍歷保護：確保路徑在 OCLAW_HOME 或項目目錄下
    allowed_roots = (OCLAW_HOME.resolve(), BASE.parent.resolve())
    if not any(str(skill_path).startswith(str(root)) for root in allowed_roots):
        return {'ok': False, 'error': '路径不在允许的目录范围内'}
    if not skill_path.exists():
        return {'ok': True, 'name': skill_name, 'agent': agent_id, 'content': '(SKILL.md 文件不存在)', 'path': str(skill_path)}
    try:
        content = skill_path.read_text()
        return {'ok': True, 'name': skill_name, 'agent': agent_id, 'content': content, 'path': str(skill_path)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def add_skill_to_agent(agent_id, skill_name, description, trigger=''):
    """Create a new skill for an agent with a standardised SKILL.md template."""
    if not _SAFE_NAME_RE.match(skill_name):
        return {'ok': False, 'error': f'skill_name 含非法字符: {skill_name}'}
    if not _SAFE_NAME_RE.match(agent_id):
        return {'ok': False, 'error': f'agentId 含非法字符: {agent_id}'}
    workspace = OCLAW_HOME / f'workspace-{agent_id}' / 'skills' / skill_name
    workspace.mkdir(parents=True, exist_ok=True)
    skill_md = workspace / 'SKILL.md'
    desc_line = description or skill_name
    trigger_section = f'\n## 觸發條件\n{trigger}\n' if trigger else ''
    template = (f'---\n'
                f'name: {skill_name}\n'
                f'description: {desc_line}\n'
                f'---\n\n'
                f'# {skill_name}\n\n'
                f'{desc_line}\n'
                f'{trigger_section}\n'
                f'## 輸入\n\n'
                f'<!-- 說明此技能接收什麼輸入 -->\n\n'
                f'## 處理流程\n\n'
                f'1. 步驟一\n'
                f'2. 步驟二\n\n'
                f'## 輸出規範\n\n'
                f'<!-- 說明產出物格式與交付要求 -->\n\n'
                f'## 注意事項\n\n'
                f'- (在此補充約束、限制或特殊規則)\n')
    skill_md.write_text(template)
    # Re-sync agent config
    try:
        subprocess.run([python_bin(), str(SCRIPTS / 'sync_agent_config.py')], timeout=10)
    except Exception:
        pass
    return {'ok': True, 'message': f'技能 {skill_name} 已添加到 {agent_id}', 'path': str(skill_md)}


def add_remote_skill(agent_id, skill_name, source_url, description=''):
    """從遠程 URL 或本地路徑爲 Agent 添加 skill SKILL.md 文件。
    
    支持的源：
    - HTTPS URLs: https://raw.githubusercontent.com/...
    - 本地路徑: /path/to/SKILL.md 或 file:///path/to/SKILL.md
    """
    # 輸入校驗
    if not _SAFE_NAME_RE.match(agent_id):
        return {'ok': False, 'error': f'agentId 含非法字符: {agent_id}'}
    if not _SAFE_NAME_RE.match(skill_name):
        return {'ok': False, 'error': f'skillName 含非法字符: {skill_name}'}
    if not source_url or not isinstance(source_url, str):
        return {'ok': False, 'error': 'sourceUrl 必須是有效的字符串'}
    
    source_url = source_url.strip()
    
    # 檢查 Agent 是否存在
    cfg = read_json(DATA / 'agent_config.json', {})
    agents = cfg.get('agents', [])
    if not any(a.get('id') == agent_id for a in agents):
        return {'ok': False, 'error': f'Agent {agent_id} 不存在'}
    
    # 下載或讀取文件內容
    try:
        if source_url.startswith('http://') or source_url.startswith('https://'):
            # HTTPS URL 校驗
            if not validate_url(source_url, allowed_schemes=('https',)):
                return {'ok': False, 'error': 'URL 無效或不安全（僅支持 HTTPS）'}
            
            # 從 URL 下載，帶超時保護
            req = Request(source_url, headers={'User-Agent': 'OpenClaw-SkillManager/1.0'})
            try:
                resp = urlopen(req, timeout=10)
                content = resp.read(10 * 1024 * 1024).decode('utf-8')  # 最多 10MB
                if len(content) > 10 * 1024 * 1024:
                    return {'ok': False, 'error': '文件過大（最大 10MB）'}
            except Exception as e:
                return {'ok': False, 'error': f'URL 無法訪問: {str(e)[:100]}'}
        
        elif source_url.startswith('file://'):
            # file:// URL 格式
            local_path = pathlib.Path(source_url[7:]).resolve()
            if not local_path.exists():
                return {'ok': False, 'error': f'本地文件不存在: {local_path}'}
            # 路徑遍歷防護：與本地路徑分支一致，確保在允許範圍內
            allowed_roots = (OCLAW_HOME.resolve(), BASE.parent.resolve())
            if not any(str(local_path).startswith(str(root)) for root in allowed_roots):
                return {'ok': False, 'error': '路径不在允许的目录范围内'}
            content = local_path.read_text()
        
        elif source_url.startswith('/') or source_url.startswith('.'):
            # 本地絕對或相對路徑
            local_path = pathlib.Path(source_url).resolve()
            if not local_path.exists():
                return {'ok': False, 'error': f'本地文件不存在: {local_path}'}
            # 路徑遍歷防護
            allowed_roots = (OCLAW_HOME.resolve(), BASE.parent.resolve())
            if not any(str(local_path).startswith(str(root)) for root in allowed_roots):
                return {'ok': False, 'error': '路径不在允许的目录范围内'}
            content = local_path.read_text()
        
        else:
            return {'ok': False, 'error': '不支持的 URL 格式（僅支持 https://, file://, 或本地路徑）'}
    except Exception as e:
        return {'ok': False, 'error': f'文件讀取失敗: {str(e)[:100]}'}
    
    # 基礎驗證：檢查是否爲 Markdown 且包含 YAML frontmatter
    if not content.startswith('---'):
        return {'ok': False, 'error': '文件格式無效（缺少 YAML frontmatter）'}
    
    # 驗證 frontmatter 結構（先做字符串檢查，再嘗試 YAML 解析）
    parts = content.split('---', 2)
    if len(parts) < 3:
        return {'ok': False, 'error': '文件格式無效（YAML frontmatter 結構錯誤）'}
    if 'name:' not in content[:500]:
        return {'ok': False, 'error': '文件格式無效：frontmatter 缺少 name 字段'}
    try:
        import yaml
        yaml.safe_load(parts[1])  # 嚴格校驗 YAML 語法
    except ImportError:
        pass  # PyYAML 未安裝，跳過嚴格驗證，字符串檢查已通過
    except Exception as e:
        return {'ok': False, 'error': f'YAML 格式無效: {str(e)[:100]}'}
    
    # 創建本地目錄
    workspace = OCLAW_HOME / f'workspace-{agent_id}' / 'skills' / skill_name
    workspace.mkdir(parents=True, exist_ok=True)
    skill_md = workspace / 'SKILL.md'
    
    # 寫入 SKILL.md
    skill_md.write_text(content)
    
    # 保存源信息到 .source.json
    source_info = {
        'skillName': skill_name,
        'sourceUrl': source_url,
        'description': description,
        'addedAt': now_iso(),
        'lastUpdated': now_iso(),
        'checksum': _compute_checksum(content),
        'status': 'valid',
    }
    source_json = workspace / '.source.json'
    source_json.write_text(json.dumps(source_info, ensure_ascii=False, indent=2))
    
    # Re-sync agent config
    try:
        subprocess.run([python_bin(), str(SCRIPTS / 'sync_agent_config.py')], timeout=10)
    except Exception:
        pass
    
    return {
        'ok': True,
        'message': f'技能 {skill_name} 已從遠程源添加到 {agent_id}',
        'skillName': skill_name,
        'agentId': agent_id,
        'source': source_url,
        'localPath': str(skill_md),
        'size': len(content),
        'addedAt': now_iso(),
    }


def get_remote_skills_list():
    """列表所有已添加的遠程 skills 及其源信息"""
    remote_skills = []
    
    # 遍歷所有 workspace
    for ws_dir in OCLAW_HOME.glob('workspace-*'):
        agent_id = ws_dir.name.replace('workspace-', '')
        skills_dir = ws_dir / 'skills'
        if not skills_dir.exists():
            continue
        
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_name = skill_dir.name
            source_json = skill_dir / '.source.json'
            skill_md = skill_dir / 'SKILL.md'
            
            if not source_json.exists():
                # 本地創建的 skill，跳過
                continue
            
            try:
                source_info = json.loads(source_json.read_text())
                # 檢查 SKILL.md 是否存在
                status = 'valid' if skill_md.exists() else 'not-found'
                remote_skills.append({
                    'skillName': skill_name,
                    'agentId': agent_id,
                    'sourceUrl': source_info.get('sourceUrl', ''),
                    'description': source_info.get('description', ''),
                    'localPath': str(skill_md),
                    'addedAt': source_info.get('addedAt', ''),
                    'lastUpdated': source_info.get('lastUpdated', ''),
                    'status': status,
                })
            except Exception:
                pass
    
    return {
        'ok': True,
        'remoteSkills': remote_skills,
        'count': len(remote_skills),
        'listedAt': now_iso(),
    }


def update_remote_skill(agent_id, skill_name):
    """更新已添加的遠程 skill 爲最新版本（重新從源 URL 下載）"""
    if not _SAFE_NAME_RE.match(agent_id):
        return {'ok': False, 'error': f'agentId 含非法字符: {agent_id}'}
    if not _SAFE_NAME_RE.match(skill_name):
        return {'ok': False, 'error': f'skillName 含非法字符: {skill_name}'}
    
    workspace = OCLAW_HOME / f'workspace-{agent_id}' / 'skills' / skill_name
    source_json = workspace / '.source.json'
    skill_md = workspace / 'SKILL.md'
    
    if not source_json.exists():
        return {'ok': False, 'error': f'技能 {skill_name} 不是遠程 skill（無 .source.json）'}
    
    try:
        source_info = json.loads(source_json.read_text())
        source_url = source_info.get('sourceUrl', '')
        if not source_url:
            return {'ok': False, 'error': '源 URL 不存在'}
        
        # 重新下載
        result = add_remote_skill(agent_id, skill_name, source_url, 
                                  source_info.get('description', ''))
        if result['ok']:
            result['message'] = f'技能已更新'
            source_info_updated = json.loads(source_json.read_text())
            result['newVersion'] = source_info_updated.get('checksum', 'unknown')
        return result
    except Exception as e:
        return {'ok': False, 'error': f'更新失敗: {str(e)[:100]}'}


def remove_remote_skill(agent_id, skill_name):
    """移除已添加的遠程 skill"""
    if not _SAFE_NAME_RE.match(agent_id):
        return {'ok': False, 'error': f'agentId 含非法字符: {agent_id}'}
    if not _SAFE_NAME_RE.match(skill_name):
        return {'ok': False, 'error': f'skillName 含非法字符: {skill_name}'}
    
    workspace = OCLAW_HOME / f'workspace-{agent_id}' / 'skills' / skill_name
    if not workspace.exists():
        return {'ok': False, 'error': f'技能不存在: {skill_name}'}
    
    # 檢查是否爲遠程 skill
    source_json = workspace / '.source.json'
    if not source_json.exists():
        return {'ok': False, 'error': f'技能 {skill_name} 不是遠程 skill，無法通過此 API 移除'}
    
    try:
        # 刪除整個 skill 目錄
        import shutil
        shutil.rmtree(workspace)
        
        # Re-sync agent config
        try:
            subprocess.run([python_bin(), str(SCRIPTS / 'sync_agent_config.py')], timeout=10)
        except Exception:
            pass
        
        return {'ok': True, 'message': f'技能 {skill_name} 已從 {agent_id} 移除'}
    except Exception as e:
        return {'ok': False, 'error': f'移除失敗: {str(e)[:100]}'}


def _compute_checksum(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def migrate_notification_config():
    """自動遷移舊配置 (feishu_webhook) 到新結構 (notification)"""
    cfg_path = DATA / 'morning_brief_config.json'
    cfg = read_json(cfg_path, {})
    if not cfg:
        return
    if 'notification' in cfg:
        return
    if 'feishu_webhook' not in cfg:
        return
    webhook = cfg.get('feishu_webhook', '').strip()
    cfg['notification'] = {
        'enabled': bool(webhook),
        'channel': 'feishu',
        'webhook': webhook
    }
    try:
        atomic_json_write(cfg_path, cfg)
        log.info('已自動遷移 feishu_webhook 到 notification 配置')
    except Exception as e:
        log.warning(f'遷移配置失敗: {e}')


def push_notification():
    """通用消息推送 (支持多渠道)"""
    cfg = read_json(DATA / 'morning_brief_config.json', {})
    notification = cfg.get('notification', {})
    if not notification and cfg.get('feishu_webhook'):
        notification = {'enabled': True, 'channel': 'feishu', 'webhook': cfg['feishu_webhook']}
    if not notification.get('enabled', True):
        return
    channel_type = notification.get('channel', 'feishu')
    webhook = notification.get('webhook', '').strip()
    if not webhook:
        return
    channel_cls = get_channel(channel_type)
    if not channel_cls:
        log.warning(f'未知的通知渠道: {channel_type}')
        return
    if not channel_cls.validate_webhook(webhook):
        log.warning(f'{channel_cls.label} Webhook URL 不合法: {webhook}')
        return
    brief = read_json(DATA / 'morning_brief.json', {})
    date_str = brief.get('date', '')
    total = sum(len(v) for v in (brief.get('categories') or {}).values())
    if not total:
        return
    cat_lines = []
    for cat, items in (brief.get('categories') or {}).items():
        if items:
            cat_lines.append(f'  {cat}: {len(items)} 條')
    summary = '\n'.join(cat_lines)
    date_fmt = date_str[:4] + '年' + date_str[4:6] + '月' + date_str[6:] + '日' if len(date_str) == 8 else date_str
    title = f'📰 天下要聞 · {date_fmt}'
    content = f'共 **{total}** 條要聞已更新\n{summary}'
    url = f'http://127.0.0.1:{_DASHBOARD_PORT}'
    success = channel_cls.send(webhook, title, content, url)
    print(f'[{channel_cls.label}] 推送{"成功" if success else "失敗"}')


def push_to_feishu():
    """Push morning brief link to Feishu via webhook. (已棄用，使用 push_notification)"""
    push_notification()


# 旨意標題最低要求
_MIN_TITLE_LEN = 6
_JUNK_TITLES = {
    '?', '？', '好', '好的', '是', '否', '不', '不是', '對', '了解', '收到',
    '嗯', '哦', '知道了', '開啓了麼', '可以', '不行', '行', 'ok', 'yes', 'no',
    '你去開啓', '測試', '試試', '看看',
}


def handle_create_task(title, org='中書省', official='中書令', priority='normal', template_id='', params=None, target_dept=''):
    """從看板創建新任務（聖旨模板下旨）。

    統一走 scripts/kanban_update.py 的共用建單函式，避免 Dashboard 與 CLI 邏輯分叉。
    """
    if not title or not title.strip():
        return {'ok': False, 'error': '任務標題不能爲空'}

    title = title.strip()
    today = datetime.datetime.now().strftime('%Y%m%d')
    tasks = load_tasks()
    today_ids = [t['id'] for t in tasks if t.get('id', '').startswith(f'JJC-{today}-')]
    seq = 1
    if today_ids:
        nums = [int(tid.split('-')[-1]) for tid in today_ids if tid.split('-')[-1].isdigit()]
        seq = max(nums) + 1 if nums else 1
    task_id = f'JJC-{today}-{seq:03d}'

    # 統一建單入口（含標題清洗/校驗、初始化、派發）
    create_task_from_intent(
        task_id=task_id,
        title=title,
        state='Taizi',
        org='太子',
        official=official,
        remark=f'下旨：{title}',
    )

    # 補充 Dashboard 額外字段（模板/優先級/目標部門）
    def _patch_extra(tsk):
        if tsk.get('id') != task_id:
            return tsk
        tsk['priority'] = priority
        tsk['templateId'] = template_id
        tsk['templateParams'] = params or {}
        if target_dept:
            tsk['targetDept'] = target_dept
        _ensure_scheduler(tsk)
        _scheduler_snapshot(tsk, 'create-task-initial')
        _scheduler_mark_progress(tsk, '任務創建')
        tsk['updatedAt'] = now_iso()
        return tsk

    def _modifier(all_tasks):
        return [_patch_extra(t) for t in all_tasks]

    atomic_json_update(get_task_data_dir() / 'tasks_source.json', _modifier, [])

    return {'ok': True, 'taskId': task_id, 'message': f'旨意 {task_id} 已下達，正在派發給太子'}


def _todo_progress(task):
    todos = task.get('todos') or []
    total = len(todos)
    completed = sum(1 for td in todos if td.get('status') == 'completed')
    return completed, total


def handle_review_action(task_id, action, comment=''):
    """門下省御批：準奏/封駁。"""
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}
    if task.get('state') not in ('Review', 'Menxia'):
        return {'ok': False, 'error': f'任務 {task_id} 當前狀態爲 {task.get("state")}，無法御批'}

    _ensure_scheduler(task)
    _scheduler_snapshot(task, f'review-before-{action}')

    if action == 'approve':
        if task['state'] == 'Menxia':
            new_state = 'Assigned'
            now_text = '門下省準奏，移交尚書省派發'
            remark = f'✅ 準奏：{comment or "門下省審議通過"}'
            to_dept = '尚書省'
        else:  # Review
            completed, total = _todo_progress(task)
            if total > 0 and completed < total:
                return {'ok': False, 'error': f'子任務尚未全部完成（{completed}/{total}），不能直接准奏完结'}
            new_state = 'Done'
            now_text = '御批通過，任務完成'
            remark = f'✅ 御批准奏：{comment or "審查通過"}'
            to_dept = '皇上'
    elif action == 'reject':
        round_num = (task.get('review_round') or 0) + 1
        task['review_round'] = round_num
        now_text = f'封駁退回中書省修訂（第{round_num}輪）'
        new_state = 'Zhongshu'
        remark = f'🚫 封駁：{comment or "需要修改"}'
        to_dept = '中書省'
    else:
        return {'ok': False, 'error': f'未知操作: {action}'}

    # 在當前任務集合中直接寫入（便於測試與看板一致性）
    task['state'] = new_state
    task['now'] = now_text
    task['org'] = '完成' if new_state == 'Done' else to_dept
    task.setdefault('flow_log', []).append({
        'at': now_iso(),
        'from': '門下省' if new_state != 'Done' else '皇上',
        'to': to_dept,
        'remark': remark,
    })
    if action == 'reject':
        task['review_round'] = round_num
    _ensure_scheduler(task)
    _scheduler_mark_progress(task, f'審議動作 {action} -> {new_state}')
    task['updatedAt'] = now_iso()
    save_tasks(tasks)

    # 兼容生產環境：額外觸發一次統一派發（失敗不阻塞主流程）
    try:
        dispatch_for_state(task_id, task, new_state, 'review-action')
    except Exception:
        pass

    label = '已準奏' if action == 'approve' else '已封駁'
    dispatched = ' (已自動派發 Agent)' if new_state != 'Done' else ''
    return {'ok': True, 'message': f'{task_id} {label}{dispatched}'}


# ══ Agent 在線狀態檢測 ══

_AGENT_DEPTS = [
    {'id':'taizi',   'label':'太子',  'emoji':'🤴', 'role':'太子',     'rank':'儲君'},
    {'id':'zhongshu','label':'中書省','emoji':'📜', 'role':'中書令',   'rank':'正一品'},
    {'id':'menxia',  'label':'門下省','emoji':'🔍', 'role':'侍中',     'rank':'正一品'},
    {'id':'shangshu','label':'尚書省','emoji':'📮', 'role':'尚書令',   'rank':'正一品'},
    {'id':'hubu',    'label':'戶部',  'emoji':'💰', 'role':'戶部尚書', 'rank':'正二品'},
    {'id':'libu',    'label':'禮部',  'emoji':'📝', 'role':'禮部尚書', 'rank':'正二品'},
    {'id':'bingbu',  'label':'兵部',  'emoji':'⚔️', 'role':'兵部尚書', 'rank':'正二品'},
    {'id':'xingbu',  'label':'刑部',  'emoji':'⚖️', 'role':'刑部尚書', 'rank':'正二品'},
    {'id':'gongbu',  'label':'工部',  'emoji':'🔧', 'role':'工部尚書', 'rank':'正二品'},
    {'id':'libu_hr', 'label':'吏部',  'emoji':'👔', 'role':'吏部尚書', 'rank':'正二品'},
    {'id':'zaochao', 'label':'欽天監','emoji':'📰', 'role':'朝報官',   'rank':'正三品'},
]


def _check_gateway_alive():
    """檢測 Gateway 是否在運行。

    Windows 上不要依賴 pgrep；優先通過本地端口探測判斷。
    """
    if _check_gateway_probe():
        return True
    try:
        if os.name == 'nt':
            with socket.create_connection(('127.0.0.1', 18789), timeout=2):
                return True
            return False
        result = subprocess.run(['pgrep', '-f', 'openclaw-gateway'],
                                capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _check_gateway_probe():
    """通過 HTTP probe 檢測 Gateway 是否響應。"""
    for url in ('http://127.0.0.1:18789/', 'http://127.0.0.1:18789/healthz'):
        try:
            from urllib.request import urlopen
            resp = urlopen(url, timeout=3)
            if 200 <= resp.status < 500:
                return True
        except Exception:
            continue
    return False


def _get_agent_session_status(agent_id):
    """讀取 Agent 的 sessions.json 獲取活躍狀態。
    返回: (last_active_ts_ms, session_count, is_busy)
    """
    sessions_file = OCLAW_HOME / 'agents' / agent_id / 'sessions' / 'sessions.json'
    if not sessions_file.exists():
        return 0, 0, False
    try:
        data = json.loads(sessions_file.read_text())
        if not isinstance(data, dict):
            return 0, 0, False
        session_count = len(data)
        last_ts = 0
        for v in data.values():
            ts = v.get('updatedAt', 0)
            if isinstance(ts, (int, float)) and ts > last_ts:
                last_ts = ts
        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        age_ms = now_ms - last_ts if last_ts else 9999999999
        is_busy = age_ms <= 2 * 60 * 1000  # 2分鐘內視爲正在工作
        return last_ts, session_count, is_busy
    except Exception:
        return 0, 0, False


def _check_agent_process(agent_id):
    """檢測是否有該 Agent 的 openclaw-agent 進程正在運行。"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', f'openclaw.*--agent.*{agent_id}'],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_agent_workspace(agent_id):
    """檢查 Agent 工作空間是否存在。"""
    ws = OCLAW_HOME / f'workspace-{agent_id}'
    return ws.is_dir()


def get_agents_status():
    """獲取所有 Agent 的在線狀態。
    返回各 Agent 的:
    - status: 'running' | 'idle' | 'offline' | 'unconfigured'
    - lastActive: 最後活躍時間
    - sessions: 會話數
    - hasWorkspace: 工作空間是否存在
    - processAlive: 是否有進程在運行
    """
    gateway_alive = _check_gateway_alive()
    gateway_probe = _check_gateway_probe() if gateway_alive else False

    agents = []
    seen_ids = set()
    for dept in _AGENT_DEPTS:
        aid = dept['id']
        if aid in seen_ids:
            continue
        seen_ids.add(aid)

        has_workspace = _check_agent_workspace(aid)
        last_ts, sess_count, is_busy = _get_agent_session_status(aid)
        process_alive = _check_agent_process(aid)

        # 狀態判定
        if not has_workspace:
            status = 'unconfigured'
            status_label = '❌ 未配置'
        elif not gateway_alive:
            status = 'offline'
            status_label = '🔴 Gateway 離線'
        elif process_alive or is_busy:
            status = 'running'
            status_label = '🟢 運行中'
        elif last_ts > 0:
            now_ms = int(datetime.datetime.now().timestamp() * 1000)
            age_ms = now_ms - last_ts
            if age_ms <= 10 * 60 * 1000:  # 10分鐘內
                status = 'idle'
                status_label = '🟡 待命'
            elif age_ms <= 3600 * 1000:  # 1小時內
                status = 'idle'
                status_label = '⚪ 空閒'
            else:
                status = 'idle'
                status_label = '⚪ 休眠'
        else:
            status = 'idle'
            status_label = '⚪ 無記錄'

        # 格式化最後活躍時間
        last_active_str = None
        if last_ts > 0:
            try:
                last_active_str = datetime.datetime.fromtimestamp(
                    last_ts / 1000
                ).strftime('%m-%d %H:%M')
            except Exception:
                pass

        agents.append({
            'id': aid,
            'label': dept['label'],
            'emoji': dept['emoji'],
            'role': dept['role'],
            'status': status,
            'statusLabel': status_label,
            'lastActive': last_active_str,
            'lastActiveTs': last_ts,
            'sessions': sess_count,
            'hasWorkspace': has_workspace,
            'processAlive': process_alive,
        })

    return {
        'ok': True,
        'gateway': {
            'alive': gateway_alive,
            'probe': gateway_probe,
            'status': '🟢 運行中' if gateway_probe else ('🟡 進程在但無響應' if gateway_alive else '🔴 未啓動'),
        },
        'agents': agents,
        'checkedAt': now_iso(),
    }


def wake_agent(agent_id, message=''):
    """喚醒指定 Agent，發送一條心跳/喚醒消息。"""
    if not _SAFE_NAME_RE.match(agent_id):
        return {'ok': False, 'error': f'agent_id 非法: {agent_id}'}
    if not _check_agent_workspace(agent_id):
        return {'ok': False, 'error': f'{agent_id} 工作空間不存在，請先配置'}
    if not _check_gateway_alive():
        return {'ok': False, 'error': 'Gateway 未啓動，請先運行 openclaw gateway start'}

    # agent_id 直接作爲 runtime_id（openclaw agents list 中的註冊名）
    runtime_id = agent_id
    msg = message or f'🔔 系統心跳檢測 — 請回復 OK 確認在線。當前時間: {now_iso()}'

    def do_wake():
        try:
            cmd = ['openclaw', 'agent', '--agent', runtime_id, '-m', msg, '--timeout', '120']
            log.info(f'🔔 喚醒 {agent_id}...')
            # 帶重試（最多2次）
            for attempt in range(1, 3):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=130)
                if result.returncode == 0:
                    log.info(f'✅ {agent_id} 已喚醒')
                    return
                err_msg = result.stderr[:200] if result.stderr else result.stdout[:200]
                log.warning(f'⚠️ {agent_id} 喚醒失敗(第{attempt}次): {err_msg}')
                if attempt < 2:
                    import time
                    time.sleep(5)
            log.error(f'❌ {agent_id} 喚醒最終失敗')
        except subprocess.TimeoutExpired:
            log.error(f'❌ {agent_id} 喚醒超時(130s)')
        except Exception as e:
            log.warning(f'⚠️ {agent_id} 喚醒異常: {e}')
    threading.Thread(target=do_wake, daemon=True).start()

    return {'ok': True, 'message': f'{agent_id} 喚醒指令已發出，約10-30秒後生效'}


# ══ Agent 實時活動讀取 ══

# 狀態 → agent_id 映射
_STATE_AGENT_MAP = {
    'Taizi': 'taizi',
    'Zhongshu': 'zhongshu',
    'Menxia': 'menxia',
    'Assigned': 'shangshu',
    'Doing': None,         # 六部，需從 org 推斷
    'Review': 'shangshu',
    'Next': None,          # 待執行，從 org 推斷
    'Pending': 'zhongshu', # 待處理，默認中書省
}
_ORG_AGENT_MAP = {
    '禮部': 'libu', '戶部': 'hubu', '兵部': 'bingbu',
    '刑部': 'xingbu', '工部': 'gongbu', '吏部': 'libu_hr',
    '中書省': 'zhongshu', '門下省': 'menxia', '尚書省': 'shangshu',
}

_TERMINAL_STATES = {'Done', 'Cancelled'}


def _parse_iso(ts):
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except Exception:
        return None


def _ensure_scheduler(task):
    sched = task.setdefault('_scheduler', {})
    if not isinstance(sched, dict):
        sched = {}
        task['_scheduler'] = sched
    sched.setdefault('enabled', True)
    sched.setdefault('stallThresholdSec', 600)
    sched.setdefault('maxRetry', 2)
    sched.setdefault('retryCount', 0)
    sched.setdefault('escalationLevel', 0)
    sched.setdefault('autoRollback', True)
    if not sched.get('lastProgressAt'):
        sched['lastProgressAt'] = task.get('updatedAt') or now_iso()
    if 'stallSince' not in sched:
        sched['stallSince'] = None
    if 'lastDispatchStatus' not in sched:
        sched['lastDispatchStatus'] = 'idle'
    if 'snapshot' not in sched:
        sched['snapshot'] = {
            'state': task.get('state', ''),
            'org': task.get('org', ''),
            'now': task.get('now', ''),
            'savedAt': now_iso(),
            'note': 'init',
        }
    return sched


def _scheduler_add_flow(task, remark, to=''):
    task.setdefault('flow_log', []).append({
        'at': now_iso(),
        'from': '太子調度',
        'to': to or task.get('org', ''),
        'remark': f'🧭 {remark}'
    })


def _scheduler_snapshot(task, note=''):
    sched = _ensure_scheduler(task)
    sched['snapshot'] = {
        'state': task.get('state', ''),
        'org': task.get('org', ''),
        'now': task.get('now', ''),
        'savedAt': now_iso(),
        'note': note or 'snapshot',
    }


def _scheduler_mark_progress(task, note=''):
    sched = _ensure_scheduler(task)
    sched['lastProgressAt'] = now_iso()
    sched['stallSince'] = None
    sched['retryCount'] = 0
    sched['escalationLevel'] = 0
    sched['rollbackCount'] = 0
    sched['lastEscalatedAt'] = None
    if note:
        _scheduler_add_flow(task, f'進展確認：{note}')


def _resolve_openclaw_bin():
    """Return the OpenClaw CLI path used by dashboard dispatch.

    On Windows, npm-installed CLIs are commonly exposed as .cmd shims.  Using
    shutil.which lets Python resolve that shim before subprocess runs.
    """
    configured = os.environ.get('OPENCLAW_BIN', '').strip()
    if configured:
        return configured
    # 優先檢查常見路徑，避免 PATH 缺失導致找不到
    for bin_dir in ('/home/cosmos/.npm-global/bin', '/usr/local/bin', '/usr/bin'):
        candidate = pathlib.Path(bin_dir) / 'openclaw'
        if candidate.exists():
            return str(candidate)
    return shutil.which('openclaw')


def _update_task_scheduler(task_id, updater):
    """Atomically update a task's scheduler state.

    Uses ``modify_task`` to hold the file lock for the entire
    read-modify-write cycle, preventing concurrent dispatch threads and
    the periodic scanner from clobbering each other's writes.
    """
    def _apply(task):
        sched = _ensure_scheduler(task)
        updater(task, sched)

    return modify_task(task_id, _apply)


def get_scheduler_state(task_id):
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}
    sched = _ensure_scheduler(task)
    last_progress = _parse_iso(sched.get('lastProgressAt') or task.get('updatedAt'))
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    stalled_sec = 0
    if last_progress:
        stalled_sec = max(0, int((now_dt - last_progress).total_seconds()))
    return {
        'ok': True,
        'taskId': task_id,
        'state': task.get('state', ''),
        'org': task.get('org', ''),
        'scheduler': sched,
        'stalledSec': stalled_sec,
        'checkedAt': now_iso(),
    }


def handle_scheduler_retry(task_id, reason=''):
    # Pre-check before acquiring lock (avoids holding lock for error paths)
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}
    state = task.get('state', '')
    if state in _TERMINAL_STATES or state == 'Blocked':
        return {'ok': False, 'error': f'任務 {task_id} 當前狀態 {state} 不支持重試'}

    result = {'retryCount': 0, 'state': state}

    def _apply(task):
        cur = task.get('state', '')
        if cur in _TERMINAL_STATES or cur == 'Blocked':
            return  # state changed between pre-check and lock; skip
        sched = _ensure_scheduler(task)
        sched['retryCount'] = int(sched.get('retryCount') or 0) + 1
        sched['lastRetryAt'] = now_iso()
        sched['lastDispatchTrigger'] = 'taizi-retry'
        _scheduler_add_flow(task, f'触发重试第{sched["retryCount"]}次：{reason or "超时未推进"}')
        result['retryCount'] = sched['retryCount']
        result['state'] = cur

    modify_task(task_id, _apply)

    dispatch_for_state(task_id, task, result['state'], trigger='taizi-retry')
    return {'ok': True, 'message': f'{task_id} 已触发重试派发', 'retryCount': result['retryCount']}


def handle_scheduler_escalate(task_id, reason=''):
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}
    state = task.get('state', '')
    if state in _TERMINAL_STATES:
        return {'ok': False, 'error': f'任務 {task_id} 已結束，無需升級'}

    sched = _ensure_scheduler(task)
    current_level = int(sched.get('escalationLevel') or 0)
    next_level = min(current_level + 1, 2)
    target = 'menxia' if next_level == 1 else 'shangshu'
    target_label = '門下省' if next_level == 1 else '尚書省'

    sched['escalationLevel'] = next_level
    sched['lastEscalatedAt'] = now_iso()
    _scheduler_add_flow(task, f'升級到{target_label}協調：{reason or "任務停滯"}', to=target_label)
    task['updatedAt'] = now_iso()
    save_tasks(tasks)

    msg = (
        f'🧭 太子調度升級通知\n'
        f'任務ID: {task_id}\n'
        f'當前狀態: {state}\n'
        f'停滯處理: 請你介入協調推進\n'
        f'原因: {reason or "任務超過閾值未推進"}\n'
        f'⚠️ 看板已有任務，請勿重複創建。'
    )
    wake_agent(target, msg)

    return {'ok': True, 'message': f'{task_id} 已升級至{target_label}', 'escalationLevel': next_level}


def handle_scheduler_rollback(task_id, reason=''):
    # Pre-check before acquiring lock
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}
    sched = _ensure_scheduler(task)
    snapshot = sched.get('snapshot') or {}
    snap_state = snapshot.get('state')
    if not snap_state:
        return {'ok': False, 'error': f'任務 {task_id} 無可用回滾快照'}

    result = {'snap_state': snap_state}

    def _apply(task):
        sched = _ensure_scheduler(task)
        snapshot = sched.get('snapshot') or {}
        s_state = snapshot.get('state')
        if not s_state:
            return  # snapshot cleared between pre-check and lock
        old_state = task.get('state', '')
        task['state'] = s_state
        task['org'] = snapshot.get('org', task.get('org', ''))
        task['now'] = f'↩️ 太子调度自动回滚：{reason or "恢复到上个稳定节点"}'
        task['block'] = '無'
        sched['retryCount'] = 0
        sched['escalationLevel'] = 0
        sched['stallSince'] = None
        sched['lastProgressAt'] = now_iso()
        _scheduler_add_flow(task, f'執行回滾：{old_state} → {s_state}，原因：{reason or "停滯恢復"}')
        result['snap_state'] = s_state

    modify_task(task_id, _apply)

    if result['snap_state'] not in _TERMINAL_STATES:
        dispatch_for_state(task_id, task, result['snap_state'], trigger='taizi-rollback')

    return {'ok': True, 'message': f'{task_id} 已回滾到 {result["snap_state"]}'}


def handle_scheduler_scan(threshold_sec=600):
    """Periodic stall scanner — runs in a background thread.

    Uses ``modify_tasks`` to hold the file lock during the mutation phase,
    preventing concurrent dispatch callbacks and HTTP handlers from
    clobbering each other's writes (fixes TOCTOU race between the old
    ``load_tasks()`` / ``save_tasks()`` pair).

    Side-effects (dispatch, escalation wake) are executed *after* the lock
    is released so they don't block other writers.
    """
    threshold_sec = max(60, int(threshold_sec or 600))
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    # Collect dispatch/escalation work to execute after the lock is released
    pending_retries = []
    pending_escalates = []
    pending_rollbacks = []
    actions = []

    def _scan(tasks):
        changed = False
        for task in tasks:
            task_id = task.get('id', '')
            state = task.get('state', '')
            if not task_id or state in _TERMINAL_STATES or task.get('archived'):
                continue
            if state == 'Blocked':
                continue

            sched = _ensure_scheduler(task)
            task_threshold = int(sched.get('stallThresholdSec') or threshold_sec)
            last_progress = _parse_iso(sched.get('lastProgressAt') or task.get('updatedAt'))
            if not last_progress:
                continue
            stalled_sec = max(0, int((now_dt - last_progress).total_seconds()))
            if stalled_sec < task_threshold:
                continue

            if not sched.get('stallSince'):
                sched['stallSince'] = now_iso()
                changed = True

            retry_count = int(sched.get('retryCount') or 0)
            max_retry = max(0, int(sched.get('maxRetry') or 1))
            level = int(sched.get('escalationLevel') or 0)

            if retry_count < max_retry:
                sched['retryCount'] = retry_count + 1
                sched['lastRetryAt'] = now_iso()
                sched['lastDispatchTrigger'] = 'taizi-scan-retry'
                _scheduler_add_flow(task, f'停滞{stalled_sec}秒，触发自动重试第{sched["retryCount"]}次')
                pending_retries.append((task_id, state))
                actions.append({'taskId': task_id, 'action': 'retry', 'stalledSec': stalled_sec})
                changed = True
                continue

            if level < 2:
                next_level = level + 1
                target = 'menxia' if next_level == 1 else 'shangshu'
                target_label = '门下省' if next_level == 1 else '尚书省'
                sched['escalationLevel'] = next_level
                sched['lastEscalatedAt'] = now_iso()
                _scheduler_add_flow(task, f'停滞{stalled_sec}秒，升级至{target_label}协调', to=target_label)
                pending_escalates.append((task_id, state, target, target_label, stalled_sec))
                actions.append({'taskId': task_id, 'action': 'escalate', 'to': target_label, 'stalledSec': stalled_sec})
                changed = True
                continue

            if sched.get('autoRollback', True):
                rollback_count = int(sched.get('rollbackCount') or 0)
                max_rollback = int(sched.get('maxRollback') or 3)
                snapshot = sched.get('snapshot') or {}
                snap_state = snapshot.get('state')
                if rollback_count >= max_rollback:
                    if state != 'Blocked':
                        task['state'] = 'Blocked'
                        task['now'] = f'🚫 连续回滚{rollback_count}次仍无法推进，已自动挂起'
                        task['block'] = f'连续停滞且回滚{rollback_count}次均失败，需人工介入'
                        sched['stallSince'] = None
                        _scheduler_add_flow(task, f'连续回滚{rollback_count}次，自动挂起等待人工介入')
                        actions.append({'taskId': task_id, 'action': 'blocked', 'reason': f'max rollback {rollback_count}'})
                        changed = True
                elif snap_state and snap_state != state:
                    old_state = state
                    task['state'] = snap_state
                    task['org'] = snapshot.get('org', task.get('org', ''))
                    task['now'] = '↩️ 太子调度自动回滚到稳定节点'
                    task['block'] = '无'
                    sched['retryCount'] = 0
                    sched['escalationLevel'] = 0
                    sched['rollbackCount'] = rollback_count + 1
                    sched['stallSince'] = None
                    sched['lastProgressAt'] = now_iso()
                    _scheduler_add_flow(task, f'连续停滞，自动回滚：{old_state} → {snap_state}（第{rollback_count + 1}次）')
                    pending_rollbacks.append((task_id, snap_state))
                    actions.append({'taskId': task_id, 'action': 'rollback', 'toState': snap_state})
                    changed = True

        return tasks  # always return — atomic_json_update requires it

    modify_tasks(_scan)

    # --- Side-effects: dispatch & escalation (outside the file lock) ---

    # Re-read tasks for dispatch context (the task objects from _scan are
    # no longer held under the lock, but dispatch only needs id + state +
    # title which are immutable at this point).
    tasks = load_tasks()

    for task_id, state in pending_retries:
        retry_task = next((t for t in tasks if t.get('id') == task_id), None)
        if retry_task:
            dispatch_for_state(task_id, retry_task, state, trigger='taizi-scan-retry')

    for task_id, state, target, target_label, stalled_sec in pending_escalates:
        msg = (
            f'🧭 太子調度升級通知\n'
            f'任務ID: {task_id}\n'
            f'當前狀態: {state}\n'
            f'已停滯: {stalled_sec} 秒\n'
            f'請立即介入協調推進\n'
            f'⚠️ 看板已有任務，請勿重複創建。'
        )
        wake_agent(target, msg)

    for task_id, state in pending_rollbacks:
        rollback_task = next((t for t in tasks if t.get('id') == task_id), None)
        if rollback_task and state not in _TERMINAL_STATES:
            dispatch_for_state(task_id, rollback_task, state, trigger='taizi-auto-rollback')

    return {
        'ok': True,
        'thresholdSec': threshold_sec,
        'actions': actions,
        'count': len(actions),
        'checkedAt': now_iso(),
    }


def _startup_recover_queued_dispatches():
    """服務啓動後掃描 lastDispatchStatus=queued 的任務，重新派發。
    解決：kill -9 重啓導致派發線程中斷、任務永久卡住的問題。"""
    tasks = load_tasks()
    recovered = 0
    for task in tasks:
        task_id = task.get('id', '')
        state = task.get('state', '')
        if not task_id or state in _TERMINAL_STATES or task.get('archived'):
            continue
        sched = task.get('_scheduler') or {}
        if sched.get('lastDispatchStatus') == 'queued':
            log.info(f'🔄 啓動恢復: {task_id} 狀態={state} 上次派發未完成，重新派發')
            sched['lastDispatchTrigger'] = 'startup-recovery'
            dispatch_for_state(task_id, task, state, trigger='startup-recovery')
            recovered += 1
    if recovered:
        log.info(f'✅ 啓動恢復完成: 重新派發 {recovered} 個任務')
    else:
        log.info(f'✅ 啓動恢復: 無需恢復')


def handle_repair_flow_order():
    """修復歷史任務中首條流轉爲「皇上->中書省」的錯序問題。"""
    tasks = load_tasks()
    fixed = 0
    fixed_ids = []

    for task in tasks:
        task_id = task.get('id', '')
        if not task_id.startswith('JJC-'):
            continue
        flow_log = task.get('flow_log') or []
        if not flow_log:
            continue

        first = flow_log[0]
        if first.get('from') != '皇上' or first.get('to') != '中書省':
            continue

        first['to'] = '太子'
        remark = first.get('remark', '')
        if isinstance(remark, str) and remark.startswith('下旨：'):
            first['remark'] = remark

        if task.get('state') == 'Zhongshu' and task.get('org') == '中書省' and len(flow_log) == 1:
            set_task_state(task_id, 'Taizi', '等待太子接旨分揀')
            # 重新讀取，確保下方保存使用最新內容
            tasks = load_tasks()
            task = next((t for t in tasks if t.get('id') == task_id), None)
            if not task:
                continue
            task['org'] = '太子'

        task['updatedAt'] = now_iso()
        fixed += 1
        fixed_ids.append(task_id)

    if fixed:
        save_tasks(tasks)

    return {
        'ok': True,
        'count': fixed,
        'taskIds': fixed_ids[:80],
        'more': max(0, fixed - 80),
        'checkedAt': now_iso(),
    }


def _collect_message_text(msg):
    """收集消息中的可檢索文本，用於 task_id/關鍵詞過濾。"""
    parts = []
    for c in msg.get('content', []) or []:
        ctype = c.get('type')
        if ctype == 'text' and c.get('text'):
            parts.append(str(c.get('text', '')))
        elif ctype == 'thinking' and c.get('thinking'):
            parts.append(str(c.get('thinking', '')))
        elif ctype == 'tool_use':
            parts.append(json.dumps(c.get('input', {}), ensure_ascii=False))
    details = msg.get('details') or {}
    for key in ('output', 'stdout', 'stderr', 'message'):
        val = details.get(key)
        if isinstance(val, str) and val:
            parts.append(val)
    return ''.join(parts)


def _parse_activity_entry(item):
    """將 session jsonl 的 message 統一解析成看板活動條目。"""
    msg = item.get('message') or {}
    role = str(msg.get('role', '')).strip().lower()
    ts = item.get('timestamp', '')

    if role == 'assistant':
        text = ''
        thinking = ''
        tool_calls = []
        for c in msg.get('content', []) or []:
            if c.get('type') == 'text' and c.get('text') and not text:
                text = str(c.get('text', '')).strip()
            elif c.get('type') == 'thinking' and c.get('thinking') and not thinking:
                thinking = str(c.get('thinking', '')).strip()[:200]
            elif c.get('type') == 'tool_use':
                tool_calls.append({
                    'name': c.get('name', ''),
                    'input_preview': json.dumps(c.get('input', {}), ensure_ascii=False)[:100]
                })
        if not (text or thinking or tool_calls):
            return None
        entry = {'at': ts, 'kind': 'assistant'}
        if text:
            entry['text'] = text[:300]
        if thinking:
            entry['thinking'] = thinking
        if tool_calls:
            entry['tools'] = tool_calls
        return entry

    if role in ('toolresult', 'tool_result'):
        details = msg.get('details') or {}
        code = details.get('exitCode')
        if code is None:
            code = details.get('code', details.get('status'))
        output = ''
        for c in msg.get('content', []) or []:
            if c.get('type') == 'text' and c.get('text'):
                output = str(c.get('text', '')).strip()[:200]
                break
        if not output:
            for key in ('output', 'stdout', 'stderr', 'message'):
                val = details.get(key)
                if isinstance(val, str) and val.strip():
                    output = val.strip()[:200]
                    break

        entry = {
            'at': ts,
            'kind': 'tool_result',
            'tool': msg.get('toolName', msg.get('name', '')),
            'exitCode': code,
            'output': output,
        }
        duration_ms = details.get('durationMs')
        if isinstance(duration_ms, (int, float)):
            entry['durationMs'] = int(duration_ms)
        return entry

    if role == 'user':
        text = ''
        for c in msg.get('content', []) or []:
            if c.get('type') == 'text' and c.get('text'):
                text = str(c.get('text', '')).strip()
                break
        if not text:
            return None
        return {'at': ts, 'kind': 'user', 'text': text[:200]}

    return None


def get_agent_activity(agent_id, limit=30, task_id=None):
    """從 Agent 的 session jsonl 讀取最近活動。
    如果 task_id 不爲空，只返回提及該 task_id 的相關條目。
    """
    sessions_dir = OCLAW_HOME / 'agents' / agent_id / 'sessions'
    if not sessions_dir.exists():
        return []

    # 掃描所有 jsonl（按修改時間倒序），優先最新
    jsonl_files = sorted(sessions_dir.glob('*.jsonl'), key=lambda f: f.stat().st_mtime, reverse=True)
    if not jsonl_files:
        return []

    entries = []
    # 如果需要按 task_id 過濾，可能需要掃描多個文件
    files_to_scan = jsonl_files[:3] if task_id else jsonl_files[:1]

    for session_file in files_to_scan:
        try:
            lines = session_file.read_text(errors='ignore').splitlines()
        except Exception:
            continue

        # 正向掃描以保持時間順序；如果有 task_id，收集提及 task_id 的條目
        for ln in lines:
            try:
                item = json.loads(ln)
            except Exception:
                continue
            msg = item.get('message') or {}
            all_text = _collect_message_text(msg)

            # task_id 過濾：只保留提及 task_id 的條目
            if task_id and task_id not in all_text:
                continue
            entry = _parse_activity_entry(item)
            if entry:
                entries.append(entry)

            if len(entries) >= limit:
                break
        if len(entries) >= limit:
            break

    # 只保留最後 limit 條
    return entries[-limit:]


def _extract_keywords(title):
    """從任務標題中提取有意義的關鍵詞（用於 session 內容匹配）。"""
    stop = {'的', '了', '在', '是', '有', '和', '與', '或', '一個', '一篇', '關於', '進行',
            '寫', '做', '請', '把', '給', '用', '要', '需要', '面向', '風格', '包含',
            '出', '個', '不', '可以', '應該', '如何', '怎麼', '什麼', '這個', '那個'}
    # 提取英文詞
    en_words = re.findall(r'[a-zA-Z][\w.-]{1,}', title)
    # 提取 2-4 字中文詞組（更短的顆粒度）
    cn_words = re.findall(r'[\u4e00-\u9fff]{2,4}', title)
    all_words = en_words + cn_words
    kws = [w for w in all_words if w not in stop and len(w) >= 2]
    # 去重保序
    seen = set()
    unique = []
    for w in kws:
        if w.lower() not in seen:
            seen.add(w.lower())
            unique.append(w)
    return unique[:8]  # 最多 8 個關鍵詞


def get_agent_activity_by_keywords(agent_id, keywords, limit=20):
    """從 agent session 中按關鍵詞匹配獲取活動條目。
    找到包含關鍵詞的 session 文件，只讀該文件的活動。
    """
    sessions_dir = OCLAW_HOME / 'agents' / agent_id / 'sessions'
    if not sessions_dir.exists():
        return []

    jsonl_files = sorted(sessions_dir.glob('*.jsonl'), key=lambda f: f.stat().st_mtime, reverse=True)
    if not jsonl_files:
        return []

    # 找到包含關鍵詞的 session 文件
    target_file = None
    for sf in jsonl_files[:5]:
        try:
            content = sf.read_text(errors='ignore')
        except Exception:
            continue
        hits = sum(1 for kw in keywords if kw.lower() in content.lower())
        if hits >= min(2, len(keywords)):
            target_file = sf
            break

    if not target_file:
        return []

    # 解析 session 文件，按 user 消息分割爲對話段
    # 找到包含關鍵詞的對話段，只返回該段的活動
    try:
        lines = target_file.read_text(errors='ignore').splitlines()
    except Exception:
        return []

    # 第一遍：找到關鍵詞匹配的 user 消息位置
    user_msg_indices = []  # (line_index, user_text)
    for i, ln in enumerate(lines):
        try:
            item = json.loads(ln)
        except Exception:
            continue
        msg = item.get('message') or {}
        if msg.get('role') == 'user':
            text = ''
            for c in msg.get('content', []):
                if c.get('type') == 'text' and c.get('text'):
                    text += c['text']
            user_msg_indices.append((i, text))

    # 找到與關鍵詞匹配度最高的 user 消息
    best_idx = -1
    best_hits = 0
    for line_idx, utext in user_msg_indices:
        hits = sum(1 for kw in keywords if kw.lower() in utext.lower())
        if hits > best_hits:
            best_hits = hits
            best_idx = line_idx

    # 確定對話段的行範圍：從匹配的 user 消息到下一個 user 消息之前
    if best_idx >= 0 and best_hits >= min(2, len(keywords)):
        # 找下一個 user 消息的位置
        next_user_idx = len(lines)
        for line_idx, _ in user_msg_indices:
            if line_idx > best_idx:
                next_user_idx = line_idx
                break
        start_line = best_idx
        end_line = next_user_idx
    else:
        # 沒找到匹配的對話段，返回空
        return []

    # 第二遍：只解析對話段內的行
    entries = []
    for ln in lines[start_line:end_line]:
        try:
            item = json.loads(ln)
        except Exception:
            continue
        entry = _parse_activity_entry(item)
        if entry:
            entries.append(entry)

    return entries[-limit:]


def get_agent_latest_segment(agent_id, limit=20):
    """獲取 Agent 最新一輪對話段（最後一條 user 消息起的所有內容）。
    用於活躍任務沒有精確匹配時，展示 Agent 的實時工作狀態。
    """
    sessions_dir = OCLAW_HOME / 'agents' / agent_id / 'sessions'
    if not sessions_dir.exists():
        return []

    jsonl_files = sorted(sessions_dir.glob('*.jsonl'),
                         key=lambda f: f.stat().st_mtime, reverse=True)
    if not jsonl_files:
        return []

    # 讀取最新的 session 文件
    target_file = jsonl_files[0]
    try:
        lines = target_file.read_text(errors='ignore').splitlines()
    except Exception:
        return []

    # 找到最後一條 user 消息的行號
    last_user_idx = -1
    for i, ln in enumerate(lines):
        try:
            item = json.loads(ln)
        except Exception:
            continue
        msg = item.get('message') or {}
        if msg.get('role') == 'user':
            last_user_idx = i

    if last_user_idx < 0:
        return []

    # 從最後一條 user 消息開始，解析到文件末尾
    entries = []
    for ln in lines[last_user_idx:]:
        try:
            item = json.loads(ln)
        except Exception:
            continue
        entry = _parse_activity_entry(item)
        if entry:
            entries.append(entry)

    return entries[-limit:]


def _compute_phase_durations(flow_log):
    """從 flow_log 計算每個階段的停留時長。"""
    if not flow_log or len(flow_log) < 1:
        return []
    phases = []
    for i, fl in enumerate(flow_log):
        start_at = fl.get('at', '')
        to_dept = fl.get('to', '')
        remark = fl.get('remark', '')
        # 下一階段的起始時間就是本階段的結束時間
        if i + 1 < len(flow_log):
            end_at = flow_log[i + 1].get('at', '')
            ongoing = False
        else:
            end_at = now_iso()
            ongoing = True
        # 計算時長
        dur_sec = 0
        try:
            from_dt = datetime.datetime.fromisoformat(start_at.replace('Z', '+00:00'))
            to_dt = datetime.datetime.fromisoformat(end_at.replace('Z', '+00:00'))
            dur_sec = max(0, int((to_dt - from_dt).total_seconds()))
        except Exception:
            pass
        # 人類可讀時長
        if dur_sec < 60:
            dur_text = f'{dur_sec}秒'
        elif dur_sec < 3600:
            dur_text = f'{dur_sec // 60}分{dur_sec % 60}秒'
        elif dur_sec < 86400:
            h, rem = divmod(dur_sec, 3600)
            dur_text = f'{h}小時{rem // 60}分'
        else:
            d, rem = divmod(dur_sec, 86400)
            dur_text = f'{d}天{rem // 3600}小時'
        phases.append({
            'phase': to_dept,
            'from': start_at,
            'to': end_at,
            'durationSec': dur_sec,
            'durationText': dur_text,
            'ongoing': ongoing,
            'remark': remark,
        })
    return phases


def _compute_todos_summary(todos):
    """計算 todos 完成率匯總。"""
    if not todos:
        return None
    total = len(todos)
    completed = sum(1 for t in todos if t.get('status') == 'completed')
    in_progress = sum(1 for t in todos if t.get('status') == 'in-progress')
    not_started = total - completed - in_progress
    percent = round(completed / total * 100) if total else 0
    return {
        'total': total,
        'completed': completed,
        'inProgress': in_progress,
        'notStarted': not_started,
        'percent': percent,
    }


def _compute_todos_diff(prev_todos, curr_todos):
    """計算兩個 todos 快照之間的差異。"""
    prev_map = {str(t.get('id', '')): t for t in (prev_todos or [])}
    curr_map = {str(t.get('id', '')): t for t in (curr_todos or [])}
    changed, added, removed = [], [], []
    for tid, ct in curr_map.items():
        if tid in prev_map:
            pt = prev_map[tid]
            if pt.get('status') != ct.get('status'):
                changed.append({
                    'id': tid, 'title': ct.get('title', ''),
                    'from': pt.get('status', ''), 'to': ct.get('status', ''),
                })
        else:
            added.append({'id': tid, 'title': ct.get('title', '')})
    for tid, pt in prev_map.items():
        if tid not in curr_map:
            removed.append({'id': tid, 'title': pt.get('title', '')})
    if not changed and not added and not removed:
        return None
    return {'changed': changed, 'added': added, 'removed': removed}


def get_task_activity(task_id):
    """獲取任務的實時進展數據。
    數據來源：
    1. 任務自身的 now / todos / flow_log 字段（由 Agent 通過 progress 命令主動上報）
    2. Agent session JSONL 中的對話日誌（thinking / tool_result / user，用於展示思考過程）

    增強字段:
    - taskMeta: 任務元信息 (title/state/org/output/block/priority/reviewRound/archived)
    - phaseDurations: 各階段停留時長
    - todosSummary: todos 完成率匯總
    - resourceSummary: Agent 資源消耗匯總 (tokens/cost/elapsed)
    - activity 條目中 progress/todos 保留 state/org 快照
    - activity 中 todos 條目含 diff 字段
    """
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}

    state = task.get('state', '')
    org = task.get('org', '')
    now_text = task.get('now', '')
    todos = task.get('todos', [])
    updated_at = task.get('updatedAt', '')

    # ── 任務元信息 ──
    task_meta = {
        'title': task.get('title', ''),
        'state': state,
        'org': org,
        'output': task.get('output', ''),
        'block': task.get('block', ''),
        'priority': task.get('priority', 'normal'),
        'reviewRound': task.get('review_round', 0),
        'archived': task.get('archived', False),
    }

    # 當前負責 Agent（兼容舊邏輯）
    agent_id = _STATE_AGENT_MAP.get(state)
    if agent_id is None and state in ('Doing', 'Next'):
        agent_id = _ORG_AGENT_MAP.get(org)

    # ── 構建活動條目列表（flow_log + progress_log）──
    activity = []
    flow_log = task.get('flow_log', [])

    # 1. flow_log 轉爲活動條目
    for fl in flow_log:
        activity.append({
            'at': fl.get('at', ''),
            'kind': 'flow',
            'from': fl.get('from', ''),
            'to': fl.get('to', ''),
            'remark': fl.get('remark', ''),
        })

    progress_log = task.get('progress_log', [])
    related_agents = set()

    # 資源消耗累加
    total_tokens = 0
    total_cost = 0.0
    total_elapsed = 0
    has_resource_data = False

    # 用於 todos diff 計算
    prev_todos_snapshot = None

    if progress_log:
        # 2. 多 Agent 實時進展日誌（每條 progress 都保留自己的 todo 快照）
        for pl in progress_log:
            p_at = pl.get('at', '')
            p_agent = pl.get('agent', '')
            p_text = pl.get('text', '')
            p_todos = pl.get('todos', [])
            p_state = pl.get('state', '')
            p_org = pl.get('org', '')
            if p_agent:
                related_agents.add(p_agent)
            # 累加資源消耗
            if pl.get('tokens'):
                total_tokens += pl['tokens']
                has_resource_data = True
            if pl.get('cost'):
                total_cost += pl['cost']
                has_resource_data = True
            if pl.get('elapsed'):
                total_elapsed += pl['elapsed']
                has_resource_data = True
            if p_text:
                entry = {
                    'at': p_at,
                    'kind': 'progress',
                    'text': p_text,
                    'agent': p_agent,
                    'agentLabel': pl.get('agentLabel', ''),
                    'state': p_state,
                    'org': p_org,
                }
                # 單條資源數據
                if pl.get('tokens'):
                    entry['tokens'] = pl['tokens']
                if pl.get('cost'):
                    entry['cost'] = pl['cost']
                if pl.get('elapsed'):
                    entry['elapsed'] = pl['elapsed']
                activity.append(entry)
            if p_todos:
                todos_entry = {
                    'at': p_at,
                    'kind': 'todos',
                    'items': p_todos,
                    'agent': p_agent,
                    'agentLabel': pl.get('agentLabel', ''),
                    'state': p_state,
                    'org': p_org,
                }
                # 計算 diff
                diff = _compute_todos_diff(prev_todos_snapshot, p_todos)
                if diff:
                    todos_entry['diff'] = diff
                activity.append(todos_entry)
                prev_todos_snapshot = p_todos

        # 僅當無法通過狀態確定 Agent 時，才回退到最後一次上報的 Agent
        if not agent_id:
            last_pl = progress_log[-1]
            if last_pl.get('agent'):
                agent_id = last_pl.get('agent')
    else:
        # 兼容舊數據：僅使用 now/todos
        if now_text:
            activity.append({
                'at': updated_at,
                'kind': 'progress',
                'text': now_text,
                'agent': agent_id or '',
                'state': state,
                'org': org,
            })
        if todos:
            activity.append({
                'at': updated_at,
                'kind': 'todos',
                'items': todos,
                'agent': agent_id or '',
                'state': state,
                'org': org,
            })

    # 按時間排序，保證流轉/進展穿插正確
    activity.sort(key=lambda x: x.get('at', ''))

    if agent_id:
        related_agents.add(agent_id)

    # ── 融合 Agent Session 活動（thinking / tool_result / user）──
    # 從 session JSONL 中提取 Agent 的思考過程和工具調用記錄
    try:
        session_entries = []
        # 活躍任務：嘗試按 task_id 精確匹配
        if state not in ('Done', 'Cancelled'):
            if agent_id:
                entries = get_agent_activity(agent_id, limit=30, task_id=task_id)
                session_entries.extend(entries)
            # 也從其他相關 Agent 獲取
            for ra in related_agents:
                if ra != agent_id:
                    entries = get_agent_activity(ra, limit=20, task_id=task_id)
                    session_entries.extend(entries)
        else:
            # 已完成任務：基於關鍵詞匹配
            title = task.get('title', '')
            keywords = _extract_keywords(title)
            if keywords:
                agents_to_scan = list(related_agents) if related_agents else ([agent_id] if agent_id else [])
                for ra in agents_to_scan[:5]:
                    entries = get_agent_activity_by_keywords(ra, keywords, limit=15)
                    session_entries.extend(entries)
        # 去重（通過 at+kind 去重避免重複）
        existing_keys = {(a.get('at', ''), a.get('kind', '')) for a in activity}
        for se in session_entries:
            key = (se.get('at', ''), se.get('kind', ''))
            if key not in existing_keys:
                activity.append(se)
                existing_keys.add(key)
        # 重新排序
        activity.sort(key=lambda x: x.get('at', ''))
    except Exception as e:
        log.warning(f'Session JSONL 融合失敗 (task={task_id}): {e}')

    # ── 階段耗時統計 ──
    phase_durations = _compute_phase_durations(flow_log)

    # ── Todos 匯總 ──
    todos_summary = _compute_todos_summary(todos)

    # ── 總耗時（首條 flow_log 到最後一條/當前） ──
    total_duration = None
    if flow_log:
        try:
            first_at = datetime.datetime.fromisoformat(flow_log[0].get('at', '').replace('Z', '+00:00'))
            if state in ('Done', 'Cancelled') and len(flow_log) >= 2:
                last_at = datetime.datetime.fromisoformat(flow_log[-1].get('at', '').replace('Z', '+00:00'))
            else:
                last_at = datetime.datetime.now(datetime.timezone.utc)
            dur = max(0, int((last_at - first_at).total_seconds()))
            if dur < 60:
                total_duration = f'{dur}秒'
            elif dur < 3600:
                total_duration = f'{dur // 60}分{dur % 60}秒'
            elif dur < 86400:
                h, rem = divmod(dur, 3600)
                total_duration = f'{h}小時{rem // 60}分'
            else:
                d, rem = divmod(dur, 86400)
                total_duration = f'{d}天{rem // 3600}小時'
        except Exception:
            pass

    last_active = None
    if updated_at:
        try:
            dt = _parse_iso(updated_at)
            if dt:
                last_active = dt.astimezone().strftime('%Y-%m-%d %H:%M:%S')
            else:
                last_active = updated_at[:19].replace('T', ' ')
        except Exception:
            last_active = updated_at[:19].replace('T', ' ')

    result = {
        'ok': True,
        'taskId': task_id,
        'taskMeta': task_meta,
        'agentId': agent_id,
        'agentLabel': _STATE_LABELS.get(state, state),
        'lastActive': last_active,
        'activity': activity,
        'activitySource': 'progress+session',
        'relatedAgents': sorted(list(related_agents)),
        'phaseDurations': phase_durations,
        'totalDuration': total_duration,
    }
    if todos_summary:
        result['todosSummary'] = todos_summary
    if has_resource_data:
        result['resourceSummary'] = {
            'totalTokens': total_tokens,
            'totalCost': round(total_cost, 4),
            'totalElapsedSec': total_elapsed,
        }
    return result


# 狀態推進順序（手動推進用）
_STATE_FLOW = {
    'Pending':  ('Taizi', '皇上', '太子', '待處理旨意轉交太子分揀'),
    'Taizi':    ('Zhongshu', '太子', '中書省', '太子分揀完畢，轉中書省起草'),
    'Zhongshu': ('Menxia', '中書省', '門下省', '中書省方案提交門下省審議'),
    'Menxia':   ('Assigned', '門下省', '尚書省', '門下省準奏，轉尚書省派發'),
    'Assigned': ('Doing', '尚書省', '六部', '尚書省開始派發執行'),
    'Next':     ('Doing', '尚書省', '六部', '待執行任務開始執行'),
    'Doing':    ('Review', '六部', '尚書省', '各部完成，進入匯總'),
    'Review':   ('Done', '尚書省', '太子', '全流程完成，回奏太子轉報皇上'),
}
_STATE_LABELS = {
    'Pending': '待處理', 'Taizi': '太子', 'Zhongshu': '中書省', 'Menxia': '門下省',
    'Assigned': '尚書省', 'Next': '待執行', 'Doing': '執行中', 'Review': '審查', 'Done': '完成',
}


from dispatch import dispatch_for_state as _dispatch_impl

def dispatch_for_state(task_id, task, new_state, trigger='state-transition'):
    """統一派發入口（轉發至 dispatch.py 封裝的實作）。"""
    _dispatch_impl(task_id, task, new_state, trigger)
    """推進/審批後自動派發對應 Agent（後臺異步，不阻塞響應）。"""
    agent_id = _STATE_AGENT_MAP.get(new_state)
    if agent_id is None and new_state in ('Doing', 'Next'):
        org = task.get('org', '')
        agent_id = _ORG_AGENT_MAP.get(org)
    if not agent_id:
        log.info(f'ℹ️ {task_id} 新狀態 {new_state} 無對應 Agent，跳過自動派發')
        return

    _update_task_scheduler(task_id, lambda t, s: (
        s.update({
            'lastDispatchAt': now_iso(),
            'lastDispatchStatus': 'queued',
            'lastDispatchAgent': agent_id,
            'lastDispatchTrigger': trigger,
        }),
        _scheduler_add_flow(t, f'已入隊派發：{new_state} → {agent_id}（{trigger}）', to=_STATE_LABELS.get(new_state, new_state))
    ))

    title = task.get('title', '(無標題)')
    target_dept = task.get('targetDept', '')

    # 根據 agent_id 構造針對性消息
    _msgs = {
        'taizi': (
            f'📜 皇上旨意需要你處理\n'
            f'任務ID: {task_id}\n'
            f'旨意: {title}\n'
            f'⚠️ 看板已有此任務，請勿重複創建。直接用 kanban_update.py 更新狀態。\n'
            f'請立即轉交中書省起草執行方案。'
        ),
        'zhongshu': (
            f'📜 旨意已到中書省，請起草方案\n'
            f'任務ID: {task_id}\n'
            f'旨意: {title}\n'
            f'⚠️ 看板已有此任務記錄，請勿重複創建。直接用 kanban_update.py state 更新狀態。\n'
            f'請立即起草執行方案，走完完整三省流程（中書起草→門下審議→尚書派發→六部執行）。'
        ),
        'menxia': (
            f'📋 中書省方案提交審議\n'
            f'任務ID: {task_id}\n'
            f'旨意: {title}\n'
            f'⚠️ 看板已有此任務，請勿重複創建。\n'
            f'請審議中書省方案，給出準奏或封駁意見。'
        ),
        'shangshu': (
            f'📮 門下省已準奏，請派發執行\n'
            f'任務ID: {task_id}\n'
            f'旨意: {title}\n'
            f'{"建議派發部門: " + target_dept if target_dept else ""}\n'
            f'⚠️ 看板已有此任務，請勿重複創建。\n'
            f'請分析方案並派發給六部執行。'
        ),
    }
    msg = _msgs.get(agent_id, (
        f'📌 請處理任務\n'
        f'任務ID: {task_id}\n'
        f'旨意: {title}\n'
        f'⚠️ 看板已有此任務，請勿重複創建。直接用 kanban_update.py 更新狀態。'
    ))

    def _do_dispatch():
        try:
            # Gateway 可能暫時不可達（休眠恢復、進程重啓），等待後重試
            import time as _time
            _gw_alive = False
            for _gw_attempt in range(3):
                if _check_gateway_alive():
                    _gw_alive = True
                    break
                if _gw_attempt < 2:
                    _time.sleep(5 * (_gw_attempt + 1))  # 5s, 10s
            if not _gw_alive:
                log.warning(f'⚠️ {task_id} 自動派發跳過: Gateway 未啓動（重試3次仍不可達）')
                _update_task_scheduler(task_id, lambda t, s: s.update({
                    'lastDispatchAt': now_iso(),
                    'lastDispatchStatus': 'gateway-offline',
                    'lastDispatchAgent': agent_id,
                    'lastDispatchTrigger': trigger,
                }))
                return
            # Fix #139/#182: dispatch channel 可配置；未配置時不傳 --deliver 避免
            # "unknown channel: feishu" 錯誤（非飛書用戶）
            _agent_cfg = read_json(DATA / 'agent_config.json', {})
            _channel = (_agent_cfg.get('dispatchChannel') or '').strip()
            openclaw_bin = _resolve_openclaw_bin()
            if not openclaw_bin:
                err = 'OpenClaw CLI 未找到：請確認已安裝 openclaw 並加入 PATH；Windows 可設置 OPENCLAW_BIN 指向 openclaw.cmd'
                log.warning(f'⚠️ {task_id} 自動派發異常: {err}')
                _update_task_scheduler(task_id, lambda t, s: (
                    s.update({
                        'lastDispatchAt': now_iso(),
                        'lastDispatchStatus': 'openclaw-missing',
                        'lastDispatchAgent': agent_id,
                        'lastDispatchTrigger': trigger,
                        'lastDispatchError': err,
                    }),
                    _scheduler_add_flow(t, f'派發異常：OpenClaw CLI 未找到（{trigger}）', to=t.get('org', ''))
                ))
                return
            cmd = [openclaw_bin, 'agent', '--agent', agent_id, '-m', msg, '--timeout', '300']
            if _channel:
                cmd.extend(['--deliver', '--channel', _channel])
            max_retries = 2
            err = ''
            for attempt in range(1, max_retries + 1):
                log.info(f'🔄 自動派發 {task_id} → {agent_id} (第{attempt}次)...')
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=310)
                if result.returncode == 0:
                    log.info(f'✅ {task_id} 自動派發成功 → {agent_id}')
                    _update_task_scheduler(task_id, lambda t, s: (
                        s.update({
                            'lastDispatchAt': now_iso(),
                            'lastDispatchStatus': 'success',
                            'lastDispatchAgent': agent_id,
                            'lastDispatchTrigger': trigger,
                            'lastDispatchError': '',
                        }),
                        _scheduler_add_flow(t, f'派發成功：{agent_id}（{trigger}）', to=t.get('org', ''))
                    ))
                    return
                err = result.stderr[:200] if result.stderr else result.stdout[:200]
                log.warning(f'⚠️ {task_id} 自動派發失敗(第{attempt}次): {err}')
                if attempt < max_retries:
                    import time
                    time.sleep(5)
            log.error(f'❌ {task_id} 自動派發最終失敗 → {agent_id}')
            _update_task_scheduler(task_id, lambda t, s: (
                s.update({
                    'lastDispatchAt': now_iso(),
                    'lastDispatchStatus': 'failed',
                    'lastDispatchAgent': agent_id,
                    'lastDispatchTrigger': trigger,
                    'lastDispatchError': err,
                }),
                _scheduler_add_flow(t, f'派發失敗：{agent_id}（{trigger}）', to=t.get('org', ''))
            ))
        except subprocess.TimeoutExpired:
            log.error(f'❌ {task_id} 自動派發超時 → {agent_id}')
            _update_task_scheduler(task_id, lambda t, s: (
                s.update({
                    'lastDispatchAt': now_iso(),
                    'lastDispatchStatus': 'timeout',
                    'lastDispatchAgent': agent_id,
                    'lastDispatchTrigger': trigger,
                    'lastDispatchError': 'timeout',
                }),
                _scheduler_add_flow(t, f'派發超時：{agent_id}（{trigger}）', to=t.get('org', ''))
            ))
        except FileNotFoundError as e:
            err = f'OpenClaw CLI 未找到：{e}'
            log.warning(f'⚠️ {task_id} 自動派發異常: {err}')
            _update_task_scheduler(task_id, lambda t, s: (
                s.update({
                    'lastDispatchAt': now_iso(),
                    'lastDispatchStatus': 'openclaw-missing',
                    'lastDispatchAgent': agent_id,
                    'lastDispatchTrigger': trigger,
                    'lastDispatchError': err[:200],
                }),
                _scheduler_add_flow(t, f'派發異常：OpenClaw CLI 未找到（{trigger}）', to=t.get('org', ''))
            ))
        except Exception as e:
            log.warning(f'⚠️ {task_id} 自動派發異常: {e}')
            _update_task_scheduler(task_id, lambda t, s: (
                s.update({
                    'lastDispatchAt': now_iso(),
                    'lastDispatchStatus': 'error',
                    'lastDispatchAgent': agent_id,
                    'lastDispatchTrigger': trigger,
                    'lastDispatchError': str(e)[:200],
                }),
                _scheduler_add_flow(t, f'派發異常：{agent_id}（{trigger}）', to=t.get('org', ''))
            ))

    threading.Thread(target=_do_dispatch, daemon=True).start()
    log.info(f'🚀 {task_id} 推進後自動派發 → {agent_id}')


def handle_advance_state(task_id, comment=''):
    """手動推進任務到下一階段（解卡用）。

    核心狀態與流轉寫入統一走 kanban_update 共用函式，避免 Dashboard 與 CLI 分叉。
    """
    tasks = load_tasks()
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return {'ok': False, 'error': f'任務 {task_id} 不存在'}
    cur = task.get('state', '')
    if cur not in _STATE_FLOW:
        return {'ok': False, 'error': f'任務 {task_id} 狀態爲 {cur}，無法推進'}

    _ensure_scheduler(task)
    _scheduler_snapshot(task, f'advance-before-{cur}')

    next_state, from_dept, to_dept, default_remark = _STATE_FLOW[cur]
    remark = comment or default_remark

    # 統一狀態更新 + 流轉留痕
    set_task_state(task_id, next_state, f'⬇️ 手動推進：{remark}')
    record_task_flow(task_id, from_dept, to_dept, f'⬇️ 手動推進：{remark}')

    # 補充 scheduler 進度（Dashboard 擴展信息）
    tasks2 = load_tasks()
    task2 = next((t for t in tasks2 if t.get('id') == task_id), None)
    if task2:
        _ensure_scheduler(task2)
        _scheduler_mark_progress(task2, f'手動推進 {cur} -> {next_state}')
        task2['updatedAt'] = now_iso()
        save_tasks(tasks2)

    from_label = _STATE_LABELS.get(cur, cur)
    to_label = _STATE_LABELS.get(next_state, next_state)
    dispatched = ' (已自動派發 Agent)' if next_state != 'Done' else ''
    return {'ok': True, 'message': f'{task_id} {from_label} → {to_label}{dispatched}'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 只記錄 4xx/5xx 錯誤請求
        if args and len(args) >= 1:
            status = str(args[0]) if args else ''
            if status.startswith('4') or status.startswith('5'):
                log.warning(f'{self.client_address[0]} {fmt % args}')

    def handle_error(self):
        pass  # 靜默處理連接錯誤，避免 BrokenPipe 崩潰

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass  # 客戶端斷開連接，忽略

    def do_OPTIONS(self):
        self.send_response(200)
        cors_headers(self)
        self.end_headers()

    def send_json(self, data, code=200):
        try:
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            cors_headers(self)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_file(self, path: pathlib.Path, mime='text/html; charset=utf-8'):
        if not path.exists():
            self.send_error(404)
            return
        try:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            cors_headers(self)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_static(self, rel_path):
        """從 dist/ 目錄提供靜態文件。"""
        safe = rel_path.replace('\\', '/').lstrip('/')
        if '..' in safe:
            self.send_error(403)
            return True
        fp = DIST / safe
        if fp.is_file():
            mime = _MIME_TYPES.get(fp.suffix.lower(), 'application/octet-stream')
            self.send_file(fp, mime)
            return True
        return False

    def _check_auth(self):
        """檢查認證，未通過返回 True（已發送 401 響應）。"""
        p = urlparse(self.path).path.rstrip('/')
        if not requires_auth(p):
            return False
        token = extract_token(self.headers)
        if not token or not verify_token(token):
            self.send_json({'ok': False, 'error': '未登錄或會話已過期'}, 401)
            return True
        return False

    def do_GET(self):
        p = urlparse(self.path).path.rstrip('/')
        # 認證狀態端點（公開）
        if p == '/api/auth/status':
            self.send_json({'enabled': auth_enabled(), 'configured': auth_configured()})
            return
        if self._check_auth():
            return
        if p in ('', '/dashboard', '/dashboard.html'):
            self.send_file(DIST / 'index.html')
        elif p == '/healthz':
            task_data_dir = get_task_data_dir()
            checks = {'dataDir': task_data_dir.is_dir(), 'tasksReadable': (task_data_dir / 'tasks_source.json').exists()}
            checks['dataWritable'] = os.access(str(task_data_dir), os.W_OK)
            all_ok = all(checks.values())
            self.send_json({'status': 'ok' if all_ok else 'degraded', 'ts': now_iso(), 'checks': checks})
        elif p == '/api/source-mode':
            cfg = _load_task_source_mode()
            health = _backend_health(cfg)
            effective = _effective_source_mode(cfg, health.get('ok'))
            self.send_json({'ok': True, 'config': cfg, 'backend': health, 'effective': effective})
        elif p == '/api/live-status':
            self.send_json(get_live_status_with_mode())
        elif p == '/api/agent-config':
            self.send_json(read_json(DATA / 'agent_config.json'))
        elif p == '/api/model-change-log':
            self.send_json(read_json(DATA / 'model_change_log.json', []))
        elif p == '/api/last-result':
            self.send_json(read_json(DATA / 'last_model_change_result.json', {}))
        elif p == '/api/officials-stats':
            self.send_json(read_json(DATA / 'officials_stats.json', {}))
        elif p == '/api/morning-brief':
            self.send_json(read_json(DATA / 'morning_brief.json', {}))
        elif p == '/api/morning-config':
            migrate_notification_config()
            self.send_json(read_json(DATA / 'morning_brief_config.json', {
                'categories': [
                    {'name': '政治', 'enabled': True},
                    {'name': '軍事', 'enabled': True},
                    {'name': '經濟', 'enabled': True},
                    {'name': 'AI大模型', 'enabled': True},
                ],
                'keywords': [], 'custom_feeds': [],
                'notification': {'enabled': True, 'channel': 'feishu', 'webhook': ''},
            }))
        elif p == '/api/notification-channels':
            self.send_json({'ok': True, 'channels': get_channel_info()})
        elif p.startswith('/api/morning-brief/'):
            date = p.split('/')[-1]
            # 標準化日期格式爲 YYYYMMDD（兼容 YYYY-MM-DD 輸入）
            date_clean = date.replace('-', '')
            if not date_clean.isdigit() or len(date_clean) != 8:
                self.send_json({'ok': False, 'error': f'日期格式無效: {date}，請使用 YYYYMMDD'}, 400)
                return
            self.send_json(read_json(DATA / f'morning_brief_{date_clean}.json', {}))
        elif p == '/api/remote-skills-list':
            self.send_json(get_remote_skills_list())
        elif p.startswith('/api/skill-content/'):
            # /api/skill-content/{agentId}/{skillName}
            parts = p.replace('/api/skill-content/', '').split('/', 1)
            if len(parts) == 2:
                self.send_json(read_skill_content(parts[0], parts[1]))
            else:
                self.send_json({'ok': False, 'error': 'Usage: /api/skill-content/{agentId}/{skillName}'}, 400)
        elif p.startswith('/api/task-activity/'):
            task_id = p.replace('/api/task-activity/', '')
            if not task_id:
                self.send_json({'ok': False, 'error': 'task_id required'}, 400)
            else:
                self.send_json(get_task_activity(task_id))
        elif p.startswith('/api/scheduler-state/'):
            task_id = p.replace('/api/scheduler-state/', '')
            if not task_id:
                self.send_json({'ok': False, 'error': 'task_id required'}, 400)
            else:
                self.send_json(get_scheduler_state(task_id))
        elif p == '/api/agents-status':
            self.send_json(get_agents_status())
        elif p.startswith('/api/task-output/'):
            task_id = p.replace('/api/task-output/', '')
            if not task_id or not _SAFE_NAME_RE.match(task_id):
                self.send_json({'ok': False, 'error': 'invalid task_id'}, 400)
            else:
                tasks = load_tasks()
                task = next((t for t in tasks if t.get('id') == task_id), None)
                if not task:
                    self.send_json({'ok': False, 'error': 'task not found'}, 404)
                else:
                    output_path = task.get('output', '')
                    if not output_path or output_path == '-':
                        self.send_json({'ok': True, 'taskId': task_id, 'content': '', 'exists': False})
                    else:
                        p_out = pathlib.Path(output_path)
                        if not p_out.exists():
                            self.send_json({'ok': True, 'taskId': task_id, 'content': '', 'exists': False})
                        else:
                            try:
                                content = p_out.read_text(encoding='utf-8', errors='replace')[:50000]
                                self.send_json({'ok': True, 'taskId': task_id, 'content': content, 'exists': True})
                            except Exception as e:
                                self.send_json({'ok': False, 'error': f'讀取失敗: {e}'}, 500)
        elif p.startswith('/api/agent-activity/'):
            agent_id = p.replace('/api/agent-activity/', '')
            if not agent_id or not _SAFE_NAME_RE.match(agent_id):
                self.send_json({'ok': False, 'error': 'invalid agent_id'}, 400)
            else:
                self.send_json({'ok': True, 'agentId': agent_id, 'activity': get_agent_activity(agent_id)})
        # ── 朝堂議政 ──
        elif p == '/api/court-discuss/list':
            self.send_json({'ok': True, 'sessions': cd_list()})
        elif p == '/api/court-discuss/officials':
            self.send_json({'ok': True, 'officials': CD_PROFILES})
        elif p.startswith('/api/court-discuss/session/'):
            sid = p.replace('/api/court-discuss/session/', '')
            data = cd_get(sid)
            self.send_json(data if data else {'ok': False, 'error': 'session not found'}, 200 if data else 404)
        elif p == '/api/court-discuss/fate':
            self.send_json({'ok': True, 'event': cd_fate()})
        elif self._serve_static(p):
            pass  # 已由 _serve_static 處理 (JS/CSS/圖片等)
        else:
            # SPA fallback：非 /api/ 路徑返回 index.html
            if not p.startswith('/api/'):
                idx = DIST / 'index.html'
                if idx.exists():
                    self.send_file(idx)
                    return
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path).path.rstrip('/')
        length = int(self.headers.get('Content-Length', 0))
        if length > MAX_REQUEST_BODY:
            self.send_json({'ok': False, 'error': f'Request body too large (max {MAX_REQUEST_BODY} bytes)'}, 413)
            return
        raw = self.rfile.read(length) if length else b''
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            self.send_json({'ok': False, 'error': 'invalid JSON'}, 400)
            return

        # ── 認證端點（公開） ──
        if p == '/api/auth/setup':
            pw = body.get('password', '')
            if not isinstance(pw, str) or not pw:
                self.send_json({'ok': False, 'error': '請提供密碼'}, 400)
                return
            self.send_json(setup_password(pw))
            return
        if p == '/api/auth/login':
            pw = body.get('password', '')
            if not isinstance(pw, str) or not pw:
                self.send_json({'ok': False, 'error': '請提供密碼'}, 400)
                return
            if verify_password(pw):
                token = create_token()
                resp = {'ok': True, 'token': token}
                # 同時設置 HttpOnly cookie
                try:
                    body_bytes = json.dumps(resp, ensure_ascii=False).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body_bytes)))
                    self.send_header('Set-Cookie', f'edict_token={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400')
                    cors_headers(self)
                    self.end_headers()
                    self.wfile.write(body_bytes)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send_json({'ok': False, 'error': '密碼錯誤'}, 401)
            return

        # ── 認證檢查 ──
        if self._check_auth():
            return

        if p == '/api/morning-config':
            if not isinstance(body, dict):
                self.send_json({'ok': False, 'error': '請求體必須是 JSON 對象'}, 400)
                return
            allowed_keys = {'categories', 'keywords', 'custom_feeds', 'notification', 'feishu_webhook'}
            unknown = set(body.keys()) - allowed_keys
            if unknown:
                self.send_json({'ok': False, 'error': f'未知字段: {", ".join(unknown)}'}, 400)
                return
            if 'categories' in body and not isinstance(body['categories'], list):
                self.send_json({'ok': False, 'error': 'categories 必須是數組'}, 400)
                return
            if 'keywords' in body and not isinstance(body['keywords'], list):
                self.send_json({'ok': False, 'error': 'keywords 必須是數組'}, 400)
                return
            if 'notification' in body:
                noti = body['notification']
                if not isinstance(noti, dict):
                    self.send_json({'ok': False, 'error': 'notification 必須是對象'}, 400)
                    return
                channel_type = noti.get('channel', 'feishu')
                if channel_type not in NOTIFICATION_CHANNELS:
                    self.send_json({'ok': False, 'error': f'不支持的渠道: {channel_type}'}, 400)
                    return
                webhook = noti.get('webhook', '').strip()
                if webhook:
                    channel_cls = get_channel(channel_type)
                    if channel_cls and not channel_cls.validate_webhook(webhook):
                        self.send_json({'ok': False, 'error': f'{channel_cls.label} Webhook URL 無效'}, 400)
                        return
            webhook_legacy = body.get('feishu_webhook', '').strip()
            if webhook_legacy and 'notification' not in body:
                body['notification'] = {'enabled': True, 'channel': 'feishu', 'webhook': webhook_legacy}
            cfg_path = DATA / 'morning_brief_config.json'
            cfg_path.write_text(json.dumps(body, ensure_ascii=False, indent=2))
            self.send_json({'ok': True, 'message': '訂閱配置已保存'})
            return

        if p == '/api/scheduler-scan':
            threshold_sec = body.get('thresholdSec', 180)
            try:
                result = handle_scheduler_scan(threshold_sec)
                self.send_json(result)
            except Exception as e:
                self.send_json({'ok': False, 'error': f'scheduler scan failed: {e}'}, 500)
            return

        if p == '/api/repair-flow-order':
            try:
                self.send_json(handle_repair_flow_order())
            except Exception as e:
                self.send_json({'ok': False, 'error': f'repair flow order failed: {e}'}, 500)
            return

        if p == '/api/scheduler-retry':
            task_id = body.get('taskId', '').strip()
            reason = body.get('reason', '').strip()
            if not task_id:
                self.send_json({'ok': False, 'error': 'taskId required'}, 400)
                return
            self.send_json(handle_scheduler_retry(task_id, reason))
            return

        if p == '/api/scheduler-escalate':
            task_id = body.get('taskId', '').strip()
            reason = body.get('reason', '').strip()
            if not task_id:
                self.send_json({'ok': False, 'error': 'taskId required'}, 400)
                return
            self.send_json(handle_scheduler_escalate(task_id, reason))
            return

        if p == '/api/scheduler-rollback':
            task_id = body.get('taskId', '').strip()
            reason = body.get('reason', '').strip()
            if not task_id:
                self.send_json({'ok': False, 'error': 'taskId required'}, 400)
                return
            self.send_json(handle_scheduler_rollback(task_id, reason))
            return

        if p == '/api/morning-brief/refresh':
            force = body.get('force', True)  # 從看板手動觸發默認強制
            def do_refresh():
                try:
                    cmd = [python_bin(), str(SCRIPTS / 'fetch_morning_news.py')]
                    if force:
                        cmd.append('--force')
                    subprocess.run(cmd, timeout=120)
                    push_to_feishu()
                except Exception as e:
                    print(f'[refresh error] {e}', file=sys.stderr)
            threading.Thread(target=do_refresh, daemon=True).start()
            self.send_json({'ok': True, 'message': '採集已觸發，約30-60秒後刷新'})
            return

        if p == '/api/add-skill':
            agent_id = body.get('agentId', '').strip()
            skill_name = body.get('skillName', body.get('name', '')).strip()
            desc = body.get('description', '').strip() or skill_name
            trigger = body.get('trigger', '').strip()
            if not agent_id or not skill_name:
                self.send_json({'ok': False, 'error': 'agentId and skillName required'}, 400)
                return
            result = add_skill_to_agent(agent_id, skill_name, desc, trigger)
            self.send_json(result)
            return

        if p == '/api/add-remote-skill':
            agent_id = body.get('agentId', '').strip()
            skill_name = body.get('skillName', '').strip()
            source_url = body.get('sourceUrl', '').strip()
            description = body.get('description', '').strip()
            if not agent_id or not skill_name or not source_url:
                self.send_json({'ok': False, 'error': 'agentId, skillName, and sourceUrl required'}, 400)
                return
            result = add_remote_skill(agent_id, skill_name, source_url, description)
            self.send_json(result)
            return

        if p == '/api/remote-skills-list':
            result = get_remote_skills_list()
            self.send_json(result)
            return

        if p == '/api/update-remote-skill':
            agent_id = body.get('agentId', '').strip()
            skill_name = body.get('skillName', '').strip()
            if not agent_id or not skill_name:
                self.send_json({'ok': False, 'error': 'agentId and skillName required'}, 400)
                return
            result = update_remote_skill(agent_id, skill_name)
            self.send_json(result)
            return

        if p == '/api/remove-remote-skill':
            agent_id = body.get('agentId', '').strip()
            skill_name = body.get('skillName', '').strip()
            if not agent_id or not skill_name:
                self.send_json({'ok': False, 'error': 'agentId and skillName required'}, 400)
                return
            result = remove_remote_skill(agent_id, skill_name)
            self.send_json(result)
            return

        if p == '/api/task-action':
            task_id = body.get('taskId', '').strip()
            action = body.get('action', '').strip()  # stop, cancel, resume
            reason = body.get('reason', '').strip() or f'皇上從看板{action}'
            if not task_id or action not in ('stop', 'cancel', 'resume'):
                self.send_json({'ok': False, 'error': 'taskId and action(stop/cancel/resume) required'}, 400)
                return
            result = handle_task_action(task_id, action, reason)
            self.send_json(result)
            return

        if p == '/api/archive-task':
            task_id = body.get('taskId', '').strip() if body.get('taskId') else ''
            archived = body.get('archived', True)
            archive_all = body.get('archiveAllDone', False)
            if not task_id and not archive_all:
                self.send_json({'ok': False, 'error': 'taskId or archiveAllDone required'}, 400)
                return
            result = handle_archive_task(task_id, archived, archive_all)
            self.send_json(result)
            return

        if p == '/api/task-todos':
            task_id = body.get('taskId', '').strip()
            todos = body.get('todos', [])  # [{id, title, status}]
            if not task_id:
                self.send_json({'ok': False, 'error': 'taskId required'}, 400)
                return
            # todos 輸入校驗
            if not isinstance(todos, list) or len(todos) > 200:
                self.send_json({'ok': False, 'error': 'todos must be a list (max 200 items)'}, 400)
                return
            valid_statuses = {'not-started', 'in-progress', 'completed'}
            for td in todos:
                if not isinstance(td, dict) or 'id' not in td or 'title' not in td:
                    self.send_json({'ok': False, 'error': 'each todo must have id and title'}, 400)
                    return
                if td.get('status', 'not-started') not in valid_statuses:
                    td['status'] = 'not-started'
            result = update_task_todos(task_id, todos)
            self.send_json(result)
            return

        if p == '/api/create-task':
            title = body.get('title', '').strip()
            org = body.get('org', '中書省').strip()
            official = body.get('official', '中書令').strip()
            priority = body.get('priority', 'normal').strip()
            template_id = body.get('templateId', '')
            params = body.get('params', {})
            if not title:
                self.send_json({'ok': False, 'error': 'title required'}, 400)
                return
            target_dept = body.get('targetDept', '').strip()
            result = handle_create_task(title, org, official, priority, template_id, params, target_dept)
            self.send_json(result)
            return

        if p == '/api/review-action':
            task_id = body.get('taskId', '').strip()
            action = body.get('action', '').strip()  # approve, reject
            comment = body.get('comment', '').strip()
            if not task_id or action not in ('approve', 'reject'):
                self.send_json({'ok': False, 'error': 'taskId and action(approve/reject) required'}, 400)
                return
            result = handle_review_action(task_id, action, comment)
            self.send_json(result)
            return

        if p == '/api/advance-state':
            task_id = body.get('taskId', '').strip()
            comment = body.get('comment', '').strip()
            if not task_id:
                self.send_json({'ok': False, 'error': 'taskId required'}, 400)
                return
            result = handle_advance_state(task_id, comment)
            self.send_json(result)
            return

        if p == '/api/agent-wake':
            agent_id = body.get('agentId', '').strip()
            message = body.get('message', '').strip()
            if not agent_id:
                self.send_json({'ok': False, 'error': 'agentId required'}, 400)
                return
            result = wake_agent(agent_id, message)
            self.send_json(result)
            return

        if p == '/api/set-model':
            agent_id = body.get('agentId', '').strip()
            model = body.get('model', '').strip()
            if not agent_id or not model:
                self.send_json({'ok': False, 'error': 'agentId and model required'}, 400)
                return

            # Write to pending (atomic)
            pending_path = DATA / 'pending_model_changes.json'
            def update_pending(current):
                current = [x for x in current if x.get('agentId') != agent_id]
                current.append({'agentId': agent_id, 'model': model})
                return current
            atomic_json_update(pending_path, update_pending, [])

            # Async apply
            def apply_async():
                try:
                    subprocess.run([python_bin(), str(SCRIPTS / 'apply_model_changes.py')], timeout=30)
                    subprocess.run([python_bin(), str(SCRIPTS / 'sync_agent_config.py')], timeout=10)
                except Exception as e:
                    print(f'[apply error] {e}', file=sys.stderr)

            threading.Thread(target=apply_async, daemon=True).start()
            self.send_json({'ok': True, 'message': f'Queued: {agent_id} → {model}'})

        # Fix #139: 設置派發渠道（feishu/telegram/wecom/signal/tui）
        elif p == '/api/set-dispatch-channel':
            channel = body.get('channel', '').strip()
            allowed = {'feishu', 'telegram', 'wecom', 'signal', 'tui', 'discord', 'slack'}
            if not channel or channel not in allowed:
                self.send_json({'ok': False, 'error': f'channel must be one of: {", ".join(sorted(allowed))}'}, 400)
                return
            def _set_channel(cfg):
                cfg['dispatchChannel'] = channel
                return cfg
            atomic_json_update(DATA / 'agent_config.json', _set_channel, {})
            self.send_json({'ok': True, 'message': f'派發渠道已切換爲 {channel}'})

        # ── 朝堂議政 POST ──
        elif p == '/api/court-discuss/start':
            topic = body.get('topic', '').strip()
            officials = body.get('officials', [])
            task_id = body.get('taskId', '').strip()
            if not topic:
                self.send_json({'ok': False, 'error': 'topic required'}, 400)
                return
            if not officials or not isinstance(officials, list):
                self.send_json({'ok': False, 'error': 'officials list required'}, 400)
                return
            # 校驗官員 ID
            valid_ids = set(CD_PROFILES.keys())
            officials = [o for o in officials if o in valid_ids]
            if len(officials) < 2:
                self.send_json({'ok': False, 'error': '至少選擇2位官員'}, 400)
                return
            self.send_json(cd_create(topic, officials, task_id))

        elif p == '/api/court-discuss/advance':
            sid = body.get('sessionId', '').strip()
            user_msg = body.get('userMessage', '').strip() or None
            decree = body.get('decree', '').strip() or None
            if not sid:
                self.send_json({'ok': False, 'error': 'sessionId required'}, 400)
                return
            self.send_json(cd_advance(sid, user_msg, decree))

        elif p == '/api/court-discuss/conclude':
            sid = body.get('sessionId', '').strip()
            if not sid:
                self.send_json({'ok': False, 'error': 'sessionId required'}, 400)
                return
            self.send_json(cd_conclude(sid))

        elif p == '/api/court-discuss/destroy':
            sid = body.get('sessionId', '').strip()
            if sid:
                cd_destroy(sid)
            self.send_json({'ok': True})

        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description='三省六部看板服務器')
    parser.add_argument('--port', type=int, default=7891)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--cors', default=None, help='Allowed CORS origin (default: reflect request Origin header)')
    args = parser.parse_args()

    global ALLOWED_ORIGIN, _DASHBOARD_PORT, _DEFAULT_ORIGINS
    ALLOWED_ORIGIN = args.cors
    _DASHBOARD_PORT = args.port
    _DEFAULT_ORIGINS = _DEFAULT_ORIGINS | {
        f'http://127.0.0.1:{args.port}', f'http://localhost:{args.port}',
    }

    server = HTTPServer((args.host, args.port), Handler)
    log.info(f'三省六部看板啓動 → http://{args.host}:{args.port}')
    print(f'   按 Ctrl+C 停止')

    auth_init(DATA)
    if auth_enabled():
        log.info('🔒 JWT 認證已啓用')
    else:
        log.info('🔓 認證未配置，所有 API 公開訪問（POST /api/auth/setup 設置密碼）')

    migrate_notification_config()

    # 啓動恢復：重新派發上次被 kill 中斷的 queued 任務
    threading.Timer(3.0, _startup_recover_queued_dispatches).start()

    # 定時巡檢：每 120 秒自動掃描停滯任務並觸發重試/升級/回滾
    def _periodic_scheduler_scan():
        while True:
            try:
                import time as _time
                _time.sleep(120)
                result = handle_scheduler_scan(threshold_sec=180)
                count = result.get('count', 0) if isinstance(result, dict) else 0
                if count > 0:
                    log.info(f'🔍 定時巡檢：{count} 個動作')
            except Exception as e:
                log.warning(f'定時巡檢異常: {e}')
    threading.Thread(target=_periodic_scheduler_scan, daemon=True).start()
    log.info('🔍 定時巡檢已啓動（每120秒）')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')


if __name__ == '__main__':
    main()
