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

### AI Model Provider Diagnostics
```powershell
# Check health of local Ollama and Cloud providers
.\.venv\Scripts\python.exe -m personal_ai.main model status

# Test text generation with a provider (mock, ollama, or cloud)
.\.venv\Scripts\python.exe -m personal_ai.main model test "Explain the word automation" --provider mock
```

### Clipboard Memory
```powershell
# List recent clipboard entries
.\.venv\Scripts\python.exe -m personal_ai.main clipboard list

# Search clipboard history
.\.venv\Scripts\python.exe -m personal_ai.main clipboard search "meeting"

# Copy text to Windows clipboard
.\.venv\Scripts\python.exe -m personal_ai.main clipboard copy "Important reminder"

# Capture current Windows clipboard to history immediately
.\.venv\Scripts\python.exe -m personal_ai.main clipboard capture

# Clear clipboard history
.\.venv\Scripts\python.exe -m personal_ai.main clipboard clear --yes
```

### Desktop Automation & Control
```powershell
# Inspect display resolution and active window details
.\.venv\Scripts\python.exe -m personal_ai.main desktop screen

# List visible application windows and geometry
.\.venv\Scripts\python.exe -m personal_ai.main desktop windows

# Focus window matching title
.\.venv\Scripts\python.exe -m personal_ai.main desktop focus "Notepad"

# Capture desktop screenshot to artifacts
.\.venv\Scripts\python.exe -m personal_ai.main desktop screenshot

# Click at screen coordinates with boundary checks
.\.venv\Scripts\python.exe -m personal_ai.main desktop click 500 300

# Type text into active window
.\.venv\Scripts\python.exe -m personal_ai.main desktop type "Hello from Personal AI" --enter

# Press keyboard hotkey combination
.\.venv\Scripts\python.exe -m personal_ai.main desktop hotkey "ctrl+s"
```

### Webhook Server & n8n Workflow Automation
```powershell
# Start local authenticated webhook server (default: 127.0.0.1:8000)
.\.venv\Scripts\python.exe -m personal_ai.main server start

# Test sending an authenticated task to local webhook server
.\.venv\Scripts\python.exe -m personal_ai.main server test --prompt "take desktop screenshot"

# Start n8n locally via Docker Compose (local loopback only)
docker compose -f workflows/n8n/docker-compose.yml up -d
```
See the full [n8n Integration Guide](docs/n8n_integration.md) for architecture, networking, and workflow templates.

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
| **Phase 3** | **Browser Automation**: Playwright integration, semantic selectors, artifact capture | **COMPLETE** |
| **Phase 4** | **AI Providers**: Ollama & Cloud LLM adapters, structured output validation | **COMPLETE** |
| **Phase 5** | **Clipboard Memory**: Windows clipboard monitoring, content hashing, SQLite search | **COMPLETE** |
| **Phase 6** | **Desktop Control**: Constrained PyAutoGUI actions, screen verification | **COMPLETE** |
| **Phase 7** | **Workflow Automation**: Local n8n integration, authenticated webhooks | **COMPLETE** |
| **Phase 8** | **Dashboard**: Local task tracking, artifact viewer, approvals UI | **Next** |
| **Phase 9** | **Hardening & Recovery**: Security audit, backup/restore, resilience tests | Upcoming |



