# Edict 資料庫結構文件

> **資料庫**：PostgreSQL（透過 SQLAlchemy async ORM + asyncpg 驅動）  
> **版本**：v2.0.0  
> **遷移工具**：Alembic（生產環境）/ `Base.metadata.create_all`（開發環境）

---

## 概覽

Edict 使用 6 張 PostgreSQL 表來支撐任務管理、事件溯源、審計追蹤與可靠投遞：

| 表名 | 說明 | 核心用途 |
|------|------|----------|
| `tasks` | 三省六部任務核心表 | 任務 CRUD、狀態流轉、Dashboard 呈現 |
| `events` | 事件持久化表 | 事件溯源、回放、跨任務查詢 |
| `outbox_events` | 交易發件箱表 | Transactional Outbox Pattern — 確保事件可靠性 |
| `audit_logs` | 審計日誌表 | 所有操作的獨立審計追蹤 |
| `thoughts` | Agent 思考流表 | 思考過程持久化、效能分析 |
| `todos` | 結構化子任務表 | 子任務拆分、追蹤與 checkpoint 管理 |

---

## 一、`tasks` — 任務核心表

三省六部任務的主要存儲表，記錄從創建到完成的完整生命週期。

### 欄位定義

#### 核心識別

| 欄位 | 類型 | 約束 | 說明 |
|------|------|------|------|
| `task_id` | `UUID` | **PK**，預設 `uuid4()` | 任務主鍵 |
| `trace_id` | `VARCHAR(64)` | NOT NULL，INDEX | 追蹤鏈路 ID |
| `title` | `VARCHAR(200)` | NOT NULL | 任務標題 |
| `description` | `TEXT` | 預設 `''` | 任務描述 |
| `priority` | `VARCHAR(10)` | 預設 `'中'` | 優先級（高 / 中 / 低） |

#### 狀態與派發

| 欄位 | 類型 | 約束 | 說明 |
|------|------|------|------|
| `state` | `VARCHAR`（枚舉） | NOT NULL，預設 `'Taizi'` | 任務狀態 |
| `assignee_org` | `VARCHAR(50)` | NULLABLE | 目標執行部門 |
| `creator` | `VARCHAR(50)` | 預設 `'emperor'` | 創建者 |
| `tags` | `JSONB` | 預設 `[]` | 標籤陣列 |
| `meta` | `JSONB` | 預設 `{}` | 擴展元數據 |

#### 舊看板相容欄位

> 以下欄位與新欄位同步寫入，供舊版 Dashboard 直接讀取。

| 欄位 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `org` | `VARCHAR(32)` | `'太子'` | 當前執行部門（舊顯示格式） |
| `official` | `VARCHAR(32)` | `''` | 責任官員 |
| `now` | `TEXT` | `''` | 當前進展描述 |
| `eta` | `VARCHAR(64)` | `'-'` | 預計完成時間 |
| `block` | `TEXT` | `'無'` | 阻塞原因 |
| `output` | `TEXT` | `''` | 最終產出 |
| `archived` | `BOOLEAN` | `false` | 是否歸檔 |

#### 日誌與附件

| 欄位 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `flow_log` | `JSONB` | `[]` | 流轉日誌：`[{from, to, agent, reason, ts, at}]` |
| `progress_log` | `JSONB` | `[]` | 進展日誌：`[{at, agent, text, todos}]` |
| `todos` | `JSONB` | `[]` | 子任務：`[{id, title, status, detail}]` |
| `scheduler` | `JSONB` | `{}` | 調度器元數據 |
| `template_id` | `VARCHAR(64)` | `''` | 模板 ID |
| `template_params` | `JSONB` | `{}` | 模板參數 |
| `ac` | `TEXT` | `''` | 驗收標準 |
| `target_dept` | `VARCHAR(64)` | `''` | 目標部門 |

#### 時間戳

| 欄位 | 類型 | 約束 | 說明 |
|------|------|------|------|
| `created_at` | `TIMESTAMPTZ` | NOT NULL | 創建時間 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL，ON UPDATE | 最後更新時間 |

### 索引

| 索引名稱 | 欄位 | 說明 |
|----------|------|------|
| `ix_tasks_trace_id` | `trace_id` | 依追蹤 ID 查詢 |
| `ix_tasks_assignee_org` | `assignee_org` | 依部門過濾 |
| `ix_tasks_created_at` | `created_at` | 時間排序 |
| `ix_tasks_state` | `state` | 狀態過濾 |
| `ix_tasks_state_archived` | `(state, archived)` | 狀態 + 歸檔聯合過濾 |
| `ix_tasks_updated_at` | `updated_at` | 最近更新排序 |

### 狀態枚舉（TaskState）

