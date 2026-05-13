#!/usr/bin/env python3
import json
import pathlib
import time
import datetime
import traceback
import logging
from file_lock import atomic_json_write, atomic_json_read
from utils import get_openclaw_home

log = logging.getLogger('sync_runtime')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / 'data'
DATA.mkdir(exist_ok=True)
SYNC_STATUS = DATA / 'sync_status.json'
SESSIONS_ROOT = get_openclaw_home() / 'agents'


def write_status(**kwargs):
    atomic_json_write(SYNC_STATUS, kwargs)


def ms_to_str(ts_ms):
    if not ts_ms:
        return '-'
    try:
        return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return '-'


def state_from_session(age_ms, aborted):
    if aborted:
        return 'Blocked'
    if age_ms <= 2 * 60 * 1000:
        return 'Doing'
    if age_ms <= 60 * 60 * 1000:
        return 'Review'
    return 'Next'


def detect_official(agent_id):
    mapping = {
        'main':    ('儲君', '太子'),        # legacy id for taizi
        'taizi':   ('儲君', '太子'),
        'zhongshu': ('中書令', '中書省'),
        'menxia':  ('侍中', '門下省'),
        'shangshu': ('尚書令', '尚書省'),
        'hubu':    ('戶部尚書', '戶部'),
        'libu':    ('禮部尚書', '禮部'),
        'bingbu':  ('兵部尚書', '兵部'),
        'xingbu':  ('刑部尚書', '刑部'),
        'gongbu':  ('工部尚書', '工部'),
        'libu_hr': ('吏部尚書', '吏部'),
        'zaochao': ('欽天監', '欽天監'),
    }
    return mapping.get(agent_id, ('尚書令', '尚書省'))


def load_activity(session_file, limit=12):
    p = pathlib.Path(session_file or '')
    if not p.exists():
        return []
    rows = []
    try:
        lines = p.read_text(errors='ignore').splitlines()
    except Exception:
        return []

    # Read all valid JSON lines first
    events = []
    for ln in lines:
        try:
            item = json.loads(ln)
            events.append(item)
        except:
            continue

    # Process events to extract meaningful activity
    # We want to show what the agent is *thinking* or *doing*
    for item in reversed(events):
        msg = item.get('message') or {}
        role = msg.get('role')
        ts = item.get('timestamp') or ''

        if role == 'toolResult':
            tool = msg.get('toolName', '-')
            details = msg.get('details') or {}
            # If tool output is short, show it
            content = msg.get('content', [{'text': ''}])[0].get('text', '')
            if len(content) < 50:
                text = f"Tool '{tool}' returned: {content}"
            else:
                text = f"Tool '{tool}' finished"
            rows.append({'at': ts, 'kind': 'tool', 'text': text})

        elif role == 'assistant':
            text = ''
            for c in msg.get('content', []):
                if c.get('type') == 'text' and c.get('text'):
                    raw_text = c.get('text').strip()
                    # Clean up common prefixes
                    clean_text = raw_text.replace('[[reply_to_current]]', '').strip()
                    if clean_text:
                        text = clean_text
                    break
            if text:
                # Prioritize showing the "thought" - usually the first few sentences
                summary = text.split('\n')[0]
                if len(summary) > 200:
                    summary = summary[:200] + '...'
                rows.append({'at': ts, 'kind': 'assistant', 'text': summary})
                
        elif role == 'user':
             # Also show what user asked, can be context relevant
             text = ''
             for c in msg.get('content', []):
                if c.get('type') == 'text':
                     text = c.get('text', '')[:100]
             if text:
                 rows.append({'at': ts, 'kind': 'user', 'text': f"User: {text}..."})

        if len(rows) >= limit:
            break

    # Re-order to chronological for display if needed, but the caller usually takes the first (latest)
    return rows


