# MarketPulse AI — Indian Financial Intelligence & Automation Platform

[![Tests](https://img.shields.io/badge/tests-187%20passed%20(100%25)-brightgreen.svg)](tests/unit/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.14-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Framework](https://img.shields.io/badge/backend-FastAPI%20%2B%20Uvicorn-009688.svg)](https://fastapi.tiangolo.com/)
[![Database](https://img.shields.io/badge/database-SQLite%20(WAL)%20%7C%20PostgreSQL%2016-336791.svg)](src/marketpulse/storage/)
[![Automation Engine](https://img.shields.io/badge/automation-n8n%20Workflow%20Engine-FF6D5A.svg)](workflows/n8n/)
[![Operating Modes](https://img.shields.io/badge/runtime-Windows%20Desktop%20%7C%20Cloud%20Docker-9C27B0.svg)](docs/cloud_deployment_guide.md)
[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fthejasteju54-lgtm%2Fagent)

**MarketPulse AI** is an India-first financial market research, intelligence, and workflow automation platform engineered for Windows desktop and cloud container environments. It combines automated official disclosure collection (BSE, NSE, SEBI, RBI), deterministic financial data normalization, verifiable evidence-backed research, n8n workflow integration, an interactive glassmorphic web dashboard, and strict human-in-the-loop safety boundaries.

---

## Table of Contents

- [Architectural Overview](#architectural-overview)
- [Port Allocation & Decoupling](#port-allocation--decoupling)
- [Key Features](#key-features)
- [Web Dashboard Experience](#web-dashboard-experience)
- [Quick Start Guide](#quick-start-guide)
- [CLI Reference](#cli-reference)
- [REST API & Webhooks](#rest-api--webhooks)
- [Production n8n Workflows](#production-n8n-workflows)
- [Security & Risk Model](#security--risk-model)
- [Cloud Deployment (Docker)](#cloud-deployment-docker)
- [Automated Test Suite](#automated-test-suite)
- [Repository Structure](#repository-structure)
- [License](#license)

---

## Architectural Overview

MarketPulse AI decouples financial data collection, synthesis, and workflow automation into clean, observable layers:

```mermaid
graph TB
    subgraph ClientInterfaces ["Client & Interaction Layer"]
        User([Analyst / Operator]) -->|Browser UI :8001| Dash[Glassmorphic Web Dashboard]
        User -->|Terminal / CLI| CLI[MarketPulse CLI]
        n8n([n8n Workflow Engine :5678]) -->|Signed Webhooks| WebhookAPI[FastAPI Webhook Router]
    end

    subgraph RuntimeEngine ["MarketPulse Runtime Engine (:8001)"]
        API[FastAPI App Engine]
        RiskPolicy[3-Tier Risk Engine & Permissions]
        Orchestrator[Task Orchestrator & State Machine]
        Security[Emergency Stop & Injection Scanner]
        Normalizer[Deterministic Normalization Engine]
        Calendar[IST Market Calendar & Trading Sessions]
        BackupMgr[Online DB Hot Backup & Restore]
    end

    subgraph ResearchPipeline ["7-Step Market Research Pipeline"]
        Col[Collector & RSS Parser]
        Map[Company Entity Resolver]
        Ev[Evidence Extraction & Provenance Hashing]
        Model[Deterministic / Ollama / Cloud Model Service]
        Rep[Report Synthesizer & Scenario Engine]
        Watch[Watchlist Evaluator & Alert Dispatcher]
    end

    subgraph PersistenceLayer ["Persistence & Storage Layer"]
        SQLite[(SQLite WAL - Desktop Mode)]
        Postgres[(PostgreSQL 16 - Cloud Mode)]
        Artifacts[artifacts/reports/ (*.md, *.json)]
        AuditLog[(mp_audit_events - Immutable Trail)]
    end

    Dash --> API
    CLI --> Orchestrator
    WebhookAPI --> Orchestrator
    API --> Orchestrator
    Orchestrator --> RiskPolicy
    Orchestrator --> Security
    Orchestrator --> ResearchPipeline
    ResearchPipeline --> Normalizer
    ResearchPipeline --> Calendar
    ResearchPipeline --> PersistenceLayer
    API --> PersistenceLayer
```

---

## Port Allocation & Decoupling

To ensure zero port collisions across desktop and automated services, ports are strictly reserved:

| Port | Service | Default Binding | Description |
| :--- | :--- | :--- | :--- |
| **8001** | **MarketPulse AI** | `127.0.0.1:8001` | FastAPI Server, Web Dashboard, REST API, & Webhook Ingestion |
| **8000** | **Personal AI** | `127.0.0.1:8000` | Base OS-level automation utilities (Win32, clipboard, browser) |
| **5678** | **n8n Container** | `127.0.0.1:5678` | Local n8n Workflow Automation Engine |

---

## Key Features

### 🇮🇳 India-First Financial Intelligence
- **Approved Primary Source Registry**: Ingests directly from Bombay Stock Exchange (BSE), National Stock Exchange (NSE), SEBI press circulars, Reserve Bank of India (RBI) notifications, and whitelisted financial feeds.
- **Strict Non-Fabrication Rule**: LLM outputs are never treated as ground truth. Every numerical metric, price observation, and date cited in research reports is immutably mapped to a cryptographic `EvidenceRecord` row.
- **IST Market Session Calendar**: Native tracking of Indian market hours (09:15–15:30 IST), pre-market (09:00–09:15), post-market closing, weekends, and gazetted NSE/BSE holidays.
- **Deterministic Financial Normalizer**: Parses Indian ticker formats (`TCS.NS`, `BSE:532540` $\to$ `TCS`) and rupee denomination strings (`₹ 1,500.50 Cr` $\to$ `15,005,000,000.00 INR`).

### 🛡️ Safety & Consequential Action Controls
- **Permanent Trading Prohibition**: Brokerage order placement, automated trading, and fund transfers are permanently hard-disabled (`ProhibitedActionError`) with immediate audit logging.
- **Human Approval Gate**: High-risk actions (file alterations, external disclosures) enter `AWAITING_APPROVAL` status and require explicit operator sign-off via the Web Dashboard or CLI before execution.
- **Global Emergency Stop**: One-click kill switch (`marketpulse emergency-stop` or Dashboard button) halts all active and queued task steps across the runtime immediately.
- **Prompt Injection Defense**: Multi-pattern scanner neutralizes instruction overrides, system-prompt extractions, and malicious payload executions.

### 🌐 Dual Desktop & Cloud Runtimes
- **Desktop Mode (`OPERATING_MODE=desktop`)**: Optimized for Windows 10/11 with SQLite WAL mode, local Ollama LLM execution, Win32 clipboard memory, and Playwright automation.
- **Cloud Mode (`OPERATING_MODE=cloud`)**: Headless container execution backed by PostgreSQL 16. Desktop GUI tools are safely disabled via `OperatingModeError`.

---

## Web Dashboard Experience

The integrated single-page web dashboard is served directly at **`http://localhost:8001/`**:

- **Active Task Tracker**: Live progress bar, step counter ($x/20$), status pill, and one-click task cancellation.
- **Today's Market Brief**: Real-time IST market session status, holiday detection, verified statistical indicators, and executive summary.
- **Research Archive**: Interactive modal viewer displaying executive summaries, 3-case scenario models (Bull, Base, Bear), and primary source citation links.
- **Watchlists & Alerts**: Tracked equity baskets (`NIFTY_CORE`, etc.) with categorized materiality alert feeds.
- **Automation & Scheduling**: Configured CRON schedules (`30 8 * * 1-5`, etc.) with instant live trigger and dry-run simulation mode.
- **Human Approval Gate**: Pending review counter and Approve/Reject decision modal.
- **Immutable Audit Trail**: Event timestamps, risk classifications, and operator actions.

---

## Quick Start Guide

### Prerequisites
- Windows 10/11 or Linux / macOS
- Python 3.11, 3.12, or 3.14
- Git
- `uv` (recommended) or `pip`

### 1. Clone the Repository
```powershell
git clone https://github.com/thejasteju54-lgtm/agent.git
cd agent
```

### 2. Set Up Virtual Environment & Dependencies
```powershell
# Using uv (fastest)
uv venv .venv
.\.venv\Scripts\activate
uv pip install -e .

# Or using standard pip
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

### 3. Configure Environment Variables
```powershell
cp .env.example .env
```
Key configuration items in `.env`:
```ini
OPERATING_MODE=desktop
MARKETPULSE_API_PORT=8001
DATABASE_URL=sqlite:///data/marketpulse.db
AI_MODEL_PROVIDER=mock    # Options: mock, ollama, cloud
LOG_LEVEL=INFO
```

### 4. Initialize Database
Apply database schema migrations (v1 through v6) and seed approved Indian sources:
```powershell
.\.venv\Scripts\marketpulse.exe init-db
```

### 5. Launch Server & Dashboard
```powershell
.\.venv\Scripts\marketpulse.exe serve --port 8001
```
Open your browser to: **`http://localhost:8001`**

---

## CLI Reference

MarketPulse AI includes a full-featured CLI:

```text
Usage: marketpulse [OPTIONS] COMMAND [ARGS]...

Commands:
  status          Inspect system health, configuration, and database records.
  init-db         Initialize database schema migrations and seed approved sources.
  test-env        Validate environment directories, settings, and write permissions.
  brief           Generate today's Indian market session brief with verified metrics.
  research        Execute on-demand research on an Indian listed company.
  collect         Ingest and normalize evidence records from approved sources.
  sources         List all approved market sources in the registry.
  watchlist       Manage monitored equity symbols and evaluate alert rules.
  schedule        Manage and trigger permitted automated schedules.
  backup          Manage hot database backups and disaster recovery.
  emergency-stop  Immediately halt all active and incoming MarketPulse tasks.
  reset-stop      Clear emergency stop flag and restore normal execution.
  serve           Start the FastAPI application server and web dashboard.
```

### Common CLI Examples

```powershell
# Check runtime status
marketpulse status

# Generate market session brief
marketpulse brief

# Perform on-demand deep equity research
marketpulse research --symbol RELIANCE --prompt "Analyze Q3 results and capex"

# Evaluate watchlist alert triggers
marketpulse watchlist evaluate

# Trigger a scheduled job in simulation / dry-run mode
marketpulse schedule trigger daily_market_brief --dry-run

# Create a hot online database backup
marketpulse backup create
```

---

## REST API & Webhooks

All endpoints are served with CORS enabled and structured error responses under `/api/v1`:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/health` | Comprehensive system, database, and n8n connectivity probe |
| `GET` | `/api/v1/ready` | Kubernetes / container readiness probe |
| `GET` | `/api/v1/tasks` | List recent automation tasks with step progress and status |
| `POST`| `/api/v1/tasks/{id}/cancel` | Cancel an active task |
| `POST`| `/api/v1/research/brief` | On-demand generation of today's IST market session brief |
| `GET` | `/api/v1/research/reports` | List generated research reports |
| `GET` | `/api/v1/research/reports/{id}`| Retrieve detailed report with 3-case scenarios and citations |
| `GET` | `/api/v1/watchlists` | Retrieve monitored equity watchlists |
| `GET` | `/api/v1/alerts/events` | Retrieve triggered alert events |
| `POST`| `/api/v1/alerts/evaluate` | Trigger watchlist alert rule evaluation |
| `GET` | `/api/v1/schedules` | List permitted automation schedules |
| `POST`| `/api/v1/schedules/{id}/trigger` | Dispatch a schedule immediately (supports dry-run) |
| `GET` | `/api/v1/approvals` | List pending human approval requests |
| `POST`| `/api/v1/approvals/{id}/decide` | Approve or reject a gated action |
| `GET` | `/api/v1/audit` | Query immutable audit events |
| `POST`| `/webhook/task` | Ingest task submission webhook (n8n compatible) |
| `POST`| `/webhook/notify` | Handle external notifications and emergency stop signals |

---

## Production n8n Workflows

Pre-built production workflows reside in `workflows/n8n/` ready for import into local or cloud n8n instances:

1. **`MP-01-daily-market-brief.json`**: Scheduled pre-session market briefing (08:30 IST). Triggers MarketPulse briefing API, checks IST trading calendar, stores report artifact, and emits notification.
2. **`MP-02-news-intelligence.json`**: Periodic 15-minute polling loop for BSE/NSE corporate disclosures and regulatory RSS feeds. Runs through deduplication and normalizer.
3. **`MP-03-on-demand-research.json`**: Webhook-triggered on-demand equity research. Dispatches research task, polls execution state, and returns synthesized scenario analysis.

---

## Security & Risk Model

MarketPulse implements a strict 3-tier risk engine:

| Risk Tier | Examples | Execution Behavior |
| :--- | :--- | :--- |
| **`LOW`** | Read-only market queries, RSS parsing, market brief generation | Executes autonomously without interruption |
| **`MEDIUM`** | Modifying research files, watchlist alert updates, local cache saves | Allowed in auto-mode; tracked with audit logs |
| **`HIGH`** | Deleting local research files, external report distribution | **Paused** in `AWAITING_APPROVAL` until approved |
| **`PROHIBITED`** | Placing brokerage orders, executing trades, fund transfers | **Permanently rejected** with `ProhibitedActionError` |

---

## Cloud Deployment (Docker)

To run MarketPulse in headless cloud mode with PostgreSQL and n8n:

```bash
# Build and launch cloud stack
docker compose -f docker-compose.cloud.yml --env-file .env.production up -d --build

# Verify health probes
curl -s http://localhost:8001/api/v1/health | jq .
```

For advanced production deployment details, see the [Cloud Deployment Guide](docs/cloud_deployment_guide.md).

---

## Automated Test Suite

MarketPulse maintains a **100% test pass rate** with 187 comprehensive unit and integration tests across 19 test modules:

```powershell
# Run the complete test suite
.\.venv\Scripts\pytest.exe tests/unit/ -v

# Run with quiet summary
.\.venv\Scripts\pytest.exe tests/unit/ -q
```

```text
===================== 187 passed, 157 warnings in 47.04s ======================
```

Coverage spans:
- SQLite WAL & PostgreSQL connection handling
- Schema migrations (v1 through v6)
- RSS parser and rate-limit backoff
- Indian currency and ticker normalizers
- IST market calendar & holiday rules
- Non-fabrication evidence persistence
- 3-tier risk engine and trading prohibitions
- Human approval gate workflow
- REST API endpoints and webhooks
- Emergency stop manager & ungraceful crash recovery
- Hot database backup & SHA-256 restore verification

---

## Repository Structure

```text
Agent/
├── .env.example                     # Environment template with sensible defaults
├── pyproject.toml                   # Project metadata and CLI entrypoints
├── Dockerfile                       # Multi-stage container definition
├── docker-compose.cloud.yml         # Cloud deployment stack (Postgres + n8n + App)
├── AGENTS.md                        # AI developer and system architecture guidelines
├── README.md                        # Project documentation
│
├── src/
│   ├── marketpulse/                 # Core MarketPulse AI runtime package
│   │   ├── agent/                   # Task orchestrator, security, and permissions
│   │   ├── api/                     # FastAPI application, routes, and schemas
│   │   ├── cli.py                   # Click CLI entry point ('marketpulse')
│   │   ├── config.py                # Central Pydantic settings loading from .env
│   │   ├── dashboard/               # Glassmorphic single-page web dashboard
│   │   │   └── static/              # HTML, CSS, and vanilla JS client controller
│   │   ├── logging/                 # Secret-redacting rotating logger
│   │   ├── n8n/                     # n8n HTTP client and webhook handlers
│   │   ├── research/                # Research collectors, normalizer, and brief
│   │   └── storage/                 # Database engine, models, migrations, and backups
│   │
│   └── personal_ai/                 # Base OS-level automation utilities
│       ├── agent/                   # Base planner and tool executor
│       ├── desktop/                 # Win32 automation and clipboard memory
│       └── tools/                   # Filesystem, browser, and system tools
│
├── workflows/
│   └── n8n/                         # Production n8n workflow definitions
│       ├── MP-01-daily-market-brief.json
│       ├── MP-02-news-intelligence.json
│       └── MP-03-on-demand-research.json
│
├── docs/                            # In-depth architectural guides and runbooks
│   ├── cloud_deployment_guide.md
│   ├── feature_status_report.md
│   └── recovery_runbook.md
│
└── tests/
    └── unit/                        # 187 automated test cases (100% passing)
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
