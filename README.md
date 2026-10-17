# Personal AI Automation System

A reliable, local-first personal AI automation system for Windows built with Python, SQLite, Playwright, and Antigravity 2.0.

---

## 1. Architecture Overview

The system is built on a modular runtime architecture:
- **CLI / Dashboard**: User interface for submitting tasks, inspecting state, approvals, and logs.
- **Task Engine & Planner**: Natural language parsing, risk assessment, tool-chain planning, and structured execution.
- **Storage Layer**: SQLite (`data/personal_ai.db`) with WAL mode, automated migrations, task lifecycle tracking, step logging, and filesystem artifact management (`artifacts/`).
- **Tool Registry**: Constrained, validated capabilities across browser (Playwright), desktop (PyAutoGUI), filesystem, and clipboard memory.
- **Security & Approvals**: Tiered risk engine (`LOW`, `MEDIUM`, `HIGH`) requiring explicit human approval for high-risk operations.
- **AI Providers**: Decoupled interface supporting local Ollama models and cloud model providers.

---

## 2. Requirements & Windows Setup

### Prerequisites
- Windows 10/11
- Python 3.11+
- Git
- `uv` (recommended) or standard `pip`

### Installation
1. Clone the repository and navigate to the project directory:
   ```powershell
   cd PersonalAI
   ```

2. Create a virtual environment using `uv`:
   ```powershell
   uv venv .venv
   .\.venv\Scripts\activate
   ```

3. Install dependencies in editable mode:
   ```powershell
   uv pip install -e . --python .\.venv\Scripts\python.exe
   ```

4. Configure environment variables:
   ```powershell
   Copy-Item .env.example .env
   ```

---

## 3. Quick Start & CLI Usage

### Initialize the Database
```powershell
.\.venv\Scripts\python.exe -m personal_ai.main init-db
```

### Inspect System Status
```powershell
.\.venv\Scripts\python.exe -m personal_ai.main status
```

### Execute Natural Language Tasks
```powershell
# Plan and execute a task
.\.venv\Scripts\python.exe -m personal_ai.main run "read file 'README.md'"

# Dry-run planning without executing
.\.venv\Scripts\python.exe -m personal_ai.main run "delete file 'temp.log'" --dry-run

# Run with auto-approval for non-interactive execution
.\.venv\Scripts\python.exe -m personal_ai.main run "save content: 'hello' to file 'output.txt'" --yes
```

### List and Inspect Tasks
```powershell
# List recent tasks
.\.venv\Scripts\python.exe -m personal_ai.main task list

# Show task details
.\.venv\Scripts\python.exe -m personal_ai.main task show <TASK_ID>

# Cancel a task
.\.venv\Scripts\python.exe -m personal_ai.main task cancel <TASK_ID>

# Approve a pending high-risk action
.\.venv\Scripts\python.exe -m personal_ai.main task approve <APPROVAL_ID>
```

---

## 4. Running Automated Tests

Run the full automated test suite using `pytest`:
```powershell
.\.venv\Scripts\pytest.exe
```

---

## 5. Implementation Roadmap & Phase Status

| Phase | Description | Status |
|---|---|---|
| **Phase 1** | **Foundation**: Config, logging, SQLite storage, repositories, CLI, tests | **COMPLETE** |
| **Phase 2** | **Working Task Runtime**: Structured planning, tool registry, execution, verification, error recovery, approvals | **COMPLETE** |
| **Phase 3** | **Browser Automation**: Playwright integration, semantic selectors, artifact capture | Next |
| **Phase 4** | **AI Providers**: Ollama & Cloud LLM adapters, structured output validation | Upcoming |
| **Phase 5** | **Clipboard Memory**: Windows clipboard monitoring, content hashing, SQLite search | Upcoming |
| **Phase 6** | **Desktop Control**: Constrained PyAutoGUI actions, screen verification | Upcoming |
| **Phase 7** | **Workflow Automation**: Local n8n integration, authenticated webhooks | Upcoming |
| **Phase 8** | **Dashboard**: Local task tracking, artifact viewer, approvals UI | Upcoming |
| **Phase 9** | **Hardening & Recovery**: Security audit, backup/restore, resilience tests | Upcoming |