| 狀態 | 說明 | 負責 Agent | 負責部門 |
|------|------|-----------|----------|
| `Pending` | 等待處理 | zhongshu | 中書省 |
| `Taizi` | 太子分揀 | taizi | 太子 |
| `Zhongshu` | 中書省規劃 | zhongshu | 中書省 |
| `Menxia` | 門下省審核封駁 | menxia | 門下省 |
| `Assigned` | 已派發至六部 | shangshu | 尚書省 |
| `Next` | 排隊等待 | — | 六部 |
| `Doing` | 執行中 | — | 六部 |
| `Review` | 審查階段 | shangshu | 尚書省 |
| `PendingConfirm` | 待確認 | shangshu | 尚書省 |
| `Done` | 已完成（終止態） | — | — |
| `Cancelled` | 已取消（終止態） | — | — |
| `Blocked` | 已阻塞 | — | — |

### 狀態流轉矩陣

```
Pending ────→ Taizi ────→ Zhongshu ────→ Menxia ────→ Assigned
                                                 ↙           ↓
                                            [封駁]         Doing
                                                            ↓
                                                         Review ────→ Done
                                                            ↓
                                                     PendingConfirm ────→ Done

Blocked ←→ 任意非終止態
```

---

## 二、`events` — 事件持久化表

所有系統事件的持久化記錄，支援事件回放與審計。

### 欄位定義

| 欄位 | 類型 | 約束 | 說明 |
|------|------|------|------|
| `event_id` | `UUID` | **PK**，預設 `uuid4()` | 事件唯一 ID |
| `trace_id` | `VARCHAR(64)` | NOT NULL，INDEX | 關聯任務 ID |
| `timestamp` | `TIMESTAMPTZ` | NOT NULL | 事件時間戳 |
| `topic` | `VARCHAR(128)` | NOT NULL，INDEX | 事件主題（粗分類），對應 Redis Stream key |
| `event_type` | `VARCHAR(128)` | NOT NULL | 事件細分類 |
| `producer` | `VARCHAR(128)` | NOT NULL | 事件生產者（含版本號） |
| `payload` | `JSONB` | 預設 `{}` | 事件負載（業務內容） |
| `meta` | `JSONB` | 預設 `{}` | 事件元數據（priority, model, version） |

### 索引

| 索引名稱 | 欄位 | 說明 |
|----------|------|------|
| `ix_events_trace_topic` | `(trace_id, topic)` | 依任務 + 主題查詢（最常用） |
| `ix_events_timestamp` | `timestamp` | 時間範圍查詢 |

### 範例資料

```json
{
  "event_id": "550e8400-...",
  "trace_id": "...",
  "timestamp": "2026-06-05T12:00:00+00:00",
  "topic": "task.status",
  "event_type": "state.changed",
  "producer": "task_service:v2",
  "payload": {
    "task_id": "...",
    "old_state": "Taizi",
    "new_state": "Zhongshu"
  },
  "meta": {
    "priority": "normal",
    "model": "deepseek-v4"
  }
}
```

---

## 三、`outbox_events` — 交易發件箱表

實現 Transactional Outbox Pattern，確保事件與業務數據的原子性寫入。

### 設計原理

1. 事件與業務數據在同一個 DB 事務中寫入 `outbox_events` 表
2. `OutboxRelay` worker 定期掃描 `published=false` 的記錄
3. 將事件投遞至 Redis Streams
4. 投遞成功後標記 `published=true`
5. 此模式消滅了 DB/Event 雙寫不一致問題

### 欄位定義

| 欄位 | 類型 | 約束 | 說明 |
|------|------|------|------|
| `id` | `BIGINT` | **PK**，AUTO INCREMENT | 自增主鍵 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | 創建時間 |
| `event_id` | `VARCHAR(64)` | NOT NULL，**UNIQUE** | 事件唯一 ID |
| `topic` | `VARCHAR(100)` | NOT NULL | 目標 Redis Stream topic |
| `trace_id` | `VARCHAR(64)` | NOT NULL | 關聯任務追蹤 ID |
| `event_type` | `VARCHAR(100)` | NOT NULL | 事件類型 |
| `producer` | `VARCHAR(100)` | NOT NULL | 事件生產者 |
| `payload` | `JSONB` | 預設 `{}` | 事件負載 |
| `meta` | `JSONB` | 預設 `{}` | 事件元數據 |
| `published` | `BOOLEAN` | 預設 `false`，INDEX | 是否已投遞 |
| `published_at` | `TIMESTAMPTZ` | NULLABLE | 投遞時間 |
| `attempts` | `INTEGER` | 預設 `0` | 投遞嘗試次數 |
| `last_error` | `TEXT` | NULLABLE | 最後一次錯誤訊息 |

