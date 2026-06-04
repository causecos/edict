<h1 align="center">⚔️ Edict · Multi-Agent Orchestration</h1>

<p align="center">
  <strong>I modeled an AI multi-agent system after China's 1,300-year-old imperial governance.<br>Turns out, ancient bureaucracy understood separation of powers better than modern AI frameworks.</strong>
</p>

<p align="center">
  <sub>12 AI agents (11 business roles + 1 compatibility role) form the Three Departments & Six Ministries: Crown Prince triages, Planning proposes, Review vetoes, Dispatch assigns, Ministries execute.<br>Built-in <b>institutional review gates</b> that CrewAI doesn't have. A <b>real-time dashboard</b> that AutoGen doesn't have.</sub>
</p>

<p align="center">
  <a href="#-demo">🎬 Demo</a> ·
  <a href="#-quick-start">🚀 Quick Start</a> ·
  <a href="#-architecture">🏛️ Architecture</a> ·
  <a href="#-features">📋 Features</a> ·
  <a href="docs/task-dispatch-architecture.md">📚 Architecture Docs</a> ·
  <a href="README.md">中文</a> ·
  <a href="README_JA.md">日本語</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/OpenClaw-Required-blue?style=flat-square" alt="OpenClaw">
  <img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Agents-12_Specialized-8B5CF6?style=flat-square" alt="Agents">
  <img src="https://img.shields.io/badge/Dashboard-Real--time-F59E0B?style=flat-square" alt="Dashboard">
  <img src="https://img.shields.io/badge/License-MIT-22C55E?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Frontend-React_18-61DAFB?style=flat-square&logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/Backend-FastAPI_+_PostgreSQL_+_Redis-EC4899?style=flat-square" alt="FastAPI + PostgreSQL + Redis">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/WeChat-cft0808-07C160?style=for-the-badge&logo=wechat&logoColor=white" alt="WeChat">
</p>

---

## 🔱 Maintained Fork Notice

