#!/usr/bin/env python3
"""Refresh Watcher — 常駐進程，監控信號文件，debounce 後執行 refresh_live_data.py。

替代 kanban_update.py 中每次操作都 fork 子進程的方式。
多 Agent 並發時，200 次 touch → 合併爲 1 次 refresh。

運行方式:
  python3 scripts/refresh_watcher.py

部署方式:
  - systemd: 參見 edict.service
  - docker-compose: 參見 edict/docker-compose.yml
  - 手動前臺: python3 scripts/refresh_watcher.py
"""
import logging
import os
import pathlib
import signal
import subprocess
import sys
import time

_BASE = pathlib.Path(os.environ.get('EDICT_HOME', '')).resolve() if os.environ.get('EDICT_HOME') else pathlib.Path(__file__).resolve().parent.parent
SIGNAL_FILE = _BASE / 'data' / '.refresh_pending'
PID_FILE = _BASE / 'data' / '.refresh_watcher_pid'
REFRESH_SCRIPT = _BASE / 'scripts' / 'refresh_live_data.py'
DEBOUNCE_SEC = 2       # 信號文件穩定 2 秒後才執行
POLL_INTERVAL = 0.5    # 檢查間隔

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [refresh_watcher] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('refresh_watcher')

_running = True


def _shutdown(signum, frame):
    global _running
    _running = False
    log.info(f'收到信號 {signum}，準備退出')


def main():
    # 寫 PID 文件，讓 kanban_update.py 知道 watcher 在運行
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    log.info(f'Refresh watcher started (pid={os.getpid()}, debounce={DEBOUNCE_SEC}s)')

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    last_seen_mtime = 0.0
    refresh_count = 0

    try:
        while _running:
            try:
                if SIGNAL_FILE.exists():
                    mtime = SIGNAL_FILE.stat().st_mtime
                    now = time.time()
                    # 信號文件存在且已穩定 DEBOUNCE_SEC 秒
                    if mtime > last_seen_mtime and (now - mtime) >= DEBOUNCE_SEC:
                        last_seen_mtime = mtime
                        # 刪除信號文件（在執行前刪，避免執行期間的新 touch 被吞）
                        try:
                            SIGNAL_FILE.unlink()
                        except FileNotFoundError:
                            pass

                        refresh_count += 1
                        log.info(f'🔄 執行 refresh #{refresh_count}')
                        try:
                            subprocess.run(
                                [sys.executable, str(REFRESH_SCRIPT)],
                                capture_output=True,
                                timeout=30,
                            )
                        except subprocess.TimeoutExpired:
                            log.warning('refresh_live_data.py 超時 (30s)')
                        except Exception as e:
                            log.error(f'refresh 執行失敗: {e}')
            except Exception as e:
                log.error(f'Watcher loop error: {e}')

            time.sleep(POLL_INTERVAL)
    finally:
        # 清理 PID 文件
        try:
            PID_FILE.unlink()
        except Exception:
            pass
        log.info(f'Refresh watcher stopped (total refreshes: {refresh_count})')


if __name__ == '__main__':
    main()
