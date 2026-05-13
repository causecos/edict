#!/usr/bin/env python3
"""task_source_mode.py

看板資料來源模式 CLI（保持操作一致性）

用法：
  python3 scripts/task_source_mode.py status
  python3 scripts/task_source_mode.py set db
  python3 scripts/task_source_mode.py set auto --backend http://127.0.0.1:8000 --timeout 3000
  python3 scripts/task_source_mode.py check
"""
import argparse
import json
import pathlib
import sys
from urllib.request import Request, urlopen

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / 'data'
CFG_FILE = DATA / 'task_source_mode.json'
DEFAULT = {
    'mode': 'db',
    'backendApiBase': 'http://127.0.0.1:8000',
    'timeoutMs': 3000,
}


def normalize(cfg):
    if not isinstance(cfg, dict):
        cfg = {}
    mode = str(cfg.get('mode') or DEFAULT['mode']).lower().strip()
    if mode not in ('auto', 'json', 'db'):
        mode = 'db'
    base = str(cfg.get('backendApiBase') or DEFAULT['backendApiBase']).strip().rstrip('/')
    if not (base.startswith('http://') or base.startswith('https://')):
        base = DEFAULT['backendApiBase']
    try:
        timeout_ms = int(cfg.get('timeoutMs', DEFAULT['timeoutMs']))
    except Exception:
        timeout_ms = DEFAULT['timeoutMs']
    timeout_ms = max(500, min(timeout_ms, 15000))
    return {'mode': mode, 'backendApiBase': base, 'timeoutMs': timeout_ms}


def load_cfg():
    if not CFG_FILE.exists():
        return DEFAULT.copy()
    try:
        return normalize(json.loads(CFG_FILE.read_text(encoding='utf-8')))
    except Exception:
        return DEFAULT.copy()


def save_cfg(cfg):
    CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CFG_FILE.write_text(json.dumps(normalize(cfg), ensure_ascii=False, indent=2), encoding='utf-8')


def check_backend(cfg):
    url = cfg['backendApiBase'] + '/health'
    req = Request(url, headers={'Accept': 'application/json'})
    with urlopen(req, timeout=max(1, cfg['timeoutMs'] / 1000)) as resp:
        raw = resp.read().decode('utf-8', errors='replace')
        payload = json.loads(raw) if raw else {}
        return {'ok': resp.status == 200, 'statusCode': resp.status, 'url': url, 'payload': payload}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('status')
    sub.add_parser('check')

    p_set = sub.add_parser('set')
    p_set.add_argument('mode', choices=['auto', 'json', 'db'])
    p_set.add_argument('--backend', dest='backendApiBase', default=None)
    p_set.add_argument('--timeout', dest='timeoutMs', type=int, default=None)

    args = ap.parse_args()

    if args.cmd == 'status':
        cfg = load_cfg()
        out = {'ok': True, 'config': cfg}
        try:
            out['backend'] = check_backend(cfg)
        except Exception as e:
            out['backend'] = {'ok': False, 'error': str(e), 'url': cfg['backendApiBase'] + '/health'}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if args.cmd == 'check':
        cfg = load_cfg()
        try:
            out = check_backend(cfg)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            sys.exit(0 if out.get('ok') else 2)
        except Exception as e:
            print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False, indent=2))
            sys.exit(2)

    if args.cmd == 'set':
        cfg = load_cfg()
        cfg['mode'] = args.mode
        if args.backendApiBase is not None:
            cfg['backendApiBase'] = args.backendApiBase
        if args.timeoutMs is not None:
            cfg['timeoutMs'] = args.timeoutMs
        cfg = normalize(cfg)
        save_cfg(cfg)
        out = {'ok': True, 'config': cfg}
        # db / auto 模式：立即檢查 backend，提醒故障
        if cfg['mode'] in ('db', 'auto'):
            try:
                out['backend'] = check_backend(cfg)
            except Exception as e:
                out['backend'] = {'ok': False, 'error': str(e), 'url': cfg['backendApiBase'] + '/health'}
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
