#!/bin/bash
# 三省六部 · 數據刷新循環
# 用法: ./run_loop.sh [間隔秒數 [巡檢間隔秒數]]
#   間隔秒數：數據刷新頻率，默認 15 秒
#   巡檢間隔秒數：自動重試卡住任務的頻率，默認 120 秒

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export EDICT_HOME="${EDICT_HOME:-$(dirname "$SCRIPT_DIR")}"
INTERVAL="${1:-15}"
LOG="/tmp/sansheng_liubu_refresh.log"
PIDFILE="/tmp/sansheng_liubu_refresh.pid"
MAX_LOG_SIZE=$((10 * 1024 * 1024))  # 10MB

# ── 單實例保護 ──
if [[ -f "$PIDFILE" ]]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "❌ 已有實例運行中 (PID=$OLD_PID)，退出"
    exit 1
  fi
  rm -f "$PIDFILE"
fi
echo $$ > "$PIDFILE"

# ── 優雅退出 ──
cleanup() {
  echo "$(date '+%H:%M:%S') [loop] 收到退出信號，清理中..." >> "$LOG"
  rm -f "$PIDFILE"
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# ── 日誌輪轉 ──
rotate_log() {
  if [[ -f "$LOG" ]] && (( $(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0) > MAX_LOG_SIZE )); then
    mv "$LOG" "${LOG}.1"
    echo "$(date '+%H:%M:%S') [loop] 日誌已輪轉" > "$LOG"
  fi
}

SCAN_INTERVAL="${2:-120}"  # 巡檢間隔(秒), 默認 120
SCAN_COUNTER=0
SCRIPT_TIMEOUT=30  # 單個腳本最大執行時間(秒)
DASHBOARD_PORT="${EDICT_DASHBOARD_PORT:-7891}"  # 看板端口，可通過環境變量覆蓋

echo "🏛️  三省六部數據刷新循環啓動 (PID=$$)"
echo "   腳本目錄: $SCRIPT_DIR"
echo "   間隔: ${INTERVAL}s"
echo "   巡檢間隔: ${SCAN_INTERVAL}s"
echo "   腳本超時: ${SCRIPT_TIMEOUT}s"
echo "   日誌: $LOG"
echo "   PID文件: $PIDFILE"
echo "   按 Ctrl+C 停止"

# ── 安全執行（帶超時保護）──
safe_run() {
  local script="$1"
  if command -v timeout &>/dev/null; then
    timeout "$SCRIPT_TIMEOUT" python3 "$script" >> "$LOG" 2>&1 || {
      local rc=$?
      if [[ $rc -eq 124 ]]; then
        echo "$(date '+%H:%M:%S') [loop] ⚠️ 腳本超時(${SCRIPT_TIMEOUT}s): $script" >> "$LOG"
      fi
    }
  else
    python3 "$script" >> "$LOG" 2>&1 || true
  fi
}

while true; do
  rotate_log
  safe_run "$SCRIPT_DIR/sync_from_openclaw_runtime.py"
  safe_run "$SCRIPT_DIR/sync_agent_config.py"
  safe_run "$SCRIPT_DIR/apply_model_changes.py"
  safe_run "$SCRIPT_DIR/sync_officials_stats.py"
  safe_run "$SCRIPT_DIR/refresh_live_data.py"

  # 定期巡檢：檢測卡住的任務並自動重試
  SCAN_COUNTER=$((SCAN_COUNTER + INTERVAL))
  if (( SCAN_COUNTER >= SCAN_INTERVAL )); then
    SCAN_COUNTER=0
    curl -s -X POST "http://127.0.0.1:${DASHBOARD_PORT}/api/scheduler-scan" \
      -H 'Content-Type: application/json' -d '{"thresholdSec":180}' >> "$LOG" 2>&1 || true
  fi

  sleep "$INTERVAL"
done
