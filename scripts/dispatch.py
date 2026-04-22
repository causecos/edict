"""
三省六部 · 任務派發模組
封裝統一的派發邏輯，供給 Dashboard Server 和 kanban_update.py 共用。

使用方式（kanban_update.py）：
    from dispatch import dispatch_for_state

    # 讀取 task 資料
    tasks = atomic_json_read(TASKS_FILE)
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if task:
        dispatch_for_state(task_id, task, new_state, trigger='state')
"""

import json, pathlib, subprocess, logging, shutil, os, sys, time, datetime

# ── 基本路径 ──────────────────────────────────────────────
_BASE = pathlib.Path(os.environ.get('EDICT_HOME', '/home/cosmos/ai-base/core/edict'))
DATA = _BASE / 'data'
SCRIPTS_DIR = _BASE / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))
from file_lock import atomic_json_read, atomic_json_write, atomic_json_update
from utils import now_iso

log = logging.getLogger('dispatch')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

# ── 狀態 → Agent 映射（與 server.py 保持一致）───────────
_STATE_AGENT_MAP = {
    'Taizi':    'taizi',
    'Zhongshu':  'zhongshu',
    'Menxia':    'menxia',
    'Assigned':  'shangshu',
    'Review':   'shangshu',
    'Pending':  'zhongshu',
}
_ORG_AGENT_MAP = {
    '礼部': 'libu', '户部': 'hubu', '兵部': 'bingbu',
    '刑部': 'xingbu', '工部': 'gongbu', '吏部': 'libu_hr',
}
_STATE_LABELS = {
    'Taizi': '太子', 'Zhongshu': '中书省', 'Menxia': '门下省',
    'Assigned': '尚书省', 'Next': '待执行', 'Doing': '执行中',
    'Review': '审查', 'Done': '完成', 'Pending': '待处理',
}
_TERMINAL_STATES = {'Done', 'Cancelled'}

