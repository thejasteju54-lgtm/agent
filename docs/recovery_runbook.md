# MarketPulse AI — Disaster Recovery & Operational Runbook

## 1. Overview
This runbook defines standard operating procedures (SOPs) for diagnosing, recovering, and restoring MarketPulse AI across Windows Desktop and Cloud environments.

---

## 2. Emergency Stop Activation & Reset

### Triggering Emergency Stop
If an anomalous task loop, runaway process, or unauthorized execution is detected:

```powershell
# Windows Desktop CLI
.\.venv\Scripts\marketpulse.exe emergency-stop --reason "Operational panic stop"

# Web Dashboard
# Click the red "⛔ EMERGENCY STOP" button in the top navigation bar.

# Docker / Cloud
docker compose -f docker-compose.cloud.yml exec marketpulse-api marketpulse emergency-stop --reason "Cloud incident"
```

**System Behavior**:
- All subsequent task steps halt immediately with `EmergencyStopActiveError`.
- Running tasks transition to `CANCELLED`.
- A persistent `.emergency_stop` flag file is created in `data/`.
- An audit event `TASK_EMERGENCY_STOPPED` is recorded in `mp_audit_events`.

### Clearing Emergency Stop
Once the root cause is resolved:
```powershell
.\.venv\Scripts\marketpulse.exe reset-stop
```
The runtime resumes normal operations immediately.

---

## 3. Ungraceful Crash & Interrupted Task Recovery

If the host machine reboots or the container is terminated (`SIGKILL`) while tasks are running:

1. **Automatic Startup Recovery**:
   - The FastAPI `lifespan` handler automatically invokes `recover_interrupted_tasks(session)`.
   - Any task left in `RUNNING`, `PLANNING`, or `VERIFYING` state is safely marked `FAILED`.
   - The task's `cancellation_reason` is updated to: `"Process interrupted prior to completion; state preserved in database."`
   - An audit record with event type `TASK_RECOVERED` is created.

2. **Manual Inspection via CLI**:
```powershell
# List recent tasks and inspect status
.\.venv\Scripts\marketpulse.exe task list

# Inspect detailed failure state of a task
.\.venv\Scripts\marketpulse.exe task show <TASK_ID>
```

---

## 4. Database Disaster Recovery (SQLite & PostgreSQL)

### Restoring from a Snapshot (SQLite)
```powershell
# 1. List available verified backups
.\.venv\Scripts\marketpulse.exe backup list

# 2. Restore from a chosen backup file
.\.venv\Scripts\marketpulse.exe backup restore data/backups/marketpulse_backup_YYYYMMDD_HHMMSS.db
```
The manager will:
1. Verify the SQLite file signature and SHA-256 checksum against metadata.
2. Create an automated pre-restore safety copy (`safety_pre_restore_...db`).
3. Replace the active database file atomically.
4. Verify schema version compatibility and record a `DATABASE_RESTORED` audit event.

### Creating an Immediate Backup
```powershell
.\.venv\Scripts\marketpulse.exe backup create --label "pre_maintenance"
```

---

## 5. n8n Connection & Webhook Recovery

If n8n is reported as `DISCONNECTED` or webhooks fail:

1. **Check Local n8n Container**:
```powershell
docker ps --filter "name=n8n"
```
If offline, start the container:
```powershell
docker compose -f docker-compose.cloud.yml up -d n8n
```

2. **Check Port & Network Connectivity**:
- Personal AI API: Port `8000`
- MarketPulse API: Port `8001`
- n8n Webhook Server: Port `5678`
Ensure no port collision exists (`netstat -ano | findstr 8001`).

3. **Verify Webhook Callback Delivery**:
MarketPulse employs exponential backoff (retries: 3) for outgoing webhook callbacks. Check `logs/marketpulse.log` for HTTP delivery status codes.

---

## 6. Prompt Injection & Security Violations

If external market disclosures or untrusted sources contain prompt injections (e.g., attempts to override policies, delete root drives, or execute financial orders):

1. **Automatic Defense**:
   - `MarketPulseSecurityGuard` flags the content via `scan_untrusted_financial_content`.
   - Prohibited trading tools raise `ProhibitedActionError`.
   - High-risk actions halt at `AWAITING_APPROVAL`.
2. **Review Security Events**:
```powershell
# Query audit trail for security violations
# In Web Dashboard: Go to "System & Audit" tab.
```