def build_task(agent_id, session_key, row, now_ms):
    session_id = row.get('sessionId') or session_key
    updated_at = row.get('updatedAt') or 0
    age_ms = max(0, now_ms - updated_at) if updated_at else 99 * 24 * 3600 * 1000
    aborted = bool(row.get('abortedLastRun'))
    state = state_from_session(age_ms, aborted)

    official, org = detect_official(agent_id)
    channel = row.get('lastChannel') or (row.get('origin') or {}).get('channel') or '-'
    session_file = row.get('sessionFile', '')
    
    # 嘗試從 activity 獲取更有意義的當前狀態描述
    latest_act = '等待指令'
    acts = load_activity(session_file, limit=5)
    
    # If the absolute latest is a tool result, look for the preceding assistant thought
    # because that explains *why* the tool was called.
    if acts:
        first_act = acts[0]
        if first_act['kind'] == 'tool' and len(acts) > 1:
            # Look for next assistant message (which is actually previous in time)
            for next_act in acts[1:]:
                if next_act['kind'] == 'assistant':
                    latest_act = f"正在執行: {next_act['text'][:80]}"
                    break
            else:
                latest_act = first_act['text'][:60]
        elif first_act['kind'] == 'assistant':
             latest_act = f"思考中: {first_act['text'][:80]}"
        else:
             latest_act = acts[0]['text'][:60]
    
    title_label = (row.get('origin') or {}).get('label') or session_key
    # 清洗會話標題：agent:xxx:cron:uuid → 定時任務, agent:xxx:subagent:uuid → 子任務
    import re
    if re.match(r'agent:\w+:cron:', title_label):
        title = f"{org}定時任務"
    elif re.match(r'agent:\w+:subagent:', title_label):
        title = f"{org}子任務"
    elif title_label == session_key or len(title_label) > 40:
        title = f"{org}會話"
    else:
        title = f"{title_label}"
    
    return {
        'id': f"OC-{agent_id}-{str(session_id)[:8]}",
        'title': title,
        'official': official,
        'org': org,
        'state': state,
        'now': latest_act,
        'eta': ms_to_str(updated_at),
        'block': '上次運行中斷' if aborted else '無',
        'output': session_file,
        'flow': {
            'draft': f"agent={agent_id}",
            'review': f"updatedAt={ms_to_str(updated_at)}",
            'dispatch': f"sessionKey={session_key}",
        },
        'ac': '來自 OpenClaw runtime sessions 的實時映射',
        'activity': load_activity(session_file, limit=10),
        'sourceMeta': {
            'agentId': agent_id,
            'sessionKey': session_key,
            'sessionId': session_id,
            'updatedAt': updated_at,
            'ageMs': age_ms,
            'systemSent': bool(row.get('systemSent')),
            'abortedLastRun': aborted,
            'inputTokens': row.get('inputTokens'),
            'outputTokens': row.get('outputTokens'),
            'totalTokens': row.get('totalTokens'),
        }
    }


