# MarketPulse AI — Version-Controlled n8n Workflows Specification

This document details the architecture, input/output schemas, credentials, error handling, and manual activation protocols for the five core automation workflows powering MarketPulse AI.

---

## 1. Architecture Overview

MarketPulse AI utilizes n8n for scheduled ingestion, event-driven processing, watchlist alerts, and automated system health monitoring. All workflows operate against the authenticated MarketPulse AI backend (FastAPI) running locally at `http://localhost:8000` or in a production container network.

### Security & Invariant Rules
1. **Never Assume Trading Authority**: Workflows produce research briefings, digest updates, and audit notifications. They **never execute market orders**.
2. **Correlation Tracking**: Every execution generates or propagates a unique UUID `correlation_id` across all HTTP payloads and audit records.
3. **Idempotency & Deduplication**: All ingested articles and alert triggers are hashed (`SHA-256`) and checked before persistence to prevent re-alerting.
4. **Credential Isolation**: No plain-text API keys or tokens are stored in workflow definitions. In development, headers use `X-API-Key: {{ $env.N8N_WEBHOOK_SECRET || 'dev-secret-key' }}`.

---

## 2. Workflow Specifications

### MP-01: Daily Market Brief
- **File**: `workflows/n8n/MP-01-daily-market-brief.json`
- **Trigger**: Cron Schedule — Every weekday at 08:30 IST (`30 8 * * 1-5`).
- **Purpose**: Generates an opening bell intelligence summary covering major Indian market indices, pre-market updates, regulatory notices, and active watchlist alerts.

#### Input Schema
```json
{
  "correlation_id": "uuid-string (auto-generated if null)",
  "timestamp": "ISO-8601 UTC string"
}
```

#### Output Schema
```json
{
  "status": "COMPLETED | FAILED",
  "correlation_id": "string",
  "generated_at": "ISO-8601 UTC string",
  "summary": "string",
  "report_id": "string (optional)",
  "error": "string (null on success)"
}
```

#### Operations Flow
1. **Trigger**: Cron at 08:30 IST.
2. **Setup Context**: Formats timestamp and injects correlation ID.
3. **Fetch Active Watchlist**: `GET /api/v1/watchlists` to retrieve tracked tickers.
4. **Trigger Research Pipeline**: `POST /api/v1/research/jobs` with type `daily_brief`.
5. **Publish / Notify**: Logs dispatch status or notifies research Slack/Discord webhook.

---

### MP-02: News Intelligence Ingestion
- **File**: `workflows/n8n/MP-02-news-intelligence.json`
- **Trigger**: Cron Schedule — Every 15 minutes (`*/15 * * * *`).
- **Purpose**: Polling permitted RSS and regulatory disclosure feeds (BSE/NSE announcements, licensed feeds), normalizing article metadata, and deduplicating content.

#### Input Schema
```json
{
  "source_urls": ["array of permitted RSS/feed URLs"],
  "poll_interval_minutes": 15
}
```

#### Output Schema
```json
{
  "status": "COMPLETED",
  "articles_ingested": "number",
  "duplicates_skipped": "number",
  "correlation_id": "string",
  "timestamp": "ISO-8601 UTC"
}
```

#### Operations Flow
1. **Cron Trigger**: 15-minute interval.
2. **Fetch Feed Registry**: `GET /api/v1/sources/active`.
3. **Poll Permitted Feeds**: Iterates over approved RSS feeds with HTTP request timeout (10s).
4. **Send to Backend Normalizer**: `POST /api/v1/articles/ingest` (runs SHA-256 fingerprinting and DB deduplication).
5. **Audit Ingest**: Records item counts in database audit log.

---

### MP-03: On-Demand Research
- **File**: `workflows/n8n/MP-03-on-demand-research.json`
- **Trigger**: Webhook `POST /webhook/marketpulse-research`.
- **Purpose**: Accepts ad-hoc ticker/sector research queries from user or dashboard, dispatches 7-agent pipeline asynchronously, and returns job confirmation.

#### Input Schema
```json
{
  "query": "string (e.g. 'Analyze impact of recent capex on RELIANCE')",
  "ticker": "string (e.g. 'RELIANCE.NS')",
  "sector": "string (optional)",
  "correlation_id": "string"
}
```

#### Output Schema
```json
{
  "job_id": "string (UUID)",
  "status": "QUEUED | IN_PROGRESS | COMPLETED",
  "correlation_id": "string",
  "estimated_completion_seconds": 30
}
```

#### Operations Flow
1. **Webhook Inbound**: Validates incoming payload and auth token header.
2. **Backend Submission**: `POST /api/v1/research/jobs` with Pydantic payload.
3. **Poll / Wait**: Bounded check of execution status (up to 45s).
4. **Webhook Response**: Returns structured report summary and persistence ID.

---

### MP-04: Watchlist Alerts
- **File**: `workflows/n8n/MP-04-watchlist-alerts.json`
- **Trigger**: Webhook `POST /webhook/marketpulse-alerts` or Cron (Every 10 min during trading hours).
- **Purpose**: Evaluates price/news volatility alerts against user-defined alert rules, deduplicating alerts within a 4-hour cooldown window.

#### Input Schema
```json
{
  "watchlist_id": "string (UUID)",
  "alert_type": "PRICE_MOVEMENT | MATERIAL_NEWS | DISCLOSURE",
  "trigger_timestamp": "ISO-8601 UTC"
}
```

#### Output Schema
```json
{
  "alerts_evaluated": "number",
  "alerts_dispatched": "number",
  "suppressed_by_cooldown": "number",
  "correlation_id": "string"
}
```

---

### MP-05: Health and Failure Recovery
- **File**: `workflows/n8n/MP-05-health-recovery.json`
- **Trigger**: Cron Schedule — Every 5 minutes (`*/5 * * * *`).
- **Purpose**: Continuously monitors backend API health (`GET /api/v1/health`), database connection, and queue backlog. Triggers alerting if unreachable for 2 consecutive cycles.

#### Input Schema
```json
{
  "health_check_url": "http://localhost:8000/api/v1/health",
  "max_failures_before_alert": 2
}
```

#### Output Schema
```json
{
  "system_status": "HEALTHY | DEGRADED | UNREACHABLE",
  "database": "CONNECTED | DISCONNECTED",
  "checked_at": "ISO-8601 UTC",
  "latency_ms": "number"
}
```

---

## 3. Activation Instructions

To activate workflows on an n8n instance:

1. **Ensure n8n is running**:
   - Docker: `docker run -it --rm --name n8n -p 5678:5678 -e N8N_DEFAULT_BINARY_DATA_MODE=filesystem n8nio/n8n`
   - Or via desktop n8n app / hosted service.
2. **Import via API**:
   Use the MarketPulse CLI or Python client:
   ```bash
   python -m marketpulse.cli workflows import --path workflows/n8n/MP-01-daily-market-brief.json
   ```
3. **Manual Import via n8n UI**:
   - Log into n8n (`http://localhost:5678`).
   - Navigate to **Workflows** -> **Import from File**.
   - Select the desired `MP-*.json` file.
   - Click **Save** and toggle the workflow switch to **Active**.
4. **Webhook URL Verification**:
   - For webhook-triggered workflows (MP-03, MP-04), copy the generated Webhook URL from the Webhook node into `.env` as `N8N_RESEARCH_WEBHOOK_URL` and `N8N_ALERT_WEBHOOK_URL`.
