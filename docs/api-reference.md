# Edict API 參考文件

> **版本**：v2.0.0  
> **後端框架**：FastAPI  
> **基礎 URL**：`http://127.0.0.1:8000`（可透過環境變數 `PORT` 設定）  
> **Dashboard 端口**：`7891`（可透過 `DASHBOARD_PORT` / `EDICT_DASHBOARD_PORT` 設定）

---

## 認證機制

所有寫入端點（POST / PUT / DELETE）需要 API Key 驗證。支援兩種傳遞方式：

- **Header `X-API-Key`**：`X-API-Key: <your-api-key>`
- **Authorization Bearer**：`Authorization: Bearer <your-api-key>`

讀取端點（GET）無需認證。

---

## 一、Backend API（FastAPI，端口 8000）

### 1.1 系統端點

#### `GET /health`

存活檢查端點，供負載均衡 / Docker healthcheck 使用。

**回應範例**：
```json
{
  "status": "ok",
  "version": "2.0.0",
  "engine": "edict"
}
```

#### `GET /api`

API 根路徑，回傳可用端點清單。

**回應範例**：
```json
{
  "name": "Edict 三省六部 API",
  "version": "2.0.0",
  "endpoints": {
    "tasks": "/api/tasks",
    "agents": "/api/agents",
    "events": "/api/events",
    "admin": "/api/admin",
    "websocket": "/ws",
    "health": "/health"
  }
}
```

---

### 1.2 任務 API — `/api/tasks`

#### `GET /api/tasks`

獲取任務列表，支援多重過濾與分頁。

**查詢參數**：

| 參數 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `state` | `string` | 無 | 任務狀態過濾（可選） |
| `assignee_org` | `string` | 無 | 執行部門過濾（可選） |
| `priority` | `string` | 無 | 優先級過濾（可選） |
| `limit` | `int` | `50` | 回傳數量上限（最大 200） |
| `offset` | `int` | `0` | 分頁偏移量 |

**回應範例**：
```json
{
  "tasks": [
    {
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "trace_id": "...",
      "title": "任務標題",
      "description": "...",
      "priority": "中",
      "state": "Doing",
      "assignee_org": "工部",
      "creator": "emperor",
      "tags": [],
      "flow_log": [],
      "progress_log": [],
      "todos": [],
      "scheduler": {},
      "created_at": "2026-06-05T12:00:00+00:00",
      "updated_at": "2026-06-05T12:00:00+00:00"
    }
  ],
  "count": 1
}
```

#### `GET /api/tasks/live-status`

相容舊 `live_status.json` 格式的全局狀態，將 active 與 completed 任務分開回傳。

#### `GET /api/tasks/stats`

任務統計，按狀態彙總數量。

**回應範例**：
```json
{
  "total": 42,
  "by_state": {
    "Taizi": 2,
    "Zhongshu": 5,
    "Menxia": 3,
    "Assigned": 1,
    "Doing": 20,
    "Review": 3,
    "Done": 5,
    "Cancelled": 2,
    "Blocked": 1
  }
}
```

#### `POST /api/tasks` 🔐

創建新任務。

**請求體**：
```json
{
  "title": "任務標題（必填，最長 500 字元）",
  "description": "任務描述（可選，最長 5000 字元）",
  "priority": "中",
  "assignee_org": "工部",
  "creator": "emperor",
  "tags": [],
  "meta": {}
}
```

**回應**（201 Created）：
```json
{
  "task_id": "550e8400-...",
  "trace_id": "...",
  "state": "Taizi"
}
```

#### `GET /api/tasks/{task_id}`

獲取任務詳情。

**路徑參數**：
- `task_id`：UUID 格式的任務 ID

#### `POST /api/tasks/{task_id}/transition` 🔐

執行狀態流轉。

**請求體**：
```json
{
  "new_state": "Zhongshu",
  "agent": "taizi",
  "reason": "太子分揀完成"
}
```

