#!/usr/bin/env python3
"""應用 data/pending_thinking_changes.json → openclaw.json，並重啓 Gateway"""
import json
import pathlib
import subprocess
import datetime
import shutil
import logging
import glob

from file_lock import atomic_json_write
from utils import get_openclaw_home

log = logging.getLogger('thinking_change')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

BASE = pathlib.Path(__file__).parent.parent
DATA = BASE / 'data'
OPENCLAW_HOME = get_openclaw_home()
OPENCLAW_CFG = OPENCLAW_HOME / 'openclaw.json'
PENDING = DATA / 'pending_thinking_changes.json'
CHANGE_LOG = DATA / 'thinking_change_log.json'
MAX_BACKUPS = 10
VALID_THINKING = {'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'adaptive', 'max'}


def rj(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def cleanup_backups():
    pattern = str(OPENCLAW_CFG.parent / 'openclaw.json.bak.thinking-*')
    baks = sorted(glob.glob(pattern))
    for old in baks[:-MAX_BACKUPS]:
        try:
            pathlib.Path(old).unlink()
        except OSError:
            pass


def main():
    if not PENDING.exists():
        return
    pending = rj(PENDING, [])
    if not pending:
        return

    cfg = rj(OPENCLAW_CFG, {})
    agents_list = cfg.get('agents', {}).get('list', [])

    applied, errors = [], []
    for change in pending:
        ag_id = str(change.get('agentId', '')).strip()
        thinking = str(change.get('thinking', '')).strip()
        if not ag_id:
            errors.append({'change': change, 'error': 'missing agentId'})
            continue

        clear_default = thinking in ('', '__default__', 'default', 'follow')
        if not clear_default and thinking not in VALID_THINKING:
            errors.append({'change': change, 'error': f'invalid thinking: {thinking}'})
            continue

        found = False
        for ag in agents_list:
            if ag.get('id') != ag_id:
                continue
            old = str(ag.get('thinkingDefault') or '')
            if clear_default:
                ag.pop('thinkingDefault', None)
                new_val = ''
            else:
                ag['thinkingDefault'] = thinking
                new_val = thinking
            applied.append({
                'at': datetime.datetime.now().isoformat(),
                'agentId': ag_id,
                'oldThinking': old,
                'newThinking': new_val,
            })
            found = True
            break

        if not found:
            errors.append({'change': change, 'error': f'agent {ag_id} not found'})

    if applied:
        new_cfg = dict(cfg)
        new_cfg['agents'] = dict(cfg.get('agents', {}))
        new_cfg['agents']['list'] = agents_list

        old_text = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
        new_text = json.dumps(new_cfg, ensure_ascii=False, sort_keys=True)
        bak = None
        if old_text != new_text:
            bak = OPENCLAW_CFG.parent / f'openclaw.json.bak.thinking-{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}'
            shutil.copy2(OPENCLAW_CFG, bak)
            cleanup_backups()
            atomic_json_write(OPENCLAW_CFG, new_cfg)

        log_data = rj(CHANGE_LOG, [])
        if not isinstance(log_data, list):
            log_data = []
        log_data.extend(applied)
        if len(log_data) > 200:
            log_data = log_data[-200:]
        atomic_json_write(CHANGE_LOG, log_data)

        restart_ok = False
        rollback = False
        try:
            r = subprocess.run(['openclaw', 'gateway', 'restart'], capture_output=True, text=True, timeout=30)
            restart_ok = r.returncode == 0
            log.info(f'gateway restart rc={r.returncode}')
        except Exception as e:
            log.error(f'gateway restart failed: {e}')
            if bak and bak.exists():
                shutil.copy2(bak, OPENCLAW_CFG)
                rollback = True
                for a in applied:
                    a['rolledBack'] = True

        atomic_json_write(PENDING, [])
        atomic_json_write(DATA / 'last_thinking_change_result.json', {
            'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'applied': applied,
            'errors': errors,
            'gatewayRestarted': restart_ok,
            'rolledBack': rollback,
        })
    elif errors:
        atomic_json_write(PENDING, [])


if __name__ == '__main__':
    main()