# ── Gateway 檢測 ─────────────────────────────────────────
def _check_gateway_alive():
    """檢測 Gateway 是否在運行。"""
    try:
        import socket
        with socket.create_connection(('127.0.0.1', 18789), timeout=2):
            return True
    except Exception:
        pass
    try:
        result = subprocess.run(['pgrep', '-f', 'openclaw-gateway'],
                                capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False

# ── OpenClaw CLI 路徑解析 ────────────────────────────────
def _resolve_openclaw_bin():
    configured = os.environ.get('OPENCLAW_BIN', '').strip()
    if configured:
        return configured
    # 先檢查常見路徑（避免 PATH 缺失導致找不到）
    for bin_dir in ('/home/cosmos/.npm-global/bin', '/usr/local/bin', '/usr/bin'):
        candidate = pathlib.Path(bin_dir) / 'openclaw'
        if candidate.exists():
            return str(candidate)
    return shutil.which('openclaw')

# ── Scheduler 工具（與 server.py 同步）──────────────────
def _ensure_scheduler(task):
    task.setdefault('_scheduler', {})
    return task['_scheduler']

def _scheduler_add_flow(task, remark, to=''):
    """寫入 flow_log，與 server.py 保持一致。"""
    task.setdefault('flow_log', []).append({
        'at': now_iso(),
        'from': '太子调度',
        'to': to or task.get('org', ''),
        'remark': f'🧭 {remark}'
    })

def _update_task_scheduler(task_id, updater):
    """更新 task 的 scheduler 欄位（寫入 tasks_source.json）。"""
    tasks_path = DATA / 'tasks_source.json'
    tasks = atomic_json_read(tasks_path)
    task = next((t for t in tasks if t.get('id') == task_id), None)
    if not task:
        return False
    sched = _ensure_scheduler(task)
    updater(task, sched)
    task['updatedAt'] = now_iso()
    atomic_json_write(tasks_path, tasks)
    return True

# ── 派發訊息模板 ─────────────────────────────────────────
def _build_dispatch_msg(agent_id, task_id, title, target_dept=''):
    templates = {
        'taizi': (
            f'📜 皇上旨意需要你处理\n'
            f'任务ID: {task_id}\n'
            f'旨意: {title}\n'
            f'⚠️ 看板已有此任务，请勿重复创建。直接用 kanban_update.py 更新状态。\n'
            f'请立即转交中书省起草执行方案。'
        ),
        'zhongshu': (
            f'📜 旨意已到中书省，请起草方案\n'
            f'任务ID: {task_id}\n'
            f'旨意: {title}\n'
            f'⚠️ 看板已有此任务记录，请勿重复创建。直接用 kanban_update.py state 更新状态。\n'
            f'请立即起草执行方案，走完完整三省流程（中书起草→门下审议→尚书派发→六部执行）。'
        ),
        'menxia': (
            f'📋 中书省方案提交审议\n'
            f'任务ID: {task_id}\n'
            f'旨意: {title}\n'
            f'⚠️ 看板已有此任务，请勿重复创建。\n'
            f'请审议中书省方案，给出准奏或封驳意见。'
        ),
        'shangshu': (
            f'📮 门下省已准奏，请派发执行\n'
            f'任务ID: {task_id}\n'
            f'旨意: {title}\n'
            f'{"建议派发部门: " + target_dept if target_dept else ""}\n'
            f'⚠️ 看板已有此任务，请勿重复创建。\n'
            f'请分析方案并派发给六部执行。'
        ),
    }
    return templates.get(agent_id, (
        f'📌 请处理任务\n任务ID: {task_id}\n旨意: {title}\n'
        f'⚠️ 看板已有此任务，请勿重复创建。直接用 kanban_update.py 更新状态。'
    ))

# ── 主派發函式 ───────────────────────────────────────────
def dispatch_for_state(task_id, task, new_state, trigger='state-transition'):
    """
    任務狀態變更後，統一派發對應 Agent。
    
    kanban_update.py 调用方式：
        from dispatch import dispatch_for_state
        tasks = atomic_json_read(TASKS_FILE)
        task = next((t for t in tasks if t.get('id') == task_id), None)
        if task:
            dispatch_for_state(task_id, task, new_state, 'state')
    """
    # 查表找 agent_id
    agent_id = _STATE_AGENT_MAP.get(new_state)
    if agent_id is None and new_state in ('Doing', 'Next'):
        org = task.get('org', '')
        agent_id = _ORG_AGENT_MAP.get(org)
    if not agent_id:
        log.info(f'ℹ️ {task_id} 新状态 {new_state} 无对应 Agent，跳过派发')
        return

    title = task.get('title', '(无标题)')
    target_dept = task.get('targetDept', '')
    msg = _build_dispatch_msg(agent_id, task_id, title, target_dept)

    # 更新 scheduler 狀態
    _update_task_scheduler(task_id, lambda t, s: (
        s.update({
            'lastDispatchAt': now_iso(),
            'lastDispatchStatus': 'queued',
            'lastDispatchAgent': agent_id,
            'lastDispatchTrigger': trigger,
        }),
        s.setdefault('flow_log', []).append({
            'at': now_iso(),
            'remark': f'已入队派发：{new_state} → {agent_id}（{trigger}）',
            'to': _STATE_LABELS.get(new_state, new_state)
        })
    ))

    # 異步執行派發（後台執行，不阻塞）
    def _do_dispatch():
        try:
            # Gateway 就緒檢測（最多等 15 秒）
            gw_ok = False
            for _attempt in range(3):
                if _check_gateway_alive():
                    gw_ok = True
                    break
                time.sleep(5)
            if not gw_ok:
                log.warning(f'⚠️ {task_id} 派发跳过：Gateway 未启动')
                _update_task_scheduler(task_id, lambda t, s: s.update({
                    'lastDispatchStatus': 'gateway-offline',
                    'lastDispatchError': 'Gateway not reachable',
                }))
                return

            # 讀取 dispatch channel 配置（優先使用任務來源的 channel）
            agent_cfg = {}
            cfg_path = DATA / 'agent_config.json'
            if cfg_path.exists():
                agent_cfg = json.loads(cfg_path.read_text())
            # 任務有 source channel → 優先用它；否則用全域設定
            channel = ''
            if task_source := task.get('source'):
                channel = task_source.get('channel', '').strip()
            if not channel:
                channel = (agent_cfg.get('dispatchChannel') or '').strip()

            # 解析 openclaw CLI 路径
            openclaw_bin = _resolve_openclaw_bin()
            if not openclaw_bin:
                log.warning(f'⚠️ {task_id} 派发异常：OpenClaw CLI 未找到')
                _update_task_scheduler(task_id, lambda t, s: s.update({
                    'lastDispatchStatus': 'openclaw-missing',
                    'lastDispatchError': 'openclaw CLI not found',
                }))
                return

            # 構造命令
            cmd = [openclaw_bin, 'agent', '--agent', agent_id, '-m', msg, '--timeout', '300']
            if channel:
                cmd.extend(['--deliver', '--channel', channel])

            # 執行（最多重試 2 次）
            for attempt in range(1, 3):
                log.info(f'🔄 派发 {task_id} → {agent_id} (第{attempt}次)...')
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=310)
                if result.returncode == 0:
                    log.info(f'✅ {task_id} 派发成功 → {agent_id}')
                    _update_task_scheduler(task_id, lambda t, s: s.update({
                        'lastDispatchStatus': 'success',
                        'lastDispatchError': '',
                    }))
                    return
                err = result.stderr[:200] if result.stderr else result.stdout[:200]
                log.warning(f'⚠️ {task_id} 派发失败（第{attempt}次）: {err}')
                if attempt < 2:
                    time.sleep(5)

            log.error(f'❌ {task_id} 派发最终失败 → {agent_id}')
            _update_task_scheduler(task_id, lambda t, s: s.update({
                'lastDispatchStatus': 'failed',
                'lastDispatchError': err,
            }))

        except subprocess.TimeoutExpired:
            log.error(f'❌ {task_id} 派发超时 → {agent_id}')
            _update_task_scheduler(task_id, lambda t, s: s.update({
                'lastDispatchStatus': 'timeout',
                'lastDispatchError': 'timeout',
            }))
        except FileNotFoundError:
            log.warning(f'⚠️ {task_id} 派发异常：OpenClaw CLI 未找到')
            _update_task_scheduler(task_id, lambda t, s: s.update({
                'lastDispatchStatus': 'openclaw-missing',
                'lastDispatchError': 'openclaw CLI not found',
            }))
        except Exception as e:
            log.warning(f'⚠️ {task_id} 派发异常: {e}')
            _update_task_scheduler(task_id, lambda t, s: s.update({
                'lastDispatchStatus': 'error',
                'lastDispatchError': str(e)[:200],
            }))

    import threading
    threading.Thread(target=_do_dispatch, daemon=True).start()
    log.info(f'🚀 {task_id} 派发 → {agent_id}')