**狀態流轉矩陣**：
| 目前狀態 | 允許流轉至 |
|----------|-----------|
| `Pending` | `Taizi`, `Cancelled` |
| `Taizi` | `Zhongshu`, `Cancelled` |
| `Zhongshu` | `Menxia`, `Cancelled`, `Blocked` |
| `Menxia` | `Assigned`, `Zhongshu`, `Cancelled` |
| `Assigned` | `Doing`, `Next`, `Cancelled`, `Blocked` |
| `Next` | `Doing`, `Cancelled`, `Blocked` |
| `Doing` | `Review`, `Done`, `Blocked`, `Cancelled` |
| `Review` | `Done`, `Menxia`, `Doing`, `Cancelled`, `PendingConfirm` |
| `PendingConfirm` | `Done`, `Review`, `Cancelled` |
| `Blocked` | `Taizi`, `Zhongshu`, `Menxia`, `Assigned`, `Next`, `Doing`, `Review`, `Cancelled` |

#### `POST /api/tasks/{task_id}/dispatch` 🔐

手動派發任務給指定 agent。

**查詢參數**：
| 參數 | 類型 | 說明 |
|------|------|------|
| `agent` | `string` | 目標 agent 名稱（必填） |
| `message` | `string` | 派發消息（可選） |

#### `POST /api/tasks/{task_id}/progress` 🔐

添加進度記錄。

**請求體**：
```json
{
  "agent": "gongbu",
  "content": "已完成基礎架構搭建"
}
```

#### `PUT /api/tasks/{task_id}/todos` 🔐

更新任務 TODO 清單。

**請求體**：
```json
{
  "todos": [
    { "id": "1", "title": "子任務一", "status": "in_progress" }
  ]
}
```

#### `PUT /api/tasks/{task_id}/scheduler` 🔐

更新任務排期信息。

**請求體**：
```json
{
  "scheduler": {
    "deadline": "2026-07-01T00:00:00Z",
    "reminder": true
  }
}
```

---

### 1.3 舊版相容路由 — `/api/tasks/by-legacy/{legacy_id}`

用於透過舊版任務 ID（如 `JJC-20260301-007`）操作任務。系統會透過 tags 或 `meta.legacy_id` 欄位查找對應的 UUID 任務。

#### `GET /api/tasks/by-legacy/{legacy_id}`

透過舊版 ID 獲取任務。

#### `POST /api/tasks/by-legacy/{legacy_id}/transition` 🔐

透過舊版 ID 執行狀態流轉。

#### `POST /api/tasks/by-legacy/{legacy_id}/progress` 🔐

透過舊版 ID 添加進度。

#### `PUT /api/tasks/by-legacy/{legacy_id}/todos` 🔐

透過舊版 ID 更新 TODO。

---

### 1.4 Agent API — `/api/agents`

#### `GET /api/agents`

列出所有可用 Agent（12 個角色）。

**回應範例**：
```json
{
  "agents": [
    { "id": "zaochao", "name": "早朝（朝會主持）", "role": "朝會召集與議程管理", "icon": "🏛️" },
    { "id": "taizi", "name": "太子", "role": "任務分揀與派發", "icon": "👑" },
    { "id": "libu_hr", "name": "吏部（人事）", "role": "人事與組織管理", "icon": "👤" },
    { "id": "shangshu", "name": "尚書令", "role": "總協調與任務監督", "icon": "📜" },
    { "id": "zhongshu", "name": "中書省", "role": "起草詔令與方案規劃", "icon": "✍️" },
    { "id": "menxia", "name": "門下省", "role": "審核與封駁", "icon": "🔍" },
    { "id": "libu", "name": "禮部", "role": "文檔與規範管理", "icon": "📝" },
    { "id": "hubu", "name": "戶部", "role": "財務與資源管理", "icon": "💰" },
    { "id": "gongbu", "name": "工部", "role": "工程與技術實施", "icon": "🔧" },
    { "id": "xingbu", "name": "刑部", "role": "規範與質量審查", "icon": "⚖️" },
    { "id": "bingbu", "name": "兵部", "role": "安全與應急響應", "icon": "🛡️" }
  ]
}
```

#### `GET /api/agents/{agent_id}`

獲取指定 Agent 的詳細資訊，包含 SOUL.md 前 2000 字元預覽。

#### `GET /api/agents/{agent_id}/config`

獲取 Agent 運行時配置（從 `data/agent_config.json` 讀取）。

---

### 1.5 事件 API — `/api/events`

#### `GET /api/events`

查詢持久化事件（從 PostgreSQL `events` 表）。

**查詢參數**：

| 參數 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `trace_id` | `string` | 無 | 依追蹤鏈路 ID 過濾 |
| `topic` | `string` | 無 | 依事件主題過濾 |
| `producer` | `string` | 無 | 依事件生產者過濾 |
| `limit` | `int` | `50` | 回傳數量上限（最大 500） |