### 索引

| 索引名稱 | 欄位 | 說明 |
|----------|------|------|
| `ix_outbox_unpublished` | `(published, id)`，WHERE `published=false` | 掃描未投遞事件（部分索引） |
| `ix_outbox_created_at` | `created_at` | 時間排序 |

---

## 四、`audit_logs` — 審計日誌表

獨立的審計日誌表，記錄所有 Agent 和系統對任務的操作。

### 設計原則

- **獨立表**：非 JSONB 欄位，支援跨任務檢索與聚合查詢
- **Append-only**：每次操作寫入一行，不做 UPDATE
- **action 分類**：`state`（狀態變更）、`flow`（流轉）、`todo`（待辦更新）、`confirm`（確認）、`memory`（記憶）、`permission_denied`（權限拒絕）

### 欄位定義

| 欄位 | 類型 | 約束 | 說明 |
|------|------|------|------|
| `id` | `BIGINT` | **PK**，AUTO INCREMENT | 自增主鍵 |
| `timestamp` | `TIMESTAMPTZ` | NOT NULL | 操作時間 |
| `task_id` | `VARCHAR(64)` | NULLABLE | 關聯任務 ID（系統級事件可為 NULL） |
| `trace_id` | `VARCHAR(64)` | NULLABLE | 追蹤鏈路 ID |
| `agent_id` | `VARCHAR(50)` | NULLABLE | 執行操作的 Agent |
| `action` | `VARCHAR(50)` | NOT NULL | 操作類型：`state` / `flow` / `todo` / `confirm` / `memory` / `permission_denied` |
| `old_value` | `JSONB` | NULLABLE | 變更前狀態 |
| `new_value` | `JSONB` | NULLABLE | 變更後狀態 |
| `reason` | `TEXT` | 預設 `''` | 操作原因 / 備註 |
| `meta` | `JSONB` | 預設 `{}` | 擴展元數據（tokens, cost, duration） |

### 索引

| 索引名稱 | 欄位 | 說明 |
|----------|------|------|
| `ix_audit_timestamp` | `timestamp` | 時間範圍查詢 |
| `ix_audit_task_id` | `task_id` | 依任務查詢 |
| `ix_audit_agent_id` | `agent_id` | 依 Agent 查詢 |
| `ix_audit_action` | `action` | 依操作類型查詢 |

### 查詢範例

```sql
-- 查詢某任務的所有審計記錄
SELECT * FROM audit_logs WHERE task_id = '...' ORDER BY timestamp DESC;

-- 查詢某 Agent 的狀態變更操作
SELECT * FROM audit_logs WHERE agent_id = 'taizi' AND action = 'state';

-- 成本分析：按 Agent 彙總 token 消耗
SELECT agent_id, SUM((meta->>'tokens')::int) AS total_tokens
FROM audit_logs
WHERE meta->>'tokens' IS NOT NULL
GROUP BY agent_id;
```

---

## 五、`thoughts` — Agent 思考流表

記錄 Agent 的思考過程，支援 streaming partial thoughts 與 Dashboard 實時展示。

### 欄位定義

| 欄位 | 類型 | 約束 | 說明 |
|------|------|------|------|
| `thought_id` | `UUID` | **PK**，預設 `uuid4()` | 思考記錄 ID |
| `trace_id` | `VARCHAR(32)` | NOT NULL，INDEX | 關聯任務 ID |
| `agent` | `VARCHAR(32)` | NOT NULL，INDEX | Agent 標識 |
| `step` | `INTEGER` | NOT NULL，預設 `0` | 思考步驟序號 |
| `type` | `VARCHAR(32)` | NOT NULL，預設 `'reasoning'` | 思考類型 |
| `source` | `VARCHAR(16)` | 預設 `'llm'` | 來源：`llm` / `tool` / `human` |
| `content` | `TEXT` | NOT NULL，預設 `''` | 思考內容 |
| `tokens` | `INTEGER` | 預設 `0` | 消耗 token 數 |
| `confidence` | `FLOAT` | 預設 `0.0` | 置信度（0–1） |
| `sensitive` | `BOOLEAN` | 預設 `false` | 是否敏感內容 |
| `timestamp` | `TIMESTAMPTZ` | NOT NULL | 時間戳 |

### 索引

| 索引名稱 | 欄位 | 說明 |
|----------|------|------|
| `ix_thoughts_trace_agent` | `(trace_id, agent)` | 依任務 + Agent 查詢 |
| `ix_thoughts_timestamp` | `timestamp` | 時間排序 |

### 思考類型枚舉

