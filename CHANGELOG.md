# CHANGELOG

## v2.0.0（2026-06-05）

### 🏛️ 重大更新：DB-first 架構

- **任務資料源改為 DB-first**：Dashboard `live-status` 支援 `db` / `json` / `auto` 三種資料源模式切換，預設建議使用 `db` 模式，以 PostgreSQL 為單一事實來源。
- **模式切換 CLI**：新增 `scripts/task_source_mode.py`，可查詢與切換資料源模式，同時檢測後端健康狀態。
- **流程一致性強化**：主路徑以 Event Bus（Redis Streams）為準，CLI 僅作故障排查與補救使用。

### 🔐 安全加固

- **API Key 後端鑑權**：所有寫入端點（POST / PUT / DELETE）強制驗證 API Key，支援 `X-API-Key` header 與 `Authorization: Bearer` 兩種傳遞方式。
- **密碼與密鑰集中管理**：所有密碼與密鑰統一從 `.env` 檔案載入，不再硬編碼於程式碼中，預設值改為動態隨機生成（256-bit 安全強度）。
- **審計日誌**：新增 `audit_logs` 獨立表，記錄所有 Agent 與系統對任務的操作，支援跨任務檢索與聚合查詢。

### 📢 通知管道升級

- **Telegram 化**：通知管道從 Feishu 遷移至 Telegram，dispatch 自動追蹤任務來源 channel 並優先回報至對應管道。
- **多管道支援**：保留 discord、slack、wecom、webhook 等管道介面，可透過配置靈活切換。

### 📝 繁體中文本地化

- 新增 `scripts/fanti_convert.py` 繁簡轉換工具。
- Dashboard 全介面支援繁體中文。
- Backend 程式碼註解全面補齊繁體中文說明。

### 🔧 後端重構

- **Dispatch 統一重構**：消除重複派發邏輯，統一 `openclaw` 路徑解析，支援指數退避重試機制。
- **Transactional Outbox 模式**：事件先與業務數據寫入同一事務，再由 `OutboxRelay` worker 異步投遞至 Redis Streams，消滅 DB/Event 雙寫不一致問題。
- **Event Bus 強化**：支援消費者組（Consumer Group）、ACK 確認、XAUTOCLAIM 認領超時事件，確保事件不遺失。
- **WebSocket 即時推送**：取代舊架構的 5 秒 HTTP 輪詢，改為 WebSocket 連接 + Redis Pub/Sub 實時推送。

### 🐛 穩定性修復

- 修復 config.py — `env_file` 相對路徑改為絕對路徑。
- 修復 e2e 狀態機對齊 — 確保 kanban 相容層與 backend 狀態轉換矩陣一致。
- 修復 dispatch_worker 重試邏輯 — 長標題導致 422 錯誤。
- 修復 systemd service 與 `edict.sh` — 支援全服務管理（start-all / stop-all / status）。
- 修復 `docker-compose.yml` — 修正損壞的 REDIS_URL 並新增 worker 服務。
- 修復 `install.sh` — AGENTS.md 與 `pending_model_changes.json` 的冪等性。
- Dashboard 任務分類修正：`isEdict()` 現可正確辨識 UUID 格式任務。
- Dashboard 穩定性強化：修復 `STATE_LABEL` 未定義、`loadAll()` 競爭條件等問題。
- 修復 `flow_log` 重複欄位問題。

### 🧹 死碼清理

- 移除 35 個 `_fanti` 重複檔案。
- 清理 `channels/__init__.py` 殘留程式碼。
- 移除未使用的舊架構程式碼區塊。

### 🚀 部署強化

- 新增 `systemd/` 目錄，包含 5 個 user service 模板：
  - `edict-backend.service`
  - `edict-orchestrator.service`
  - `edict-dispatch-worker.service`
  - `edict-outbox-relay.service`
  - `edict-dashboard.service`
- 新增 `.env.example`，提供完整的環境變數設定參考。
- `install.sh` 支援 `install-services` + `init_env` 子命令。
- Dashboard port 環境變數化：支援 `DASHBOARD_PORT` / `EDICT_DASHBOARD_PORT`。

---

## v1.x（2026-04 ~ 2026-05）

### 功能更新

- 任務建立時記錄 source channel，dispatch 優先使用任務來源 channel。
- Dashboard 監聽所有網卡（0.0.0.0），不再僅限 localhost。
- 修復 dashboard server 與 dispatch 模組的 openclaw 路徑解析。
- 統一派發邏輯，消除重複 dispatch 程式碼。
- 支援 `tg.tasks.*` 命令碼用於任務列表查詢（Telegram CLI）。
- 任務列表輸出支援繁體中文別名（「任務清單 完整」）。
- CLI 任務列表輸出預設隱藏 session-mirror 項目。
- 修復 EventBus：持久化並傳播 report 內容至 DB 任務流程。

### CI 與依賴

- 升級 `docker/login-action` 3→4、`docker/metadata-action` 5→6、`docker/setup-qemu-action` 3→4、`actions/setup-python` 5→6。
- 修復 CI YAML 中 FastAPI 匯入步驟的解析歧義。
- 相容 Windows 系統的 Python 解釋器路徑查找。

### 文件

- 新增專案設計文件、效能基準計劃文件、朝堂議政開發規格。
- 補齊 README — 後端架構、安全、部署、通知管道、本地化。
- 加入 Maintained Fork Notice（fork 目標 / 改動狀態 / upstream PR 方向）。
- 補齊 backend 中文註解（依 RULES.md 規範）。