#### `GET /api/events/stream-info`

查詢 Redis Stream 實時信息。

**查詢參數**：
- `topic`（必填）：Stream topic 名稱

#### `GET /api/events/topics`

列出所有可用事件 topic。

**可用 topic 清單**：

| Topic | 說明 |
|-------|------|
| `task.created` | 任務創建 |
| `task.status` | 狀態變更 |
| `task.dispatch` | Agent 派發 |
| `task.dispatch.started` | 派發開始 |
| `task.dispatch.failed` | 派發失敗 |
| `task.dispatch.alert` | 派發安全告警 |
| `task.completed` | 任務完成 |
| `task.stalled` | 任務停滯（巡檢） |
| `task.audit` | 任務審計快照 |
| `agent.thoughts` | Agent 思考流 |
| `agent.heartbeat` | Worker 心跳 |

---

### 1.6 管理 API — `/api/admin`

#### `GET /api/admin/health/deep`

深度健康檢查，同時檢測 PostgreSQL 與 Redis 連通性。

#### `GET /api/admin/config`

獲取當前運行配置（資料庫與 Redis 位址已脫敏）。

#### `GET /api/admin/pending-events`

查看未 ACK 的 pending 事件（診斷工具）。

**查詢參數**：
| 參數 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `topic` | `string` | `task.dispatch` | Stream topic |
| `group` | `string` | `dispatcher` | 消費者組名稱 |
| `count` | `int` | `20` | 回傳數量 |

#### `POST /api/admin/migrate/check` 🔐

檢查舊數據檔案（`tasks_source.json`、`live_status.json`、`agent_config.json`、`officials_stats.json`）是否存在。

#### `GET /api/admin/source-mode`

獲取當前任務資料來源模式配置。

#### `POST /api/admin/source-mode` 🔐

設定任務資料來源模式。

**請求體**：
```json
{
  "mode": "db",
  "backendApiBase": "http://127.0.0.1:8000",
  "timeoutMs": 3000
}
```

---

### 1.7 WebSocket — `/ws`

#### `WS /ws`

主 WebSocket 端點，訂閱 Redis Pub/Sub 頻道 `edict:pubsub:*`，實時推送所有事件。

**推送格式**：
```json
{
  "type": "event",
  "topic": "task.status",
  "data": { ... }
}
```

**客戶端可發送的消息**：
- `{ "type": "ping" }` — 心跳，服務端回傳 `{ "type": "pong" }`
- `{ "type": "subscribe", "topics": [...] }` — 訂閱特定 topic（未來擴展）

#### `WS /ws/task/{task_id}`

單任務 WebSocket，僅推送與指定任務相關的事件。

---

## 二、Dashboard API（Python HTTP Server，端口 7891）

### 2.1 系統與資料源

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `GET` | `/healthz` | Dashboard 健康檢查 | 無 |
| `GET` | `/api/source-mode` | 獲取資料來源模式與後端健康狀態 | 無 |
| `POST` | `/api/source-mode` | 設定資料來源模式 | 有 |

### 2.2 任務資料

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `GET` | `/api/live-status` | 獲取即時任務狀態（依資料源模式路由至 DB 或 JSON） | 無 |
| `GET` | `/api/task-activity/{task_id}` | 獲取任務活動記錄 | 無 |
| `GET` | `/api/task-output/{task_id}` | 獲取任務輸出內容（最多 50000 字元） | 無 |
| `GET` | `/api/scheduler-state/{task_id}` | 獲取任務調度器狀態 | 無 |
| `POST` | `/api/task-action` | 任務操作（stop / cancel / resume） | 有 |
| `POST` | `/api/archive-task` | 歸檔 / 取消歸檔任務 | 有 |
| `POST` | `/api/task-todos` | 更新任務 TODO 清單 | 有 |
| `POST` | `/api/create-task` | 建立新任務 | 有 |
| `POST` | `/api/review-action` | 審核操作（approve / reject） | 有 |
| `POST` | `/api/advance-state` | 推進任務狀態 | 有 |