def main():
    start = time.time()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    now_ms = int(time.time() * 1000)

    try:
        tasks = []
        scan_files = 0

        if SESSIONS_ROOT.exists():
            for agent_dir in sorted(SESSIONS_ROOT.iterdir()):
                if not agent_dir.is_dir():
                    continue
                agent_id = agent_dir.name
                sessions_file = agent_dir / 'sessions' / 'sessions.json'
                if not sessions_file.exists():
                    continue
                scan_files += 1

                try:
                    raw = json.loads(sessions_file.read_text())
                except Exception:
                    continue

                if not isinstance(raw, dict):
                    continue

                for session_key, row in raw.items():
                    if not isinstance(row, dict):
                        continue
                    tasks.append(build_task(agent_id, session_key, row, now_ms))

        # merge mission control tasks (最小接入)
        mc_tasks_file = DATA / 'mission_control_tasks.json'
        if mc_tasks_file.exists():
            try:
                mc_tasks = json.loads(mc_tasks_file.read_text())
                if isinstance(mc_tasks, list):
                    tasks.extend(mc_tasks)
            except Exception:
                pass

        # merge manual parallel tasks (用於軍機處並行看板展示)
        manual_tasks_file = DATA / 'manual_parallel_tasks.json'
        if manual_tasks_file.exists():
            try:
                manual_tasks = json.loads(manual_tasks_file.read_text())
                if isinstance(manual_tasks, list):
                    tasks.extend(manual_tasks)
            except Exception:
                pass

        tasks.sort(key=lambda x: x.get('sourceMeta', {}).get('updatedAt', 0), reverse=True)

        # 去重（同一 id 只保留第一個=最新的）
        seen_ids = set()
        deduped = []
        for t in tasks:
            if t['id'] not in seen_ids:
                seen_ids.add(t['id'])
                deduped.append(t)
        tasks = deduped

        # ── 過濾掉非 JJC 且非活躍的系統會話，防止看板噪音 ──
        # 規則: 僅保留 24小時內更新的活躍會話，且排除 cron/subagent 等純後臺任務
        filtered_tasks = []
        one_day_ago = now_ms - 24 * 3600 * 1000
        for t in tasks:
            # 始終保留 JJC 任務（如果有的話，雖然這裡主要是 OC 任務，但以防萬一）
            if str(t['id']).startswith('JJC'):
                filtered_tasks.append(t)
                continue
            
            # OC 任務過濾
            updated = t.get('sourceMeta', {}).get('updatedAt', 0)
            title = t.get('title', '')
            
            # 1. 排除太舊的 (超過24小時)
            if updated < one_day_ago:
                continue
            
            # 2. 排除純後臺 cron / subagent 任務，除非它們正在報錯
            if '定時任務' in title or '子任務' in title:
                # 只有當它 block 或者 error 時才顯示，否則視爲噪音
                if t.get('state') != 'Blocked':
                    continue

            # 3. 排除已冷卻的 OC 會話，避免污染看板
            # 保留 Doing（<2min）、Review（<60min）、Blocked（報錯）
            # 僅過濾掉 Next（>60min 無響應）等已結束/閒置的會話
            state = t.get('state')
            if state not in ('Doing', 'Review', 'Blocked'):
                continue

            filtered_tasks.append(t)
        
        tasks = filtered_tasks
        
        # ── 保留已有的 JJC-* 旨意任務（不覆蓋皇上下旨記錄）──
        # JJC 任務的 now 字段由 Agent 自己通過 kanban_update.py progress 命令主動上報，
        # 不再從會話日誌中被動抓取。這裡只做合併，不做 activity 映射。
        existing_tasks_file = DATA / 'tasks_source.json'
        if existing_tasks_file.exists():
            try:
                existing = json.loads(existing_tasks_file.read_text())
                jjc_existing = [t for t in existing if str(t.get('id', '')).startswith('JJC')]
                
                # 去掉 tasks 裏已有的 JJC（以防重複），再把旨意放到最前面
                tasks = [t for t in tasks if not str(t.get('id', '')).startswith('JJC')]
                tasks = jjc_existing + tasks
            except Exception as e:
                log.error(f'merge existing JJC tasks failed: {e}')
                pass

        atomic_json_write(DATA / 'tasks_source.json', tasks)

        duration_ms = int((time.time() - start) * 1000)
        write_status(
            ok=True,
            lastSyncAt=now,
            durationMs=duration_ms,
            source='openclaw_runtime_sessions',
            recordCount=len(tasks),
            scannedSessionFiles=scan_files,
            missingFields={},
            error=None,
        )
        log.info(f'synced {len(tasks)} tasks from openclaw runtime in {duration_ms}ms')

    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        write_status(
            ok=False,
            lastSyncAt=now,
            durationMs=duration_ms,
            source='openclaw_runtime_sessions',
            recordCount=0,
            missingFields={},
            error=f'{type(e).__name__}: {e}',
            traceback=traceback.format_exc(limit=3),
        )
        raise


if __name__ == '__main__':
    main()
