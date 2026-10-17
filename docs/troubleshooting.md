# Personal AI Automation System — Troubleshooting Guide

This guide covers diagnostic procedures, root causes, and verified solutions for common issues encountered when running the Personal AI Automation System on Windows.

---

## 1. Environment & Setup Issues

### Virtual Environment or Python Version Mismatch
- **Symptom**: `ImportError: cannot import name ...` or syntax errors on newer language features.
- **Root Cause**: The system requires Python 3.11 or newer.
- **Solution**:
  ```powershell
  # Verify active Python version
  .\.venv\Scripts\python.exe --version

  # Recreate virtual environment with Python 3.11+
  uv venv .venv --python 3.14
  uv pip install -e . --python .\.venv\Scripts\python.exe
  ```

### Missing `.env` File
- **Symptom**: Settings fallback to default or cloud models fail with `Missing API Key`.
- **Solution**:
  ```powershell
  Copy-Item .env.example .env
  # Edit .env and supply keys or custom configurations
  ```

---

## 2. Browser Automation (Playwright)

### Missing Chromium Binaries
- **Symptom**: `playwright._impl._errors.Error: Executable doesn't exist at ...\AppData\Local\ms-playwright\...`
- **Root Cause**: Playwright browser engines have not been downloaded.
- **Solution**:
  ```powershell
  .\.venv\Scripts\playwright.exe install chromium
  ```

### Browser Navigation Timeouts
- **Symptom**: `playwright._impl._errors.TimeoutError: Page.goto: Timeout 30000ms exceeded`.
- **Root Cause**: The target site is slow or offline, or `playwright_timeout_ms` is too restrictive.
- **Solution**:
  Increase timeout in `.env`:
  ```ini
  PLAYWRIGHT_TIMEOUT_MS=60000
  ```

---

## 3. Desktop Automation & Windows GUI

### `screen grab failed` or Desktop Screenshots Returning Black
- **Symptom**: `OSError: screen grab failed` when running desktop screenshot or click tools.
- **Root Cause**:
  1. The task is executing in a non-interactive Windows service or locked workstation session (`Winlogon`).
  2. Windows Session 0 isolation prevents background daemons from reading Session 1 user desktop DCs.
- **Solution**:
  1. Ensure the user workstation is unlocked with an active interactive desktop.
  2. The Personal AI runtime automatically invokes `user32.OpenInputDesktop(0, False, 0x01FF)` and `user32.SetThreadDesktop(hdesk)` to attach to the interactive desktop. Ensure the executing shell has normal desktop user privileges (do not run as `NT AUTHORITY\SYSTEM`).

### Out-of-Bounds Screen Coordinates
- **Symptom**: `ValueError: Coordinates (X, Y) are out of screen bounds`.
- **Root Cause**: Mouse click coordinates exceed the current display resolution (e.g., on multi-monitor setups or DPI scaling).
- **Solution**:
  Run display inspection to check resolution and virtual desktop geometry:
  ```powershell
  .\.venv\Scripts\python.exe -m personal_ai.main desktop screen
  ```

---

## 4. SQLite Database & Storage

### `sqlite3.OperationalError: database is locked`
- **Symptom**: Execution fails or hangs trying to acquire SQLite write lock.
- **Root Cause**: Another long-running process holds a transaction lock, or WAL mode is disabled.
- **Solution**:
  1. Verify WAL mode is active:
     ```powershell
     .\.venv\Scripts\python.exe -m personal_ai.main db init
     ```
  2. Run an online backup to test database accessibility and flush WAL pages:
     ```powershell
     .\.venv\Scripts\python.exe -m personal_ai.main db backup
     ```

### Corrupted Database or Abrupt Crash Recovery
- **Symptom**: `DatabaseError: file is not a database` or orphaned `RUNNING` tasks.
- **Solution**:
  1. Check for interrupted tasks and generate a conservative recovery report:
     ```powershell
     .\.venv\Scripts\python.exe -m personal_ai.main task recover
     ```
  2. Mark zombie tasks as failed:
     ```powershell
     .\.venv\Scripts\python.exe -m personal_ai.main task recover --mark-failed
     ```
  3. Restore from the most recent safe backup:
     ```powershell
     .\.venv\Scripts\python.exe -m personal_ai.main db backups
     .\.venv\Scripts\python.exe -m personal_ai.main db restore data/backups/personal_ai_backup_<TIMESTAMP>.db
     ```

### Missing or Desynchronized Artifact Files
- **Symptom**: Tasks record generated artifacts in SQLite, but files cannot be found on disk.
- **Solution**:
  Run the automated artifact integrity verifier:
  ```powershell
  .\.venv\Scripts\python.exe -m personal_ai.main db verify-artifacts
  ```

---

## 5. Webhook Server & Dashboard Port Conflicts

### Port `8000` or `5678` Already in Use
- **Symptom**: `[WinError 10048] Only one usage of each socket address (protocol/network address/port) is normally permitted`.
- **Root Cause**: Another instance of the server, uvicorn, or Docker container is bound to the port.
- **Solution**:
  1. Find and terminate conflicting process:
     ```powershell
     netstat -ano | findstr :8000
     Stop-Process -Id <PID> -Force
     ```
  2. Or launch the Personal AI server/dashboard on an alternate port:
     ```powershell
     .\.venv\Scripts\python.exe -m personal_ai.main dashboard --port 8088
     ```

### Client Disconnection `[WinError 10053]`
- **Symptom**: `An established connection was aborted by the software in your host machine`.
- **Root Cause**: On Windows TCP sockets, sending an HTTP error response before reading all pending request payload bytes triggers a TCP RST reset.
- **Solution**:
  The built-in webhook server drains all incoming stream bytes via `rfile.read(content_length)` prior to responding. Ensure client requests specify accurate `Content-Length` headers.

---

## 6. AI Model Providers

### Local Ollama Unreachable
- **Symptom**: `ProviderUnavailableError: Ollama service is not reachable at http://localhost:11434`.
- **Root Cause**: The Ollama service is not running or the model is not pulled.
- **Solution**:
  1. Verify Ollama is running:
     ```powershell
     curl http://localhost:11434/api/tags
     ```
  2. Pull the configured model:
     ```powershell
     ollama pull llama3.2
     ```
  3. Test provider diagnostics:
     ```powershell
     .\.venv\Scripts\python.exe -m personal_ai.main model status
     ```

---

## 7. Emergency Stop & Task Cancellation

### All Tasks Aborting Immediately
- **Symptom**: Any submitted task fails with `Execution blocked by Emergency Stop`.
- **Root Cause**: The global emergency stop flag was activated (file `data/.emergency_stop` exists).
- **Solution**:
  Inspect and clear the emergency stop flag:
  ```powershell
  .\.venv\Scripts\python.exe -m personal_ai.main reset-stop
  ```