> This is a **downstream fork** of [cft0808/edict](https://github.com/cft0808/edict), aimed at validating the following changes and preparing upstream PRs:

| Change | Status | Description |
|--------|--------|-------------|
| **DB-first task state** | ✅ Implemented | PostgreSQL + Redis Streams driven, switchable via `task_source_mode.py` |
| **Telegram workflow** | ✅ Implemented | Notification pipeline migrated from Feishu to Telegram, source channel tracking |
| **Traditional Chinese localization** | ✅ Implemented | Full Dashboard UI in Traditional Chinese, `fanti_convert.py` tool |
| **Local deployment hardening** | ✅ Implemented | systemd user service, `.env` secret management, `edict.sh` full-service management |
| **Security hardening** | ✅ Implemented | API Key backend authentication, dynamic password generation, audit logging |
| **Windows compatibility** | 🚧 Validating | Path resolution, shell script cross-platform adaptation |
| **Code annotation completion** | 🚧 In progress | Chinese mandatory annotations per RULES.md standard |

> Upstream [cft0808/edict](https://github.com/cft0808/edict) is the original Three Departments & Six Ministries AI multi-agent collaboration project. Changes from this fork will be gradually submitted as PRs back to upstream.

## 🆕 Recent Updates (2026-06)

- **Task data source switched to DB-first**: Dashboard `live-status` supports `db/json/auto` mode switching, with `db` recommended as default.
- **Mode switching CLI**: New `scripts/task_source_mode.py` for querying/switching data source mode and backend health status.
- **Flow consistency strengthened**: Main path uses **Event Bus** as the source of truth; CLI is for troubleshooting and remediation only.
- **Model configuration upgrade**: Each Agent can independently switch LLM and THINK; model dropdowns prioritize runtime-available items.
- **Backend security hardening**: Write endpoints enforce API Key authentication; passwords/secrets are uniformly managed via `.env` with dynamically generated random defaults.
- **Notification pipeline Telegram migration**: Migrated from Feishu to Telegram; dispatch automatically tracks the source channel of tasks and prioritizes reporting back to it.
- **Dispatch unified refactor**: Eliminated duplicate dispatch logic, unified `openclaw` path resolution, supports exponential backoff retry.
- **Traditional Chinese localization**: Added `scripts/fanti_convert.py`; full Dashboard UI in Traditional Chinese.
- **Dead code cleanup**: Removed 35 `_fanti` duplicate files and residual code in `channels/__init__.py`.
- **Stability fixes**: Compatibility layer and sync path fixes completed; current test results: **225 passed**.
- **Dashboard task classification fix**: `isEdict()` now correctly identifies UUID-format tasks, no longer misclassifying them as small tasks.
- **System deployment automation**: Added `systemd/` templates (5 user services) and `.env.example`; `install.sh` supports `install-services` + `init_env`.
- **Backend configuration centralized**: `config.py` expanded with 7 Settings fields (stall threshold, dispatch timeout, retry count, Dashboard port, etc.); Workers no longer hardcode.
- **Dashboard stability hardening**: Fixed `STATE_LABEL` undefined, `loadAll()` race condition, `isEdict()` only matching JJC- prefix, `EventBus.get_pending` missing, `flow_log` duplicate columns.
- **Dashboard port environment variable**: Supports `DASHBOARD_PORT` / `EDICT_DASHBOARD_PORT`, fallback 7891.

```bash
# Check current data source mode
python3 scripts/task_source_mode.py status

# Switch to DB mode
python3 scripts/task_source_mode.py set db
```

## 🎬 Demo

<p align="center">
  <video src="docs/Agent_video_Pippit_20260225121727.mp4" width="100%" autoplay muted loop playsinline controls>
    Your browser does not support video playback. See the GIF below or <a href="docs/Agent_video_Pippit_20260225121727.mp4">download the video</a>.
  </video>
  <br>
  <sub>🎥 Full demo: AI Multi-Agent collaboration with Three Departments & Six Ministries</sub>
</p>

<details>
<summary>📸 GIF Preview (loads faster)</summary>
<p align="center">
  <img src="docs/demo.gif" alt="Edict Demo" width="100%">
  <br>
  <sub>Issue edict via Telegram → Crown Prince triage → Planning → Review → Ministries execute in parallel → Report back (30s)</sub>
</p>
</details>

> 🐳 **No OpenClaw?** Run `docker run -p 7891:7891 cft0808/edict` to try the full dashboard with simulated data.

---

## 🤔 Why Three Departments & Six Ministries?

Most multi-agent frameworks follow this pattern:

> *"Here, you AIs talk among yourselves, then give me the result."*

And you get a blob of output with no idea how it was produced — not reproducible, not auditable, not intervenable.

**Edict takes a completely different approach** — we use a governance system that ran China for 1,400 years:

```
You (Emperor) → Crown Prince (Triage) → Planning Dept → Review Dept → Dispatch Dept → 6 Ministries → Report Back
```

This isn't a cute metaphor. It's **real separation of powers**:

| | CrewAI | MetaGPT | AutoGen | **Edict** |
|---|:---:|:---:|:---:|:---:|
| **Review mechanism** | ❌ None | ⚠️ Optional | ⚠️ Human-in-loop | **✅ Dedicated Review Dept · Can veto** |
| **Real-time dashboard** | ❌ | ❌ | ❌ | **✅ Kanban + Timeline** |
| **Task intervention** | ❌ | ❌ | ❌ | **✅ Stop / Cancel / Resume** |
| **Audit trail** | ⚠️ | ⚠️ | ❌ | **✅ Full memorial archive** |
| **Agent health monitoring** | ❌ | ❌ | ❌ | **✅ Heartbeat + activity detection** |
| **Hot-swap LLM models** | ❌ | ❌ | ❌ | **✅ One-click from dashboard** |
| **Skill management** | ❌ | ❌ | ❌ | **✅ View / Add skills** |
| **News aggregation** | ❌ | ❌ | ❌ | **✅ Daily briefing + Telegram push** |
| **Setup complexity** | Medium | High | Medium | **Low · One-click / Docker** |

> **Core differentiator: Institutional review + Full observability + Real-time intervention**

<details>
<summary><b>🔍 Why the "Review Department" is the killer feature (click to expand)</b></summary>

<br>

CrewAI and AutoGen agents work in a **"done, ship it"** mode — no one checks output quality. It's like a company with no QA department where engineers push code straight to production.

Edict's **Review Department (门下省)** exists specifically for this:

- 📋 **Audit plan quality** — Is the Planning Department's decomposition complete and sound?
- 🚫 **Veto subpar output** — Not a warning. A hard reject that forces re-planning.
- 🔄 **Mandatory rework loop** — Nothing passes until it meets standards.

This isn't an optional plugin — **it's part of the architecture**. Every edict must pass through Review. No exceptions.

This is why Edict produces reliable results on complex tasks: there's a mandatory quality gate before anything reaches execution. Emperor Taizong figured this out 1,300 years ago — **unchecked power inevitably produces errors**.

</details>

---

## ✨ Features

### 🏛️ Twelve-Department Agent Architecture
- **Crown Prince** (太子) message triage — auto-reply casual chat, create tasks for real edicts
- **Three Departments** (Secretariat · Chancellery · Department of State Affairs) for planning, review, and dispatch
- **Seven Ministries** (Finance · Rites · Engineering · Justice · Works · Personnel + Morning Briefing) for specialized execution
- Strict permission matrix — who can message whom is explicitly enforced
- **State transition validation** — `kanban_update.py` enforces legal transition paths; illegal state jumps are rejected
- Each agent: independent workspace, independent skills, independent LLM model
- **Edict data sanitization** — auto-strips file paths, metadata, invalid prefixes from titles/remarks

### 📋 Command Center Dashboard (11 Panels)

<table>
<tr><td width="50%">

**📋 Edicts Kanban**
- Task cards by state columns
- Department filter + full-text search
- Heartbeat badges (🟢Active 🟡Stale 🔴Alert)
- Task detail + full transition chain
- Stop / Cancel / Resume operations

</td><td width="50%">

**🔭 Department Monitor**
- Visualize task counts by state
- Horizontal bar chart by department
- Real-time Agent health status cards

</td></tr>
<tr><td>

**📜 Memorial Archive**
- Completed edicts auto-archived as memorials
- 5-phase timeline: Edict → Planning → Review → Ministries → Report
- One-click copy as Markdown
- Filter by status

</td><td>

**📜 Edict Template Library**
- 9 preset edict templates
- Category filter · Parameter forms · Time/cost estimates
- Preview edict → One-click dispatch

</td></tr>
<tr><td>

**👥 Officials Overview**
- Token consumption leaderboard
- Activity · Completion count · Session stats

</td><td>

**📰 Daily Briefing**
- Auto-curated tech/finance news daily
- Category subscription management + Telegram push

</td></tr>
<tr><td>

**⚙️ Model Config**
- Per-agent independent LLM and THINK switching
- Auto-restart Gateway on apply (~5s, model and THINK sync)

</td><td>

**🛠️ Skills Config**
- View installed skills per department
- View details + add new skills

</td></tr>
<tr><td>

**💬 Small Tasks · Sessions**
- OC-* session real-time monitoring
- Source channel · Heartbeat · Message preview

</td><td>

**🎬 Court Ceremony**
- Opening animation on first daily visit
- Today's stats · 3.5s auto-dismiss

</td></tr>
<tr><td>

**🏛️ Court Discussion**
- Multi-official debate on topics from departmental perspectives
- LLM-driven multi-role debate (each department contributes expertise)
- Multi-round advancement · Conclusion summary · Discussion record retention

</td><td>

</td></tr>
</table>

---

## 🖼️ Screenshots

### Edicts Kanban
![Kanban](docs/screenshots/01-kanban-main.png)

<details>
<summary>📸 More screenshots</summary>

### Department Monitor
![Monitor](docs/screenshots/02-monitor.png)

### Task Transition Detail
![Task Detail](docs/screenshots/03-task-detail.png)

### Model Config
![Models](docs/screenshots/04-model-config.png)

### Skills Config
![Skills](docs/screenshots/05-skills-config.png)

### Officials Overview
![Officials](docs/screenshots/06-official-overview.png)

### Sessions
![Sessions](docs/screenshots/07-sessions.png)

### Memorials Archive
![Memorials](docs/screenshots/08-memorials.png)

### Edict Templates
![Templates](docs/screenshots/09-templates.png)

### Daily Briefing
![Briefing](docs/screenshots/10-morning-briefing.png)

### Court Ceremony
![Ceremony](docs/screenshots/11-ceremony.png)

</details>

---

## 🚀 Quick Start

### Docker

```bash
docker run -p 7891:7891 cft0808/sansheng-demo
```
Open http://localhost:7891 to access the Command Center Dashboard.

<details>
<summary><b>⚠️ Getting <code>exec format error</code>? (click to expand)</b></summary>

If you see this on **x86/amd64** machines (Ubuntu, WSL2):
```
exec /usr/local/bin/python3: exec format error
```

This is an architecture mismatch. Use the `--platform` flag:
```bash
docker run --platform linux/amd64 -p 7891:7891 cft0808/sansheng-demo
```

Or use docker-compose (with `platform: linux/amd64` built in):
```bash
docker compose up
```

</details>

### Full Install

**Prerequisites:**
- [OpenClaw](https://openclaw.ai) installed
- Python 3.10+
- macOS / Linux

**Install:**

```bash
git clone https://github.com/cft0808/edict.git
cd edict
chmod +x install.sh && ./install.sh
```

The installer automatically:
- ✅ Creates full Agent Workspaces (including Crown Prince / HR / Morning Briefing, compatible with historical `main`)
- ✅ Writes SOUL.md personality files for each department (role persona + workflow rules + data sanitization standards)
- ✅ Generates `.env` config file (API Key and database passwords, with dynamically generated random defaults)
- ✅ Registers Agents and permission matrix in `openclaw.json`
- ✅ **Symlinks unified data** (each workspace's data/scripts → project directory, ensuring data consistency)
- ✅ **Sets Agent-to-Agent communication visibility** (`sessions.visibility all`, resolves unreachable message issues)
- ✅ **Syncs API Key to all Agents** (auto-copies from already-configured Agent)
- ✅ Builds React frontend (requires Node.js 18+; skipped if not installed)
- ✅ Initializes data directory + first data sync (including official stats)
- ✅ Restarts Gateway to apply configuration

> ⚠️ **First install**: Configure API Key first: `openclaw agents add taizi`, then re-run `./install.sh` to sync to all Agents.

**Launch:**

```bash
# Option 1: One-click launch (recommended)
chmod +x start.sh && ./start.sh

# Option 2: Manual launch
bash scripts/run_loop.sh &      # Data refresh loop
python3 dashboard/server.py     # Dashboard server

# Open browser
open http://127.0.0.1:7891
```

<details>
<summary><b>🖥️ Production deployment (systemd user)</b></summary>

Edict uses **user-level systemd** to manage backend services — no root privileges required:

```bash
# Install systemd user services (from edict.sh in repo)
bash edict.sh install-services

# Start / Stop all
bash edict.sh start-all
bash edict.sh stop-all

# Individual management
systemctl --user start edict-backend          # FastAPI backend (port 8000)
systemctl --user start edict-dispatch-worker  # Dispatch Worker
systemctl --user start edict-orchestrator     # DAG Orchestrator
systemctl --user start edict-outbox-relay     # Outbox Relay

# Check status / logs
bash edict.sh status
journalctl --user -u edict-backend -f         # Live logs
```

</details>

> 💡 **Dashboard works out of the box**: `server.py` embeds `dashboard/dashboard.html`; the Docker image includes a pre-built React frontend.

> 💡 See the [Getting Started Guide](docs/getting-started.md) for detailed walkthrough.

---

## 🏛️ Architecture

```
                           ┌───────────────────────────────────┐
                           │         👑 Emperor (You)           │
                           │     Telegram · Signal              │
                           └─────────────────┬─────────────────┘
                                             │ Issue edict
                           ┌─────────────────▼─────────────────┐
                           │     👑 Crown Prince (太子)          │
                           │   Triage: chat → reply / cmd → task │
                           └─────────────────┬─────────────────┘
                                             │ Forward edict
                           ┌─────────────────▼─────────────────┐
                           │    📜 Secretariat (中书省)          │
                           │   Receive → Plan → Decompose       │
                           └─────────────────┬─────────────────┘
                                             │ Submit for review
                           ┌─────────────────▼─────────────────┐
                           │    🔍 Chancellery (门下省)          │
                           │   Audit → Approve / Veto 🚫        │
                           └─────────────────┬─────────────────┘
                                             │ Approved ✅
                           ┌─────────────────▼─────────────────┐
                           │  📮 Dept. of State Affairs (尚书省)  │
                           │  Assign → Coordinate → Collect     │
                           └───┬──────┬──────┬──────┬──────┬───┘
                               │      │      │      │      │
                         ┌─────▼┐ ┌───▼───┐ ┌▼─────┐ ┌───▼─┐ ┌▼─────┐
                         │💰 Fin.│ │📝 Rites│ │⚔️ Eng.│ │⚖️ Just.│ │🔧 Works│
                         │ 户部  │ │ 礼部   │ │ 兵部  │ │ 刑部  │ │ 工部  │
                         │ Data  │ │ Docs   │ │ Code  │ │Compl. │ │ Infra │
                         └──────┘ └───────┘ └──────┘ └─────┘ └──────┘
                                                               ┌──────┐
                                                               │📋 HR  │
                                                               │ 吏部  │
                                                               │Person.│
                                                               └──────┘
```

### Agent Roles

| Dept | Agent ID | Role | Expertise |
|------|----------|------|-----------|
| 👑 **Crown Prince** | `taizi` | Message triage, requirement summarization | Chat detection, edict extraction, title summarization |
| 📜 **Secretariat** | `zhongshu` | Receive edicts, plan, decompose | Requirements understanding, task decomposition, solution design |
| 🔍 **Chancellery** | `menxia` | Audit, gatekeep, veto | Quality review, risk identification, standards enforcement |
| 📮 **Dept. of State Affairs** | `shangshu` | Assign, coordinate, collect | Task scheduling, progress tracking, result integration |
| 💰 **Finance** | `hubu` | Data, resources, accounting | Data processing, report generation, cost analysis |
| 📝 **Rites** | `libu` | Documentation, standards, reports | Technical docs, API docs, standards formulation |
| ⚔️ **Engineering** | `bingbu` | Code, algorithms, inspection | Feature development, bug fixes, code review |
| ⚖️ **Justice** | `xingbu` | Security, compliance, audit | Security scanning, compliance checks, red-line enforcement |
| 🔧 **Works** | `gongbu` | CI/CD, deployment, tooling | Docker config, pipelines, automation |
| 📋 **Personnel** | `libu_hr` | HR, Agent management | Agent registration, permission maintenance, training |
| 🌅 **Morning Briefing** | `zaochao` | Daily briefing, news aggregation | Scheduled announcements, data summaries |

### Permission Matrix

> Not everyone can message everyone — true separation of powers.

| From ↓ \ To → | Crown Prince | Secretariat | Chancellery | State Affairs | Fin. | Rites | Eng. | Just. | Works | HR |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Crown Prince** | — | ✅ | | | | | | | | |
| **Secretariat** | ✅ | — | ✅ | ✅ | | | | | | |
| **Chancellery** | | ✅ | — | ✅ | | | | | | |
| **State Affairs** | | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Ministries+HR** | | | | ✅ | | | | | | |

### Task State Machine

```
Emperor → Crown Prince Triage → Secretariat Planning → Chancellery Review → Assigned → Executing → Pending Review → ✅ Completed
                      ↑                    │                                   │
                      └─── Veto ──────────┘                          Blocked ──
```

> ⚡ **State transitions are protected**: `kanban_update.py` has a built-in `_VALID_TRANSITIONS` state machine validator.
> Illegal jumps (e.g. Doing→Taizi) are rejected and logged, ensuring the flow cannot be bypassed.
>
> 🔄 **Async event-driven**: Services communicate via Redis Streams EventBus with decoupled pub/sub. Outbox Relay ensures reliable event delivery.
> All state changes are automatically written to the audit log (`audit.py`) for full traceability.

### 🔄 Async Backend Architecture

Edict's task flow is powered by a **PostgreSQL + Redis Streams** async backend, ensuring reliable event delivery and state consistency:

| Service | Tech | Description |
|---------|------|-------------|
| **Backend API** | FastAPI + SQLAlchemy | Task / Audit / Outbox persistence, RESTful API (port 8000) |
| **EventBus** | Redis Streams | Event bus, decoupled pub/sub between services |
| **Dispatch Worker** | Python asyncio | Parallel dispatch, exponential backoff retry + resource lock |
| **Orchestrator** | DAG parsing | Task decomposition and dependency topological sort |
| **Outbox Relay** | Transactional Outbox | At-least-once event delivery guarantee, prevents loss |

#### Systemd Service Management

```bash
# Start all
bash edict.sh start-all

# Individual management
systemctl --user start edict-backend          # FastAPI backend
systemctl --user start edict-dispatch-worker  # Dispatch Worker
systemctl --user start edict-orchestrator     # DAG Orchestrator
systemctl --user start edict-outbox-relay     # Outbox Relay

# Check status
bash edict.sh status
```

#### Security Mechanisms

- **API Key Authentication**: All write endpoints enforce `X-API-Key` header validation
- **.env Secret Management**: Passwords/Tokens are uniformly loaded from `.env`, with defaults dynamically generated via `secrets.token_urlsafe(32)`
- **Audit Logging**: All state changes are automatically written to the `audit` table for full traceability

---

## 📁 Project Structure

```
edict/
├── agents/                     # 12 Agent personality templates
│   ├── taizi/SOUL.md           # Crown Prince · Message triage (incl. edict title standards)
│   ├── zhongshu/SOUL.md        # Secretariat · Planning hub
│   ├── menxia/SOUL.md          # Chancellery · Review gatekeeper
│   ├── shangshu/SOUL.md        # Dept. of State Affairs · Dispatch brain
│   ├── hubu/SOUL.md            # Finance · Data & resources
│   ├── libu/SOUL.md            # Rites · Documentation & standards
│   ├── bingbu/SOUL.md          # Engineering · Implementation
│   ├── xingbu/SOUL.md          # Justice · Compliance & audit
│   ├── gongbu/SOUL.md          # Works · Infrastructure
│   ├── libu_hr/                # Personnel · HR management
│   └── zaochao/SOUL.md         # Morning Briefing · Intelligence hub
├── dashboard/
│   ├── dashboard.html          # Command Center Dashboard (single file · zero deps · ~3400 lines)
│   ├── dist/                   # React frontend build output (included in Docker image, optional locally)
│   ├── auth.py                 # Dashboard login authentication
│   ├── court_discuss.py        # Court Discussion (multi-official LLM debate engine)
│   └── server.py               # API server (Python stdlib · zero deps · ~3200 lines)
├── edict/backend/              # Async backend services (SQLAlchemy + Redis)
│   ├── app/models/
│   │   ├── task.py             # Task model + state machine
│   │   ├── audit.py            # Audit log model
│   │   └── outbox.py           # Outbox message model
│   ├── app/services/
│   │   ├── event_bus.py        # Redis Streams EventBus
│   │   └── task_service.py     # Task service layer
│   └── app/workers/
│       ├── dispatch_worker.py  # Parallel dispatch + retry + resource lock
│       ├── orchestrator_worker.py  # DAG Orchestrator
│       └── outbox_relay.py     # Transactional Outbox Relay
├── scripts/
│   ├── run_loop.sh             # Data refresh loop (every 15s)
│   ├── kanban_update.py        # Kanban CLI (edict data sanitization + title validation + state machine)
│   ├── tg_cli.py               # Telegram-friendly task CLI
│   ├── skill_manager.py        # Skill management tool (remote/local skill add, update, remove)
│   ├── refresh_watcher.py      # Data change watcher
│   ├── sync_from_openclaw_runtime.py
│   ├── sync_agent_config.py
│   ├── apply_thinking_changes.py
│   ├── sync_officials_stats.py
│   ├── fetch_morning_news.py
│   ├── refresh_live_data.py
│   ├── apply_model_changes.py
│   └── file_lock.py            # File lock (prevents concurrent writes from multiple Agents)
├── tests/
│   ├── test_e2e_kanban.py      # End-to-end tests (21 assertions)
│   └── test_state_machine_consistency.py  # State machine consistency tests
├── data/                       # Runtime data (gitignored)
├── docs/
│   ├── task-dispatch-architecture.md  # 📚 Detailed architecture: task dispatch, flow, scheduling (business + technical)
│   ├── getting-started.md             # Quick start guide
│   ├── wechat-article.md              # WeChat article
│   └── screenshots/                   # Feature screenshots (11 images)
├── install.sh                  # One-click installer
├── start.sh                    # One-click launch (Dashboard + data refresh)
├── edict.service               # systemd service config (production deploy)
├── edict.sh                    # Service management script (start/stop/restart/status)
├── RULES.md                    # Development rules (dead code / security / testing / documentation standards)
├── .env.example                # Environment variable template
├── CONTRIBUTING.md             # Contributing guide
└── LICENSE                     # MIT License
```

---

## 🎯 Usage

### Issuing Edicts to AI

Send a message to the Secretariat via Telegram / Signal:

```
Design a user registration system for me, requirements:
1. RESTful API (FastAPI)
2. PostgreSQL database
3. JWT authentication
4. Complete test cases
5. Deployment documentation
```

**Then sit back and watch:**

1. 📜 Secretariat receives the edict, plans subtask assignments
2. 🔍 Chancellery reviews the plan, approves or vetoes for re-planning
3. 📮 Dept. of State Affairs approves and dispatches to Engineering + Works + Rites
4. ⚔️ Ministries execute in parallel, progress visible in real time
5. 📮 Dept. of State Affairs collects results and reports back

Monitor everything in the **Command Center Dashboard**; **stop, cancel, or resume** at any time.

### Using Edict Templates

> Dashboard → 📜 Template Library → Select template → Fill parameters → Issue edict

9 preset templates: Weekly Report · Code Review · API Design · Competitive Analysis · Data Report · Blog Post · Deployment Plan · Email Copy · Standup Summary

### Customizing Agents

Edit `agents/<id>/SOUL.md` to modify an Agent's personality, responsibilities, and output standards.

### Adding Skills (from the web)

**Three ways to add Skills:**

#### 1️⃣ Dashboard UI (easiest)

```
Dashboard → 🔧 Skills Config → ➕ Add Remote Skill
→ Enter Agent + Skill name + GitHub URL
→ Confirm → ✅ Done
```

#### 2️⃣ CLI Commands (most flexible)

```bash
# Add mmx_cli skill from GitHub to Chancellery
python3 scripts/skill_manager.py add-remote \
  --agent menxia \
  --name mmx_cli \
  --source https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md \
  --description "MiniMax multimodal CLI skill"

# One-click import default skills to specified agents
python3 scripts/skill_manager.py import-official-hub \
  --agents menxia,shangshu

# List all added remote skills
python3 scripts/skill_manager.py list-remote

# Update a skill to the latest version
python3 scripts/skill_manager.py update-remote \
  --agent menxia \
  --name mmx_cli
```

#### 3️⃣ API Requests (automation)

```bash
# Add remote skill
curl -X POST http://localhost:7891/api/add-remote-skill \
  -H "Content-Type: application/json" \
  -d '{
    "agentId": "menxia",
    "skillName": "mmx_cli",
    "sourceUrl": "https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md",
    "description": "MiniMax multimodal CLI skill"
  }'

# List all remote skills
curl http://localhost:7891/api/remote-skills-list
```

**Default importable Skills:**

Supported Skills:
- `mmx_cli` — MiniMax multimodal CLI skill (text, images, video, audio, music, search)

If you have your own Skills Hub, configure a custom source via `OPENCLAW_SKILLS_HUB_BASE` or `~/.openclaw/skills-hub-url`.

See [🎓 Remote Skills Resource Management Guide](docs/remote-skills-guide.md)

---

## 🔧 Technical Highlights

| Feature | Description |
|---------|-------------|
| **React 18 Frontend** | TypeScript + Vite + Zustand state management, 13 functional components |
| **Pure stdlib Dashboard** | `server.py` based on `http.server`, zero dependencies, serving both API + static files |
| **FastAPI Backend** | `edict/backend/` uses FastAPI + SQLAlchemy + Redis, providing EventBus, Outbox Relay, parallel dispatch, and more |
| **EventBus** | Redis Streams pub/sub for decoupled service communication |
| **Outbox Relay** | Transactional Outbox pattern for reliable event delivery (at-least-once semantics) |
| **State Machine Audit** | Strict lifecycle state transitions + full audit logging (`audit.py`) |
| **Parallel Dispatch Engine** | Dispatch Worker with parallel execution, exponential backoff retry, resource locking |
| **DAG Orchestrator** | Task decomposition and dependency resolution via DAG |
| **Agent Thinking Visible** | Real-time display of agent thinking process, tool calls, results |
| **One-click Install / Launch** | `install.sh` auto-configures, `start.sh` launches all services |
| **systemd Production Deploy** | `edict.service` + user-level systemd, auto-start on boot |
| **15s Auto-sync** | Live data refresh with countdown |
| **Dashboard Auth** | `auth.py` provides login authentication |
| **Daily Ceremony** | Immersive opening animation on first daily visit |
| **Remote Skills Ecosystem** | One-click skill import from GitHub/URL, version management + CLI + API + UI |

---

## 📚 Deep Dive

### Core Documentation

- **[📖 Task Dispatch Architecture](docs/task-dispatch-architecture.md)** — **Must-read document**
  - Detailed explanation of how the Three Departments & Six Ministries handle complex tasks: business design and technical implementation
  - Covers: 9-task state machine / permission matrix / 4-stage dispatch (retry→escalate→rollback) / Session JSONL data fusion
  - Includes complete usage cases, API endpoint documentation, CLI tool documentation
  - Benchmarked against CrewAI/AutoGen: why institutional governance > free-form collaboration
  - Failure scenarios and recovery mechanisms
  - **Reading this will make you understand why Edict is so powerful** (9500+ words, ~30 min for full understanding)

- **[🎓 Remote Skills Resource Management Guide](docs/remote-skills-guide.md)** — Skills ecosystem
  - Connect and add skills from the web, supporting GitHub/Gitee/any HTTPS URL
  - Default Skills source and custom Hub support
  - CLI tools + Dashboard UI + RESTful API
  - Skills file standards and security protection
  - Version management and one-click updates

- **[⚡ Remote Skills Quick Start](docs/remote-skills-quickstart.md)** — 5-minute quick start
  - Quick experience, CLI commands, Dashboard operation examples
  - Create your own Skills library
  - Complete API reference + FAQ

- **[🚀 Getting Started Guide](docs/getting-started.md)** — New user onboarding
- **[🤝 Contributing Guide](CONTRIBUTING.md)** — Want to contribute? Start here

---

## 🔧 Troubleshooting

<details>
<summary><b>❌ Tasks always timeout / subordinates finish but can't report back to Crown Prince</b></summary>

**Symptoms**: Ministries or Dept. of State Affairs complete tasks, but Crown Prince never receives the report, eventually timing out.

**Diagnostic steps**:

1. **Check Agent registration status**:
```bash
curl -s http://127.0.0.1:7891/api/agents-status | python3 -m json.tool
```
Confirm the `taizi` agent's `statusLabel` is `alive`.

2. **Check Gateway logs**:
```bash
ls /tmp/openclaw/ | tail -5          # Find latest log
grep -i "error\|fail\|unknown" /tmp/openclaw/openclaw-*.log | tail -20
```

3. **Common causes**:
   - Agent ID mismatch (fixed in v1.2: `main` → `taizi`)
   - LLM provider timeout (auto-retry added)
   - Zombie Agent processes (run `ps aux | grep openclaw` to check)

4. **Force retry**:
```bash
# Manually trigger patrol scan (auto-retry stuck tasks)
curl -X POST http://127.0.0.1:7891/api/scheduler-scan \
  -H 'Content-Type: application/json' -d '{"thresholdSec":60}'
```

</details>

<details>
<summary><b>❌ Docker: exec format error</b></summary>

**Symptom**: `exec /usr/local/bin/python3: exec format error`

**Cause**: Image architecture (arm64) doesn't match host architecture (amd64).

**Solution**:
```bash
# Method 1: Specify platform
docker run --platform linux/amd64 -p 7891:7891 cft0808/sansheng-demo

# Method 2: Use docker-compose (with platform built in)
docker compose up
```

</details>

<details>
<summary><b>❌ Skill download failure</b></summary>

**Symptom**: `python3 scripts/skill_manager.py import-official-hub` throws an error.

**Diagnosis**:
```bash
# Test network connectivity
curl -I https://raw.githubusercontent.com/MiniMax-AI/cli/main/skill/SKILL.md

# If timeout, use a proxy
export https_proxy=http://your-proxy:port
python3 scripts/skill_manager.py import-official-hub --agents menxia
```

**Common causes**:
- Accessing GitHub raw resources from certain regions may require a proxy
- Network timeout (increased to 30 seconds + 3 auto-retries)
- Default skill source unreachable, or custom Skills Hub configuration error

</details>

<details>
<summary><b>❌ After modifying backend code, API returns old data / agent list doesn't update</b></summary>

**Symptom**: After editing `backend/app/api/agents.py`, `config.py`, or other Python files, the API still returns pre-edit content. E.g., wrong agent count, unchanged field values.

**Cause**: Python compiles `.py` to `__pycache__/*.pyc` cache files. When `systemctl restart` restarts the backend, if `.pyc` timestamps are newer than `.py` (or due to multi-version Python bytecode confusion across versions), uvicorn loads old bytecode instead of new source.

**Solution**: After modifying any backend Python file, always clear the cache before restarting:

```bash
# 1. Clear all __pycache__
find ~/ai-base/core/edict/edict/backend -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# 2. Restart backend
systemctl --user restart edict-backend

# 3. Verify (using agents endpoint as example)
curl -s http://127.0.0.1:8000/api/agents | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Agent count: {len(d[\"agents\"])}')  # Should be 11
for a in d['agents']:
    print(f'  {a[\"id\"]:12s} {a[\"name\"]}')
"
```

**Prevention**: If you have multiple Python versions installed (e.g., 3.11 + 3.12), each generates its own `.pyc` files, making confusion more likely. Consider adding an auto-cache-clear step to `edict.sh` or your deployment script.

</details>

---

## 🗺️ Roadmap

> Full roadmap with contribution opportunities: [ROADMAP.md](ROADMAP.md)

### Phase 1 — Core Architecture ✅
- [x] Twelve-department Agent architecture (Crown Prince + 3 Depts + 7 Ministries + Morning Briefing) + permission matrix
- [x] Command Center real-time dashboard (11 functional panels + real-time activity panel)
- [x] Task stop / cancel / resume
- [x] Memorial system (auto-archive + 5-phase timeline)
- [x] Edict template library (9 presets + parameter forms)
- [x] Court ceremony immersive animation
- [x] Daily briefing + Telegram push + subscription management
- [x] Hot-swap LLM models + skill management + skill addition
- [x] Officials overview + Token consumption stats
- [x] Small tasks / session monitoring
- [x] Crown Prince message triage (auto-reply casual chat / create task for edicts)
- [x] Edict data sanitization (path/metadata/prefix auto-stripping)
- [x] Duplicate task protection + completed task protection
- [x] End-to-end test coverage (21 assertions)
- [x] React 18 frontend refactor (TypeScript + Vite + Zustand · 13 components)
- [x] Agent thinking process visualization (real-time thinking / tool calls / results)
- [x] Frontend-backend unified deployment (server.py serves both API + static files)

### Phase 2 — Institutional Depth 🚧
- [ ] Imperial approval mode (human-in-the-loop)
- [x] Merit/demerit ledger (Agent scoring + model recommendation + cost optimization)
- [x] EventBus (Redis Streams decoupled communication)
- [x] Outbox Relay (transactional event delivery)
- [x] State machine audit (strict lifecycle + audit logging)
- [x] Parallel dispatch engine (exponential backoff retry + resource lock)
- [x] DAG Orchestrator (task decomposition + dependency resolution)
- [x] Dashboard authentication (login auth)
- [x] One-click launch / systemd production deploy
- [ ] Express courier (inter-agent real-time message flow visualization)
- [ ] Imperial Archives (knowledge base retrieval + citation tracing)

### Phase 3 — Ecosystem
- [ ] Docker Compose + Demo image
- [ ] Notion / Linear adapters
- [ ] Annual review (yearly Agent performance reports)
- [ ] Mobile responsive + PWA
- [ ] ClawHub marketplace listing

---

## 🤝 Contributing

All contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md)

Especially welcome directions:
- 🎨 **UI enhancements**: Dark/light themes, responsiveness, animation polish
- 🤖 **New Agents**: Specialized Agent roles for specific scenarios
- 📦 **Skills ecosystem**: Ministry-specific skill packages
- 🔗 **Integrations**: Notion · Jira · Linear · GitHub Issues
- 🌐 **Internationalization**: Japanese · Korean · Spanish
- 📱 **Mobile**: Responsive adaptation, PWA

---

## 📂 Examples

The `examples/` directory contains real end-to-end use cases:

| Example | Edict | Departments |
|---------|-------|-------------|
| [Competitive Analysis](examples/competitive-analysis.md) | "Analyze CrewAI vs AutoGen vs LangGraph" | Secretariat→Chancellery→Finance+Engineering+Rites |
| [Code Review](examples/code-review.md) | "Review this FastAPI code for security issues" | Secretariat→Chancellery→Engineering+Justice |
| [Weekly Report](examples/weekly-report.md) | "Generate this week's engineering team report" | Secretariat→Chancellery→Finance+Rites |

Each case includes: Full edict → Secretariat plan → Chancellery review feedback → Ministry outputs → Final memorial.

---

## ⭐ Star History

If this project makes you smile, please give it a Star ⚔️

[![Star History Chart](https://api.star-history.com/svg?repos=cft0808/edict&type=Date)](https://star-history.com/#cft0808/edict&Date)

---

## 📮 The Emperor's Gazette — WeChat

> *In ancient China, the "Dǐbào" (imperial gazette) delivered edicts across the empire. Today we have a WeChat account.*

<p align="center">
  <img src="docs/assets/wechat-qrcode.jpg" width="220" alt="WeChat QR · cft0808">
  <br><br>
  <b>👆 Scan to follow · cft0808</b>
</p>

What you'll find:
- 🏛️ **Architecture deep-dives** — How do the 12 agents achieve separation of powers?
- 🔥 **War stories** — When agents fight, burn tokens, or go on strike
- 🛠️ **Issue fix chronicles** — Every bug is a memorial; see how the Emperor marks it in red
- 💡 **Token-saving tricks** — Run the full pipeline at 1/10 the cost
- 🎭 **Agent persona Easter eggs** — How the Six Ministries' SOUL.md files were written

> *"I made AI attend court, and the AI turned out more diligent than me."* — You'll understand after following.

---

## 📄 License

[MIT](LICENSE) · Built by the [OpenClaw](https://openclaw.ai) community

---

<p align="center">
  <strong>⚔️ Governing AI with the wisdom of ancient empires</strong><br>
  <sub>以古制御新技，以智慧驾驭 AI</sub><br><br>
  <a href="#-the-emperors-gazette--wechat"><img src="https://img.shields.io/badge/WeChat_cft0808-Follow_for_updates-07C160?style=for-the-badge&logo=wechat&logoColor=white" alt="WeChat"></a>
</p>
