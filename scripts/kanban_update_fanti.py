#!/usr/bin/env python3
"""
看板任務更新工具 - 供各省部 Agent 調用

本工具操作 data/tasks_source.json（JSON 看板模式）。
如果您已部署 edict/backend（Postgres + Redis 事件總線模式），
請使用 edict/backend API 端點代替本腳本，或運行遷移腳本：
  python3 edict/migration/migrate_json_to_pg.py

兩種模式互相獨立，數據不會自動同步。

用法:
  # 新建任務（收旨時）
  python3 kanban_update.py create JJC-20260223-012 "任務標題" Zhongshu 中書省 中書令

  # 更新狀態
  python3 kanban_update.py state JJC-20260223-012 Menxia "規劃方案已提交門下省"

  # 添加流轉記錄
  python3 kanban_update.py flow JJC-20260223-012 "中書省" "門下省" "規劃方案提交審核"

  # 完成任務
  python3 kanban_update.py done JJC-20260223-012 "/path/to/output" "任務完成摘要"

  # 添加/更新子任務 todo
  python3 kanban_update.py todo JJC-20260223-012 1 "實現API接口" in-progress
  python3 kanban_update.py todo JJC-20260223-012 1 "" completed

  # 🔥 實時進展匯報（Agent 主動調用，頻率不限）
  python3 kanban_update.py progress JJC-20260223-012 "正在分析需求，擬定3個子方案" "1.調研技術選型|2.撰寫設計文檔|3.實現原型"
"""
import datetime
import json, pathlib, sys, subprocess, logging, os, re

_BASE = pathlib.Path(os.environ['EDICT_HOME']) if 'EDICT_HOME' in os.environ else pathlib.Path(__file__).resolve().parent.parent
TASKS_FILE = _BASE / 'data' / 'tasks_source.json'
REFRESH_SCRIPT = _BASE / 'scripts' / 'refresh_live_data.py'

# ── 統一派發模組 ──────────────────────────────────────────
# 封裝統一派發邏輯，確保 kanban_update.py 與 Dashboard Server 動作一致
sys.path.insert(0, str(_BASE / 'scripts'))
from dispatch import dispatch_for_state

# 方便 dispatch_for_state 內部讀取 task 資料
def _reload_task(task_id):
    tasks = atomic_json_read(TASKS_FILE)
    return next((t for t in tasks if t.get('id') == task_id), None)

log = logging.getLogger('kanban')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

# 文件鎖 —— 防止多 Agent 同時讀寫 tasks_source.json
from file_lock import atomic_json_read, atomic_json_update  # noqa: E402
from utils import now_iso  # noqa: E402