### 2.3 Agent 與技能管理

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `GET` | `/api/agent-config` | 獲取 Agent 配置 | 無 |
| `GET` | `/api/agents-status` | 獲取所有 Agent 狀態 | 無 |
| `GET` | `/api/agent-activity/{agent_id}` | 獲取指定 Agent 活動記錄 | 無 |
| `POST` | `/api/agent-wake` | 喚醒 Agent | 有 |
| `POST` | `/api/set-model` | 設定 Agent 模型 | 有 |
| `POST` | `/api/set-thinking` | 設定 Agent 思考模式 | 有 |
| `POST` | `/api/set-dispatch-channel` | 設定派發管道 | 有 |
| `GET` | `/api/remote-skills-list` | 列出遠端技能 | 無 |
| `GET` | `/api/skill-content/{agent_id}/{skill_name}` | 獲取技能內容 | 無 |
| `POST` | `/api/add-skill` | 新增 Agent 技能 | 有 |
| `POST` | `/api/add-remote-skill` | 新增遠端技能 | 有 |
| `POST` | `/api/update-remote-skill` | 更新遠端技能 | 有 |
| `POST` | `/api/remove-remote-skill` | 移除遠端技能 | 有 |

### 2.4 調度器與巡檢

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `POST` | `/api/scheduler-scan` | 手動觸發調度器巡檢 | 有 |
| `POST` | `/api/scheduler-retry` | 重試停滯任務 | 有 |
| `POST` | `/api/scheduler-escalate` | 升級任務處理層級 | 有 |
| `POST` | `/api/scheduler-rollback` | 回滾任務狀態 | 有 |
| `POST` | `/api/repair-flow-order` | 修復 flow_log 順序 | 有 |

### 2.5 早朝（新聞）

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `GET` | `/api/morning-brief` | 獲取最新早朝簡報 | 無 |
| `GET` | `/api/morning-brief/{date}` | 獲取指定日期早朝簡報（YYYYMMDD） | 無 |
| `GET` | `/api/morning-config` | 獲取早朝配置 | 無 |
| `POST` | `/api/morning-config` | 更新早朝配置 | 有 |
| `POST` | `/api/morning-brief/refresh` | 手動觸發新聞採集 | 有 |

### 2.6 朝堂議政

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `GET` | `/api/court-discuss/list` | 列出所有議政 session | 無 |
| `GET` | `/api/court-discuss/officials` | 列出可參與議政的官員 | 無 |
| `GET` | `/api/court-discuss/session/{sid}` | 獲取指定 session 詳情 | 無 |
| `GET` | `/api/court-discuss/fate` | 獲取天命事件 | 無 |
| `POST` | `/api/court-discuss/start` | 啟動新議政 session | 有 |
| `POST` | `/api/court-discuss/advance` | 推進議政討論 | 有 |
| `POST` | `/api/court-discuss/conclude` | 結束議政 session | 有 |
| `POST` | `/api/court-discuss/destroy` | 銷毀議政 session | 有 |

### 2.7 其他

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `GET` | `/api/i18n` | 獲取多語言資料 | 無 |
| `GET` | `/api/officials-stats` | 獲取官員統計 | 無 |
| `GET` | `/api/model-change-log` | 獲取模型變更記錄 | 無 |
| `GET` | `/api/last-result` | 獲取最後一次模型變更結果 | 無 |
| `GET` | `/api/notification-channels` | 列出可用通知管道 | 無 |

### 2.8 認證

| 方法 | 路徑 | 說明 | 認證 |
|------|------|------|------|
| `GET` | `/api/auth/status` | 獲取認證狀態 | 無 |
| `POST` | `/api/auth/setup` | 設定初始密碼 | 無 |
| `POST` | `/api/auth/login` | 登入獲取 JWT Token | 無 |

#### 認證說明

Dashboard 使用 JWT 認證保護寫入端點。初次使用時需：

1. `POST /api/auth/setup` 設定密碼
2. `POST /api/auth/login` 獲取 JWT Token
3. 後續請求攜帶 Token（Cookie `edict_token` 或 Authorization header）

---

## 三、事件模型（Event Topics）

所有事件透過兩層路徑傳遞：

1. **Redis Streams**（持久化，可靠消費）：`edict:stream:{topic}`
2. **Redis Pub/Sub**（即時推送）：`edict:pubsub:{topic}`

事件結構遵循統一 schema：

```json
{
  "event_id": "uuid",
  "trace_id": "uuid",
  "timestamp": "ISO 8601",
  "topic": "task.status",
  "event_type": "state.changed",
  "producer": "task_service:v2",
  "payload": { ... },
  "meta": { "priority": "high", "model": "deepseek-v4" }
}
```