| 類型 | 說明 |
|------|------|
| `reasoning` | 推理過程 |
| `query` | 查詢操作 |
| `action_intent` | 行動意圖 |
| `summary` | 總結 |

---

## 六、`todos` — 結構化子任務表

獨立的子任務追蹤表，支援層級結構（parent_id）與 checkpoint 跟蹤。

### 欄位定義

| 欄位 | 類型 | 約束 | 說明 |
|------|------|------|------|
| `todo_id` | `UUID` | **PK**，預設 `uuid4()` | 子任務 ID |
| `trace_id` | `VARCHAR(32)` | NOT NULL，INDEX | 關聯任務 ID |
| `parent_id` | `UUID` | NULLABLE | 父級 todo_id（樹狀結構） |
| `title` | `VARCHAR(256)` | NOT NULL | 子任務標題 |
| `description` | `TEXT` | 預設 `''` | 詳細描述 |
| `owner` | `VARCHAR(64)` | 預設 `''` | 負責部門 |
| `assignee_agent` | `VARCHAR(32)` | 預設 `''` | 執行 Agent |
| `status` | `VARCHAR(32)` | NOT NULL，INDEX，預設 `'open'` | 狀態 |
| `priority` | `VARCHAR(16)` | 預設 `'normal'` | 優先級 |
| `estimated_cost` | `FLOAT` | 預設 `0.0` | 預估 token 耗費 |
| `created_by` | `VARCHAR(64)` | 預設 `''` | 創建者 |
| `checkpoints` | `JSONB` | 預設 `[]` | 檢查點：`[{name, status}]` |
| `metadata` | `JSONB` | 預設 `{}` | 擴展元數據 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | 創建時間 |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL，ON UPDATE | 更新時間 |

### 索引

| 索引名稱 | 欄位 | 說明 |
|----------|------|------|
| `ix_todos_trace_status` | `(trace_id, status)` | 依任務 + 狀態查詢 |

### 狀態枚舉

| 狀態 | 說明 |
|------|------|
| `open` | 待開始 |
| `in_progress` | 進行中 |
| `done` | 已完成 |
| `cancelled` | 已取消 |

### 優先級枚舉

| 優先級 | 說明 |
|--------|------|
| `low` | 低優先級 |
| `normal` | 一般優先級 |
| `high` | 高優先級 |
| `urgent` | 緊急 |

---

## 資料庫連線配置

透過環境變數設定（參見 `.env.example`）：

```bash
# PostgreSQL 連線
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=edict
POSTGRES_USER=edict
POSTGRES_PASSWORD=<動態生成>

# 或使用完整 URL
DATABASE_URL=postgresql+asyncpg://edict:password@localhost:5432/edict

# Redis 連線
REDIS_URL=redis://localhost:6379
```

### 連線池設定

| 參數 | 值 | 說明 |
|------|-----|------|
| `pool_size` | 10 | 基礎連線數 |
| `max_overflow` | 20 | 最大溢出連線數 |
| `pool_pre_ping` | `true` | 連線前驗證可用性 |

---

## 資料模型關聯圖

```
┌──────────────┐       ┌──────────────────┐
│    tasks     │       │  outbox_events   │
│──────────────│       │──────────────────│
│ PK task_id   │──┐    │ PK id            │
│    trace_id  │  │    │    trace_id      │
│    state     │  │    │    topic         │
│    ...       │  │    │    published     │
└──────────────┘  │    └──────────────────┘
                  │
                  │    ┌──────────────────┐
                  ├───→│     events       │
                  │    │──────────────────│
                  │    │ PK event_id      │
                  │    │ FK trace_id      │
                  │    │    topic         │
                  │    └──────────────────┘
                  │
                  │    ┌──────────────────┐
                  ├───→│   audit_logs    │
                  │    │──────────────────│
                  │    │ PK id            │
                  │    │    task_id       │
                  │    │    agent_id      │
                  │    └──────────────────┘
                  │
                  │    ┌──────────────────┐
                  ├───→│    thoughts     │
                  │    │──────────────────│
                  │    │ PK thought_id    │
                  │    │    trace_id      │
                  │    │    agent         │
                  │    └──────────────────┘
                  │
                  │    ┌──────────────────┐
                  └───→│     todos       │
                       │──────────────────│
                       │ PK todo_id       │
                       │    trace_id      │
                       │    parent_id     │
                       └──────────────────┘
```

> **注意**：`tasks.task_id` 使用 UUID 主鍵。`trace_id` 作為業務追蹤 ID，在 `tasks`、`events`、`outbox_events`、`thoughts`、`todos` 中作為關聯鍵使用。`audit_logs.task_id` 為字串（可為 NULL），與 `tasks.task_id` 鬆散關聯。