# ── 從 task.py 動態加載權威狀態轉換表（Single Source of Truth）──
def _load_canonical_transitions() -> dict:
    """從 edict/backend 源碼解析狀態轉換表，無需 import（避免 SQLAlchemy 依賴）。"""
    task_py = _BASE / "edict" / "backend" / "app" / "models" / "task.py"
    source = task_py.read_text(encoding="utf-8")

    m = re.search(r"STATE_TRANSITIONS\s*=\s*\{", source)
    if not m:
        return None
    start = m.start()
    depth = 0
    end = start
    for i, ch in enumerate(source[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    block = source[start:end]
    cleaned = re.sub(r"TaskState\.(\w+)", r'"\1"', block)
    cleaned = cleaned.replace("STATE_TRANSITIONS =", "_result =")
    local_ns = {}
    exec(cleaned, {}, local_ns)  # noqa: S102
    return local_ns["_result"]


STATE_ORG_MAP = {
    'Taizi': '太子', 'Zhongshu': '中書省', 'Menxia': '門下省',
    'Assigned': '尚書省', 'Next': '尚書省',
    'Doing': '執行中', 'Review': '尚書省', 'Done': '完成', 'Blocked': '阻塞',
    'PendingConfirm': '尚書省', 'Pending': '中書省',
}

_STATE_AGENT_MAP = {
    'Taizi': 'taizi',
    'Zhongshu': 'zhongshu',
    'Menxia': 'menxia',
    'Assigned': 'shangshu',
    'Review': 'shangshu',
    'Pending': 'zhongshu',
    'PendingConfirm': 'shangshu',
}

_ORG_AGENT_MAP = {
    '禮部': 'libu', '戶部': 'hubu', '兵部': 'bingbu',
    '刑部': 'xingbu', '工部': 'gongbu', '吏部': 'libu_hr',
    '中書省': 'zhongshu', '門下省': 'menxia', '尚書省': 'shangshu',
}

_AGENT_LABELS = {
    'main': '太子', 'taizi': '太子',
    'zhongshu': '中書省', 'menxia': '門下省', 'shangshu': '尚書省',
    'libu': '禮部', 'hubu': '戶部', 'bingbu': '兵部', 'xingbu': '刑部',
    'gongbu': '工部', 'libu_hr': '吏部', 'zaochao': '欽天監',
}

MAX_PROGRESS_LOG = 100  # 單任務最大進展日誌條數

def load():
    return atomic_json_read(TASKS_FILE, [])

_REFRESH_SIGNAL_FILE = _BASE / 'data' / '.refresh_pending'

def _trigger_refresh():
    """Debounced refresh — touch 信號文件，由獨立 watcher 合併執行。
    
    替代原來每次 fork subprocess 的方式，避免多 Agent 並發時產生數百個進程。
    如果 refresh_watcher 未運行，會 fallback 到直接 fork（保持向後兼容）。
    """
    try:
        _REFRESH_SIGNAL_FILE.touch(exist_ok=True)
    except Exception:
        pass
    # Fallback: 如果信號文件 3 秒後仍存在（watcher 沒在運行），直接 fork
    # 注意：這個 fallback 只在非 watcher 部署場景觸發
    if not (_BASE / 'data' / '.refresh_watcher_pid').exists():
        try:
            subprocess.Popen(['python3', str(REFRESH_SCRIPT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


# ── 審計日誌 ──
AUDIT_FILE = _BASE / 'data' / 'audit_log.json'
MAX_AUDIT_LOG = 5000  # 審計日誌最大條數

def _append_audit(task_id, agent, action, old_val=None, new_val=None, reason=""):
    """追加一條審計記錄到 data/audit_log.json（原子操作）。"""
    entry = {
        "ts": now_iso(),
        "task": task_id or "",
        "agent": agent or "",
        "action": action,
        "from": old_val,
        "to": new_val,
        "reason": reason,
    }
    try:
        def modifier(logs):
            if logs is None:
                logs = []
            logs.append(entry)
            if len(logs) > MAX_AUDIT_LOG:
                logs = logs[-MAX_AUDIT_LOG:]
            return logs
        atomic_json_update(AUDIT_FILE, modifier, [])
    except Exception as e:
        log.warning(f"審計日誌寫入失敗: {e}")


# ── 越權檢測（Agent 權限策略）──
AGENT_POLICY = {
    "taizi":    {"role": "coordination", "commands": {"create", "state", "flow", "progress", "todo", "memory", "task-memo"}},
    "zhongshu": {"role": "coordination", "commands": {"state", "flow", "progress", "todo", "memory", "task-memo", "delegate"}},
    "menxia":   {"role": "coordination", "commands": {"state", "flow", "progress", "todo", "confirm", "memory", "task-memo"}},
    "shangshu": {"role": "coordination", "commands": {"state", "flow", "progress", "todo", "confirm", "delegate", "memory", "task-memo", "shared-memo"}},
    "zaochao":  {"role": "coordination", "commands": {"progress", "todo", "memory"}},
    "hubu":     {"role": "execution", "commands": {"progress", "todo", "done", "block", "memory", "task-memo", "delegate-result"}},
    "libu":     {"role": "execution", "commands": {"progress", "todo", "done", "block", "memory", "task-memo", "delegate-result"}},
    "bingbu":   {"role": "execution", "commands": {"progress", "todo", "done", "block", "memory", "task-memo", "delegate-result"}},
    "xingbu":   {"role": "execution", "commands": {"progress", "todo", "done", "block", "memory", "task-memo", "delegate-result"}},
    "gongbu":   {"role": "execution", "commands": {"progress", "todo", "done", "block", "memory", "task-memo", "delegate-result"}},
    "libu_hr":  {"role": "execution", "commands": {"progress", "todo", "done", "block", "memory", "task-memo", "delegate-result"}},
}

def _check_permission(agent_id, cmd):
    """檢查 Agent 是否有權執行該命令。未知 Agent 不攔截（向前兼容）。"""
    if not agent_id:
        return  # 無法推斷 Agent 身份時不攔截
    policy = AGENT_POLICY.get(agent_id)
    if policy is None:
        return  # 未註冊的 Agent 不攔截
    if cmd not in policy["commands"]:
        _append_audit(None, agent_id, "permission_denied", cmd, None, f"{agent_id} 越權執行 {cmd}")
        log.warning(f"⛔ {agent_id} 無權執行 {cmd}（允許: {policy['commands']}）")
        print(f"[看板] 越權拒絕: {agent_id} 不可執行 {cmd}", flush=True)
        sys.exit(1)


def find_task(tasks, task_id):
    return next((t for t in tasks if t.get('id') == task_id), None)


# 旨意標題最低要求
_MIN_TITLE_LEN = 6
_JUNK_TITLES = {
    '?', '？', '好', '好的', '是', '否', '不', '不是', '對', '了解', '收到',
    '嗯', '哦', '知道了', '開啓了麼', '可以', '不行', '行', 'ok', 'yes', 'no',
    '你去開啓', '測試', '試試', '看看',
}

def _sanitize_text(raw, max_len=80):
    """清洗文本：剝離文件路徑、URL、Conversation 元數據、傳旨前綴、截斷過長內容。"""
    t = (raw or '').strip()
    # 1) 剝離 Conversation info / Conversation 後面的所有內容
    t = re.split(r'\n*Conversation\b', t, maxsplit=1)[0].strip()
    # 2) 剝離 ```json 代碼塊
    t = re.split(r'\n*```', t, maxsplit=1)[0].strip()
    # 3) 剝離 Unix/Mac 文件路徑 (/Users/xxx, /home/xxx, /opt/xxx, ./xxx)
    t = re.sub(r'[/\\.~][A-Za-z0-9_\-./]+(?:\.(?:py|js|ts|json|md|sh|yaml|yml|txt|csv|html|css|log))?', '', t)
    # 4) 剝離 URL
    t = re.sub(r'https?://\S+', '', t)
    # 5) 清理常見前綴: "傳旨:" "下旨:" "下旨（xxx）:" 等
    t = re.sub(r'^(傳旨|下旨)([（(][^)）]*[)）])?[：:\uff1a]\s*', '', t)
    # 6) 剝離系統元數據關鍵詞
    t = re.sub(r'(message_id|session_id|chat_id|open_id|user_id|tenant_key)\s*[:=]\s*\S+', '', t)
    # 7) 合併多餘空白
    t = re.sub(r'\s+', ' ', t).strip()
    # 8) 截斷過長內容
    if len(t) > max_len:
        t = t[:max_len] + '…'
    return t


def _sanitize_title(raw):
    """清洗標題（最長 80 字符）。"""
    return _sanitize_text(raw, 80)


def _sanitize_remark(raw):
    """清洗流轉備註（最長 120 字符）。"""
    return _sanitize_text(raw, 120)


def _todo_counts(task):
    """返回 (completed, total) 便於完成態校驗。"""
    todos = task.get('todos') or []
    total = len(todos)
    completed = sum(1 for td in todos if td.get('status') == 'completed')
    return completed, total


def _infer_agent_id_from_runtime(task=None):
    """儘量推斷當前執行該命令的 Agent。"""
    for k in ('OPENCLAW_AGENT_ID', 'OPENCLAW_AGENT', 'AGENT_ID'):
        v = (os.environ.get(k) or '').strip()
        if v:
            return v

    cwd = str(pathlib.Path.cwd())
    m = re.search(r'workspace-([a-zA-Z0-9_\-]+)', cwd)
    if m:
        return m.group(1)

    fpath = str(pathlib.Path(__file__).resolve())
    m2 = re.search(r'workspace-([a-zA-Z0-9_\-]+)', fpath)
    if m2:
        return m2.group(1)

    if task:
        state = task.get('state', '')
        org = task.get('org', '')
        aid = _STATE_AGENT_MAP.get(state)
        if aid is None and state in ('Doing', 'Next'):
            aid = _ORG_AGENT_MAP.get(org)
        if aid:
            return aid
    return ''


def _is_valid_task_title(title):
    """校驗標題是否足夠作爲一個旨意任務。"""
    t = (title or '').strip()
    if len(t) < _MIN_TITLE_LEN:
        return False, f'標題過短（{len(t)}<{_MIN_TITLE_LEN}字），疑似非旨意'
    if t.lower() in _JUNK_TITLES:
        return False, f'標題 "{t}" 不是有效旨意'
    # 純標點或問號
    if re.fullmatch(r'[\s?？!！.。,，…·\-—~]+', t):
        return False, '標題只有標點符號'
    # 看起來像文件路徑
    if re.match(r'^[/\\~.]', t) or re.search(r'/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+', t):
        return False, f'標題看起來像文件路徑，請用中文概括任務'
    # 只剩標點和空白（清洗後可能變空）
    if re.fullmatch(r'[\s\W]*', t):
        return False, '標題清洗後爲空'
    return True, ''


def cmd_create(task_id, title, state, org, official, remark=None, source=None):
    """新建任務（收旨時立即調用）"""
    # 清洗標題（剝離元數據）
    title = _sanitize_title(title)
    # 旨意標題校驗
    valid, reason = _is_valid_task_title(title)
    if not valid:
        log.warning(f'⚠️ 拒絕創建 {task_id}：{reason}')
        print(f'[看板] 拒絕創建：{reason}', flush=True)
        return
    actual_org = STATE_ORG_MAP.get(state, org)
    clean_remark = _sanitize_remark(remark) if remark else f"下旨：{title}"
    # 解析 source（格式：telegram:493683906 或 feishu:xxx）
    source_info = None
    if source:
        parts = source.split(':', 1)
        source_info = {"channel": parts[0], "target": parts[1] if len(parts) > 1 else None}
    def modifier(tasks):
        existing = next((t for t in tasks if t.get('id') == task_id), None)
        if existing:
            if existing.get('state') in ('Done', 'Cancelled'):
                log.warning(f'⚠️ 任務 {task_id} 已完結 (state={existing["state"]})，不可覆蓋')
                return tasks
            if existing.get('state') not in (None, '', 'Inbox', 'Pending'):
                log.warning(f'任務 {task_id} 已存在 (state={existing["state"]})，將被覆蓋')
        tasks = [t for t in tasks if t.get('id') != task_id]
        task_entry = {
            "id": task_id, "title": title, "official": official,
            "org": actual_org, "state": state,
            "now": clean_remark[:60] if remark else f"已下旨，等待{actual_org}接旨",
            "eta": "-", "block": "無", "output": "", "ac": "",
            "flow_log": [{"at": now_iso(), "from": "皇上", "to": actual_org, "remark": clean_remark}],
            "updatedAt": now_iso()
        }
        if source_info:
            task_entry["source"] = source_info
        tasks.insert(0, task_entry)
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    task = _reload_task(task_id)
    if task:
        dispatch_for_state(task_id, task, state, trigger='create')
    log.info(f'✅ 創建 {task_id} | {title[:30]} | state={state}')
    _append_audit(task_id, _infer_agent_id_from_runtime(), 'create', None, state, title)


# ── 狀態流轉合法性校驗 ──
# 從 task.py 動態加載（如果 edict 目錄存在），否則使用內置 fallback
_edict_task_path = _BASE / "edict" / "backend" / "app" / "models" / "task.py"
if _edict_task_path.exists():
    _VALID_TRANSITIONS = _load_canonical_transitions()
else:
    # Fallback：當 edict 目錄不存在時使用內置定義（必須與 task.py 保持一致）
    _VALID_TRANSITIONS = {
        'Pending':        {'Taizi', 'Cancelled'},
        'Taizi':          {'Zhongshu', 'Cancelled'},
        'Zhongshu':       {'Menxia', 'Cancelled', 'Blocked'},
        'Menxia':         {'Assigned', 'Zhongshu', 'Cancelled'},
        'Assigned':       {'Doing', 'Next', 'Blocked', 'Cancelled'},
        'Next':           {'Doing', 'Blocked', 'Cancelled'},
        'Doing':          {'Review', 'Done', 'Blocked', 'Cancelled'},
        'Review':         {'Done', 'Menxia', 'Doing', 'Cancelled', 'PendingConfirm'},
        'PendingConfirm': {'Done', 'Review', 'Cancelled'},
        'Blocked':        {'Taizi', 'Zhongshu', 'Menxia', 'Assigned', 'Next', 'Doing', 'Review', 'Cancelled'},
        'Done':           set(),
        'Cancelled':      set(),
    }


# ── 高風險操作確認機制 ──

# 需要進入 PendingConfirm 中間狀態的高風險轉換
HIGH_RISK_TRANSITIONS = {
    ('Review', 'Done'),       # 完結任務 — 需門下省確認
    ('Doing', 'Cancelled'),   # 執行中取消 — 需尚書省確認
    ('Menxia', 'Cancelled'),  # 審核中取消 — 需中書省確認
}

# 各狀態的確認權限方
CONFIRM_AUTHORITY = {
    'Review': 'menxia',
    'Doing': 'shangshu',
    'Menxia': 'zhongshu',
}


def cmd_state(task_id, new_state, now_text=None):
    """更新任務狀態（原子操作，含流轉合法性校驗 + 高風險攔截）"""
    old_state = [None]
    rejected = [False]
    pending_confirm = [False]
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任務 {task_id} 不存在')
            return tasks
        old_state[0] = t['state']
        allowed = _VALID_TRANSITIONS.get(old_state[0])
        if allowed is not None and new_state not in allowed:
            log.warning(f'⚠️ 非法狀態轉換 {task_id}: {old_state[0]} → {new_state}（允許: {allowed}）')
            rejected[0] = True
            return tasks
        # 高風險操作攔截 → 進入 PendingConfirm
        if (old_state[0], new_state) in HIGH_RISK_TRANSITIONS:
            t['state'] = 'PendingConfirm'
            t['org'] = STATE_ORG_MAP.get('PendingConfirm', t.get('org', ''))
            t['pending_confirm'] = {
                'target_state': new_state,
                'requested_by': _infer_agent_id_from_runtime(t),
                'requested_at': now_iso(),
                'confirm_by': CONFIRM_AUTHORITY.get(old_state[0], 'shangshu'),
            }
            t['now'] = f'待確認: {old_state[0]}→{new_state}'
            t['updatedAt'] = now_iso()
            pending_confirm[0] = True
            return tasks
        t['state'] = new_state
        if new_state in STATE_ORG_MAP:
            t['org'] = STATE_ORG_MAP[new_state]
        if now_text:
            t['now'] = now_text
        t['updatedAt'] = now_iso()
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    if rejected[0]:
        log.info(f'❌ {task_id} 狀態轉換被拒: {old_state[0]} → {new_state}')
        _append_audit(task_id, _infer_agent_id_from_runtime(), 'state_rejected', old_state[0], new_state, '非法狀態轉換')
    elif pending_confirm[0]:
        log.info(f'⏳ {task_id} 高風險操作 {old_state[0]}→{new_state}，進入 PendingConfirm 待確認')
        _append_audit(task_id, _infer_agent_id_from_runtime(), 'pending_confirm', old_state[0], new_state, f'需 {CONFIRM_AUTHORITY.get(old_state[0], "shangshu")} 確認')
    else:
        log.info(f'✅ {task_id} 狀態更新: {old_state[0]} → {new_state}')
        _append_audit(task_id, _infer_agent_id_from_runtime(), 'state', old_state[0], new_state, now_text or '')
        task = _reload_task(task_id)
        if task:
            dispatch_for_state(task_id, task, new_state, 'state')


def cmd_flow(task_id, from_dept, to_dept, remark):
    """添加流轉記錄（原子操作）"""
    clean_remark = _sanitize_remark(remark)
    agent_id = _infer_agent_id_from_runtime()
    agent_label = _AGENT_LABELS.get(agent_id, agent_id)
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任務 {task_id} 不存在')
            return tasks
        t.setdefault('flow_log', []).append({
            "at": now_iso(), "from": from_dept, "to": to_dept, "remark": clean_remark,
            "agent": agent_id, "agentLabel": agent_label,
        })
        # 同步更新 org，使看板能正確顯示當前所屬部門
        t['org'] = to_dept
        t['updatedAt'] = now_iso()
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    log.info(f'✅ {task_id} 流轉記錄: {from_dept} → {to_dept}')
    _append_audit(task_id, _infer_agent_id_from_runtime(), 'flow', from_dept, to_dept, clean_remark)


def cmd_done(task_id, output_path='', summary=''):
    """執行部門回報完成，任務進入 Review 待尚書省匯總審查。"""
    rejected = [False]
    reject_reason = ['']
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任務 {task_id} 不存在')
            return tasks
        old_state = t.get('state')
        if old_state not in ('Doing', 'Next'):
            rejected[0] = True
            reject_reason[0] = f'當前狀態 {old_state} 不允許直接上報完成'
            return tasks
        completed, total = _todo_counts(t)
        if total > 0 and completed < total:
            rejected[0] = True
            reject_reason[0] = f'todos 未完成（{completed}/{total}），禁止直接收口'
            return tasks

        from_org = t.get('org', '執行部門')
        t['state'] = 'Review'
        t['org'] = STATE_ORG_MAP.get('Review', t.get('org', ''))
        t['output'] = output_path
        t['now'] = summary or '執行已完成，提交尚書省匯總審查'
        t.setdefault('flow_log', []).append({
            "at": now_iso(), "from": from_org,
            "to": "尚書省", "remark": f"✅ 執行完成，提交審查：{summary or '待尚書省匯總'}"
        })
        # 同步設置 outputMeta，避免依賴 refresh_live_data.py 異步補充
        if output_path:
            p = pathlib.Path(output_path)
            if p.exists():
                ts = datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                t['outputMeta'] = {"exists": True, "lastModified": ts}
            else:
                t['outputMeta'] = {"exists": False, "lastModified": None}
        t['updatedAt'] = now_iso()
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    if rejected[0]:
        log.warning(f'⚠️ {task_id} done 被拒絕：{reject_reason[0]}')
        _append_audit(task_id, _infer_agent_id_from_runtime(), 'done_rejected', None, 'Review', reject_reason[0])
        return
    log.info(f'✅ {task_id} 執行完成，已提交尚書省審查')
    _append_audit(task_id, _infer_agent_id_from_runtime(), 'done', None, 'Review', summary or '')
    task = _reload_task(task_id)
    if task:
        dispatch_for_state(task_id, task, 'Review', 'done')


def cmd_block(task_id, reason):
    """標記阻塞（原子操作）"""
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任務 {task_id} 不存在')
            return tasks
        t['state'] = 'Blocked'
        t['block'] = reason
        t['updatedAt'] = now_iso()
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    log.warning(f'⚠️ {task_id} 已阻塞: {reason}')
    _append_audit(task_id, _infer_agent_id_from_runtime(), 'block', None, 'Blocked', reason)


def cmd_confirm(task_id, action, reason=''):
    """確認或駁回 PendingConfirm 狀態的高風險操作。

    action: approve / reject
    """
    result_state = [None]
    rejected = [False]
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任務 {task_id} 不存在')
            return tasks
        if t.get('state') != 'PendingConfirm':
            log.warning(f'⚠️ {task_id} 不在 PendingConfirm 狀態 (當前: {t.get("state")})')
            rejected[0] = True
            return tasks
        pending = t.get('pending_confirm', {})
        if action == 'approve':
            target = pending.get('target_state', 'Done')
            t['state'] = target
            if target in STATE_ORG_MAP:
                t['org'] = STATE_ORG_MAP[target]
            t['now'] = reason or f'確認通過 → {target}'
            result_state[0] = target
        elif action == 'reject':
            # 駁回 → 回到 Review
            t['state'] = 'Review'
            t['org'] = STATE_ORG_MAP.get('Review', t.get('org', ''))
            t['now'] = reason or '確認被駁回，退回覆審'
            result_state[0] = 'Review'
        else:
            log.error(f'未知 confirm 操作: {action}')
            rejected[0] = True
            return tasks
        t.pop('pending_confirm', None)
        t['updatedAt'] = now_iso()
        t.setdefault('flow_log', []).append({
            'at': now_iso(), 'from': 'PendingConfirm', 'to': result_state[0],
            'remark': f'{"✅ 批准" if action == "approve" else "❌ 駁回"}: {reason}',
        })
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    if rejected[0]:
        log.info(f'❌ {task_id} confirm 操作失敗')
    else:
        log.info(f'✅ {task_id} confirm {action} → {result_state[0]}')
    _append_audit(task_id, _infer_agent_id_from_runtime(), f'confirm_{action}', 'PendingConfirm', result_state[0], reason)


def cmd_progress(task_id, now_text, todos_pipe='', tokens=0, cost=0.0, elapsed=0):
    """🔥 實時進展匯報 — Agent 主動調用，不改變狀態，只更新 now + todos

    now_text: 當前正在做什麼的一句話描述（必填）
    todos_pipe: 可選，用 | 分隔的 todo 列表，格式：
        "已完成的事項✅|正在做的事項🔄|計劃做的事項"
        - 以 ✅ 結尾 → completed
        - 以 🔄 結尾 → in-progress
        - 其他 → not-started
    tokens: 可選，本次消耗的 token 數
    cost: 可選，本次成本（美元）
    elapsed: 可選，本次耗時（秒）
    """
    clean = _sanitize_remark(now_text)
    # 解析 todos_pipe
    parsed_todos = None
    if todos_pipe:
        new_todos = []
        for i, item in enumerate(todos_pipe.split('|'), 1):
            item = item.strip()
            if not item:
                continue
            if item.endswith('✅'):
                status = 'completed'
                title = item[:-1].strip()
            elif item.endswith('🔄'):
                status = 'in-progress'
                title = item[:-1].strip()
            else:
                status = 'not-started'
                title = item
            new_todos.append({'id': str(i), 'title': title, 'status': status})
        if new_todos:
            parsed_todos = new_todos

    # 解析資源消耗參數
    try:
        tokens = int(tokens) if tokens else 0
    except (ValueError, TypeError):
        tokens = 0
    try:
        cost = float(cost) if cost else 0.0
    except (ValueError, TypeError):
        cost = 0.0
    try:
        elapsed = int(elapsed) if elapsed else 0
    except (ValueError, TypeError):
        elapsed = 0

    done_cnt = [0]
    total_cnt = [0]
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任務 {task_id} 不存在')
            return tasks
        t['now'] = clean
        if parsed_todos is not None:
            t['todos'] = parsed_todos
        # 多 Agent 並行進展日誌
        at = now_iso()
        agent_id = _infer_agent_id_from_runtime(t)
        agent_label = _AGENT_LABELS.get(agent_id, agent_id)
        log_todos = parsed_todos if parsed_todos is not None else t.get('todos', [])
        log_entry = {
            'at': at, 'agent': agent_id, 'agentLabel': agent_label,
            'text': clean, 'todos': log_todos,
            'state': t.get('state', ''), 'org': t.get('org', ''),
        }
        # 資源消耗（可選字段，有值才寫入）
        if tokens > 0:
            log_entry['tokens'] = tokens
        if cost > 0:
            log_entry['cost'] = cost
        if elapsed > 0:
            log_entry['elapsed'] = elapsed
        t.setdefault('progress_log', []).append(log_entry)
        # 限制 progress_log 大小，防止無限增長
        if len(t['progress_log']) > MAX_PROGRESS_LOG:
            t['progress_log'] = t['progress_log'][-MAX_PROGRESS_LOG:]
        t['updatedAt'] = at
        done_cnt[0] = sum(1 for td in t.get('todos', []) if td.get('status') == 'completed')
        total_cnt[0] = len(t.get('todos', []))
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    res_info = ''
    if tokens or cost or elapsed:
        res_info = f' [res: {tokens}tok/${cost:.4f}/{elapsed}s]'
    log.info(f'📡 {task_id} 進展: {clean[:40]}... [{done_cnt[0]}/{total_cnt[0]}]{res_info}')
    _append_audit(task_id, _infer_agent_id_from_runtime(), 'progress', None, None, clean)

def cmd_todo(task_id, todo_id, title, status='not-started', detail=''):
    """添加或更新子任務 todo（原子操作）

    status: not-started / in-progress / completed
    detail: 可選，該子任務的詳細產出/說明（Markdown 格式）

    約束：同一時刻最多只有 1 個 in-progress 狀態的 todo。
    """
    # 校驗 status 值
    if status not in ('not-started', 'in-progress', 'completed'):
        status = 'not-started'
    result_info = [0, 0]
    rejected = [False]
    ready_to_close = [False]
    def modifier(tasks):
        t = find_task(tasks, task_id)
        if not t:
            log.error(f'任務 {task_id} 不存在')
            return tasks
        if 'todos' not in t:
            t['todos'] = []

        # 單一 in-progress 約束
        if status == 'in-progress':
            existing_ip = [td for td in t['todos']
                           if td.get('status') == 'in-progress' and str(td.get('id')) != str(todo_id)]
            if existing_ip:
                log.warning(
                    f'⚠️ todo #{existing_ip[0]["id"]} 正在執行中，'
                    f'請先完成或取消後再開始 #{todo_id}'
                )
                rejected[0] = True
                return tasks

        existing = next((td for td in t['todos'] if str(td.get('id')) == str(todo_id)), None)
        if existing:
            existing['status'] = status
            if title:
                existing['title'] = title
            if detail:
                existing['detail'] = detail
        else:
            item = {'id': todo_id, 'title': title, 'status': status}
            if detail:
                item['detail'] = detail
            t['todos'].append(item)
        t['updatedAt'] = now_iso()
        result_info[0] = sum(1 for td in t['todos'] if td.get('status') == 'completed')
        result_info[1] = len(t['todos'])
        # 所有 todo 完成 → 標記 ready_to_close
        if result_info[1] > 0 and result_info[0] == result_info[1]:
            t['ready_to_close'] = True
            ready_to_close[0] = True
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    if rejected[0]:
        log.info(f'❌ {task_id} todo #{todo_id} → in-progress 被拒（已有進行中的 todo）')
        _append_audit(task_id, _infer_agent_id_from_runtime(), 'todo_rejected', todo_id, 'in-progress', 'single in-progress constraint')
        return
    log.info(f'✅ {task_id} todo [{result_info[0]}/{result_info[1]}]: {todo_id} → {status}')
    if ready_to_close[0]:
        log.info(f'🎯 {task_id} 所有子任務完成，ready_to_close=true')
    _append_audit(task_id, _infer_agent_id_from_runtime(), 'todo', todo_id, status, title)


# ── 三級記憶系統 ──

MEMORY_DIR = _BASE / 'data' / 'agent_memory'
TASK_MEMORY_DIR = _BASE / 'data' / 'task_memory'
SHARED_MEMORY_FILE = _BASE / 'data' / 'shared_memory.json'
MAX_AGENT_MEMORIES = 200


def cmd_memory(agent_id, mem_type, content, source_task='', tags=''):
    """寫入 Agent 永久記憶。

    mem_type: feedback | experience | preference
    tags: 逗號分隔的相關性標籤
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    mem_file = MEMORY_DIR / f'{agent_id}.json'

    tag_list = [t.strip() for t in tags.split(',') if t.strip()] if tags else []
    entry = {
        'id': f'mem_{now_iso().replace(":", "").replace("-", "")[:15]}',
        'type': mem_type if mem_type in ('feedback', 'experience', 'preference') else 'experience',
        'content': content,
        'source_task': source_task,
        'created_at': now_iso(),
        'relevance_tags': tag_list,
        'pinned': False,
    }

    def modifier(data):
        if not data:
            data = {'agent_id': agent_id, 'memories': [], 'stats': {'tasks_handled': 0}}
        memories = data.get('memories', [])
        memories.append(entry)
        # FIFO 淘汰（pinned 除外）
        if len(memories) > MAX_AGENT_MEMORIES:
            unpinned = [m for m in memories if not m.get('pinned')]
            pinned = [m for m in memories if m.get('pinned')]
            # 淘汰最舊的 unpinned experience 類記憶
            unpinned.sort(key=lambda m: (m.get('type') == 'feedback', m.get('created_at', '')))
            memories = pinned + unpinned[-(MAX_AGENT_MEMORIES - len(pinned)):]
        data['memories'] = memories
        return data

    atomic_json_update(mem_file, modifier, {})
    log.info(f'🧠 {agent_id} 記憶寫入: [{mem_type}] {content[:40]}...')
    _append_audit(source_task or 'system', agent_id, 'memory', None, mem_type, content)


def cmd_task_memo(task_id, agent_id, decisions, warnings=''):
    """寫入任務上下文記憶（跨 Agent 傳遞決策鏈）。

    decisions: 逗號分隔的關鍵決策
    warnings: 逗號分隔的風險提示
    """
    TASK_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    memo_file = TASK_MEMORY_DIR / f'{task_id}.json'

    decision_list = [d.strip() for d in decisions.split(',') if d.strip()]
    warning_list = [w.strip() for w in warnings.split(',') if w.strip()] if warnings else []

    # 從 tasks_source.json 獲取當前狀態
    tasks = atomic_json_read(TASKS_FILE, [])
    task = next((t for t in tasks if t.get('id') == task_id), None)
    phase = task.get('state', '') if task else ''

    chain_entry = {
        'agent': agent_id,
        'phase': phase,
        'key_decisions': decision_list,
        'warnings': warning_list,
        'at': now_iso(),
    }

    def modifier(data):
        if not data:
            data = {'task_id': task_id, 'context_chain': []}
        data.setdefault('context_chain', []).append(chain_entry)
        return data

    atomic_json_update(memo_file, modifier, {})
    log.info(f'📝 {task_id} 任務記憶: {agent_id} → {len(decision_list)} 決策')
    _append_audit(task_id, agent_id, 'task_memo', None, None, f'{len(decision_list)} decisions')


def cmd_shared_memo(content, added_by):
    """寫入全局共享記憶（所有 Agent 可讀的規則）。"""
    entry = {
        'content': content,
        'added_by': added_by,
        'at': now_iso(),
    }

    def modifier(data):
        if not data:
            data = {'rules': []}
        data.setdefault('rules', []).append(entry)
        return data

    atomic_json_update(SHARED_MEMORY_FILE, modifier, {})
    log.info(f'🌐 全局記憶寫入: {content[:40]}... (by {added_by})')
    _append_audit('system', added_by, 'shared_memo', None, None, content)


# ── 子 Agent 無狀態委派 ──

MAX_DELEGATION_DEPTH = 3


def _short_uuid():
    """生成短 UUID 後綴。"""
    import uuid as _uuid
    return _uuid.uuid4().hex[:8]


def cmd_delegate(task_id, from_agent, to_agent, instruction, return_spec=''):
    """創建委派子任務，由目標 Agent 獨立執行。

    防死鎖：記錄 delegation_depth 和 delegation_path，超過 3 層或循環委派時拒絕。
    """
    # 檢查父任務，獲取委派鏈信息
    tasks = atomic_json_read(TASKS_FILE, [])
    parent = next((t for t in tasks if t.get('id') == task_id), None)
    if not parent:
        log.error(f'父任務 {task_id} 不存在')
        return

    # 計算委派深度和路徑
    parent_delegation = parent.get('delegation', {})
    depth = parent_delegation.get('delegation_depth', 0) + 1 if parent_delegation else 1
    path = parent_delegation.get('delegation_path', [from_agent]) if parent_delegation else [from_agent]
    path = list(path) + [to_agent]

    # 防死鎖檢查
    if depth > MAX_DELEGATION_DEPTH:
        log.error(f'❌ 委派深度超限 ({depth} > {MAX_DELEGATION_DEPTH})，拒絕委派')
        _append_audit(task_id, from_agent, 'delegate_rejected', None, None, f'depth={depth} exceeds limit')
        return
    if to_agent in path[:-1]:
        log.error(f'❌ 檢測到循環委派 ({" → ".join(path)})，拒絕')
        _append_audit(task_id, from_agent, 'delegate_rejected', None, None, f'circular: {" → ".join(path)}')
        return

    sub_task_id = f'{task_id}-sub-{_short_uuid()}'
    org = STATE_ORG_MAP.get('Doing', to_agent)

    def modifier(tasks):
        sub_task = {
            'id': sub_task_id,
            'parent_task': task_id,
            'type': 'delegation',
            'title': f'[委派] {instruction[:40]}',
            'state': 'Doing',
            'org': org,
            'official': from_agent,
            'now': instruction[:60],
            'delegation': {
                'from': from_agent,
                'to': to_agent,
                'instruction': instruction,
                'return_spec': return_spec,
                'created_at': now_iso(),
                'timeout_minutes': 30,
                'delegation_bypass': True,
                'review_required': True,
                'delegation_depth': depth,
                'delegation_path': path,
            },
            'flow_log': [{'at': now_iso(), 'from': from_agent, 'to': to_agent, 'remark': f'委派: {instruction[:40]}'}],
            'todos': [],
            'updatedAt': now_iso(),
        }
        tasks.insert(0, sub_task)
        return tasks

    atomic_json_update(TASKS_FILE, modifier, [])
    _trigger_refresh()
    log.info(f'📋 委派 {sub_task_id}: {from_agent} → {to_agent} (depth={depth})')
    _append_audit(task_id, from_agent, 'delegate', to_agent, sub_task_id, instruction)


def cmd_delegate_result(sub_task_id, result_json):
    """提交委派子任務結果，回寫到父任務的 task_memory。"""
    tasks = atomic_json_read(TASKS_FILE, [])
    sub = next((t for t in tasks if t.get('id') == sub_task_id), None)
    if not sub:
        log.error(f'子任務 {sub_task_id} 不存在')
        return
    parent_id = sub.get('parent_task', '')
    delegation = sub.get('delegation', {})
    from_agent = delegation.get('from', '')
    to_agent = delegation.get('to', '')

    # 標記子任務完成
    def modifier(tasks):
        t = find_task(tasks, sub_task_id)
        if t:
            t['state'] = 'Done'
            t['now'] = f'委派結果已提交'
            t['updatedAt'] = now_iso()
            t['delegation_result'] = result_json
        return tasks
    atomic_json_update(TASKS_FILE, modifier, [])

    # 寫入父任務的 task_memory
    if parent_id:
        TASK_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        memo_file = TASK_MEMORY_DIR / f'{parent_id}.json'
        chain_entry = {
            'agent': to_agent,
            'phase': 'delegation_result',
            'key_decisions': [f'委派結果: {result_json[:200]}'],
            'warnings': [],
            'at': now_iso(),
            'delegation_from': sub_task_id,
        }
        def memo_modifier(data):
            if not data:
                data = {'task_id': parent_id, 'context_chain': []}
            data.setdefault('context_chain', []).append(chain_entry)
            return data
        atomic_json_update(memo_file, memo_modifier, {})

    _trigger_refresh()
    log.info(f'✅ 委派結果 {sub_task_id} → 父任務 {parent_id}')
    _append_audit(parent_id, to_agent, 'delegate_result', sub_task_id, None, result_json[:100])

_CMD_MIN_ARGS = {
    'create': 6, 'state': 3, 'flow': 5, 'done': 2, 'block': 3, 'confirm': 3,
    'todo': 4, 'progress': 3,
    'memory': 4, 'task-memo': 4, 'shared-memo': 3,
    'delegate': 5, 'delegate-result': 3,
}

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    cmd = args[0]
    if cmd in _CMD_MIN_ARGS and len(args) < _CMD_MIN_ARGS[cmd]:
        print(f'錯誤："{cmd}" 命令至少需要 {_CMD_MIN_ARGS[cmd]} 個參數，實際 {len(args)} 個')
        print(__doc__)
        sys.exit(1)
    # 越權檢測：推斷當前 Agent 身份，校驗是否有權執行該命令
    _check_permission(_infer_agent_id_from_runtime(), cmd)
    if cmd == 'create':
        # 解析可選 --source 參數（格式：telegram:493683906 或 feishu:xxx）
        create_source = None
        create_pos = [args[1], args[2], args[3], args[4], args[5]]
        for i in range(6, len(args)):
            if args[i].startswith('--source=') and i + 1 <= len(args):
                create_source = args[i].split('=', 1)[1]
            elif args[i] == '--source' and i + 1 < len(args):
                create_source = args[i + 1]
                i += 1
        cmd_create(*create_pos, remark=args[6] if len(args)>6 else None, source=create_source)
    elif cmd == 'state':
        cmd_state(args[1], args[2], args[3] if len(args)>3 else None)
    elif cmd == 'flow':
        cmd_flow(args[1], args[2], args[3], args[4])
    elif cmd == 'done':
        cmd_done(args[1], args[2] if len(args)>2 else '', args[3] if len(args)>3 else '')
    elif cmd == 'block':
        cmd_block(args[1], args[2])
    elif cmd == 'todo':
        # 解析可選 --detail 參數
        todo_pos = []
        todo_detail = ''
        ti = 1
        while ti < len(args):
            if args[ti] == '--detail' and ti + 1 < len(args):
                todo_detail = args[ti + 1]; ti += 2
            else:
                todo_pos.append(args[ti]); ti += 1
        cmd_todo(
            todo_pos[0] if len(todo_pos) > 0 else '',
            todo_pos[1] if len(todo_pos) > 1 else '',
            todo_pos[2] if len(todo_pos) > 2 else '',
            todo_pos[3] if len(todo_pos) > 3 else 'not-started',
            detail=todo_detail,
        )
    elif cmd == 'progress':
        # 解析可選 --tokens/--cost/--elapsed 參數
        pos_args = []
        kw = {}
        i = 1
        while i < len(args):
            if args[i] == '--tokens' and i + 1 < len(args):
                kw['tokens'] = args[i + 1]; i += 2
            elif args[i] == '--cost' and i + 1 < len(args):
                kw['cost'] = args[i + 1]; i += 2
            elif args[i] == '--elapsed' and i + 1 < len(args):
                kw['elapsed'] = args[i + 1]; i += 2
            else:
                pos_args.append(args[i]); i += 1
        cmd_progress(
            pos_args[0] if len(pos_args) > 0 else '',
            pos_args[1] if len(pos_args) > 1 else '',
            pos_args[2] if len(pos_args) > 2 else '',
            tokens=kw.get('tokens', 0),
            cost=kw.get('cost', 0.0),
            elapsed=kw.get('elapsed', 0),
        )
    elif cmd == 'memory':
        cmd_memory(args[1], args[2], args[3],
                   args[4] if len(args) > 4 else '',
                   args[5] if len(args) > 5 else '')
    elif cmd == 'task-memo':
        cmd_task_memo(args[1], args[2], args[3],
                      args[4] if len(args) > 4 else '')
    elif cmd == 'shared-memo':
        cmd_shared_memo(args[1], args[2])
    elif cmd == 'confirm':
        cmd_confirm(args[1], args[2], args[3] if len(args) > 3 else '')
    elif cmd == 'delegate':
        cmd_delegate(args[1], args[2], args[3], args[4],
                     args[5] if len(args) > 5 else '')
    elif cmd == 'delegate-result':
        cmd_delegate_result(args[1], args[2])
    else:
        print(__doc__)
        sys.exit(1)
