# MarketPulse AI — Cloud Deployment & Operations Guide

## 1. Overview & Architectural Boundaries

MarketPulse AI is designed with an explicit dual-mode runtime architecture:
1. **Desktop Mode (`OPERATING_MODE=desktop`)**:
   - Designed for local execution on Windows workstations.
   - Leverages local SQLite (`WAL` mode), local Ollama models, and optional local desktop inspection tools (`desktop_screenshot`, `desktop_active_window`).
2. **Cloud Mode (`OPERATING_MODE=cloud`)**:
   - Designed for 24/7 cloud container environments (Docker, AWS ECS, GCP Cloud Run, Kubernetes, or VPS).
   - Relies on PostgreSQL for scalable relational persistence.
   - Enforces strict security boundaries: local Windows GUI automation (`desktop_screenshot`, `desktop_active_window`) is blocked via `OperatingModeError`.
   - Uses provider-independent Cloud LLM adapters (OpenAI-compatible, Anthropic, or remote Ollama instances).

> **Important**: Never attempt to share a single SQLite database file across separate distributed cloud and desktop nodes. SQLite is strictly node-local. Use PostgreSQL for cloud persistence.

---

## 2. Environment Variables & Secret Configuration

Configure production secrets using environment variables or a secret management service (e.g. AWS Secrets Manager, HashiCorp Vault, Doppler):

| Environment Variable | Mode / Scope | Description | Default / Example |
| :--- | :--- | :--- | :--- |
| `OPERATING_MODE` | Global | Controls environment mode (`desktop` or `cloud`) | `cloud` |
| `ENVIRONMENT` | Global | Deployment stage (`production`, `development`) | `production` |
| `DATABASE_URL` | Cloud | PostgreSQL connection string | `postgresql://marketpulse:pass@postgres:5432/marketpulse` |
| `API_HOST` | API | Interface to bind HTTP server | `0.0.0.0` |
| `API_PORT` | API | Port to bind HTTP server | `8001` |
| `API_SECRET_KEY` | Security | Bearer token for MarketPulse REST API | Set a strong random token (32+ chars) |
| `DEFAULT_MODEL_PROVIDER` | AI | Primary LLM inference provider (`cloud` or `ollama`) | `cloud` |
| `CLOUD_API_KEY` | AI | API key for cloud inference engine | `sk-...` |
| `CLOUD_API_BASE` | AI | Base endpoint URL for cloud models | `https://api.openai.com/v1` |
| `CLOUD_MODEL` | AI | Model identifier | `gpt-4o-mini` |
| `N8N_ENABLED` | n8n | Toggle n8n workflow integration | `true` |
| `N8N_BASE_URL` | n8n | Base URL of n8n instance | `http://n8n:5678` |
| `N8N_WEBHOOK_URL` | n8n | Target webhook URL for n8n workflow triggers | `http://n8n:5678/webhook` |
| `N8N_WEBHOOK_SECRET` | n8n | Shared secret for incoming n8n webhook authentication | Strong random string |
| `CF_ACCESS_CLIENT_ID` | Security | Cloudflare Access service token client ID | Optional |
| `CF_ACCESS_CLIENT_SECRET` | Security | Cloudflare Access service token secret | Optional |

---

## 3. Container Deployment (Docker Compose)

The repository provides a production-grade multi-stage `Dockerfile` and `docker-compose.cloud.yml` orchestrating MarketPulse API, PostgreSQL 16, and self-hosted n8n.

### Step 1: Create Production `.env`
```bash
cp .env.example .env.production
# Edit .env.production with production database passwords and API tokens
```

### Step 2: Build & Start Services
```bash
docker compose -f docker-compose.cloud.yml --env-file .env.production up -d --build
```

### Step 3: Verify Container Health
```bash
# Check service status
docker compose -f docker-compose.cloud.yml ps

# Inspect API health probe
curl -i http://localhost:8001/health

# Inspect API readiness probe (verifies database connectivity)
curl -i http://localhost:8001/ready
```

---

## 4. Database Migrations & Seeding

The database layer automatically runs versioned migrations on startup via `init_db()` and `apply_migrations()`. 

To manually initialize or inspect the cloud database:
```bash
# Execute CLI inside the running container
docker compose -f docker-compose.cloud.yml exec marketpulse-api marketpulse init-db

# Check schema version and registered sources
docker compose -f docker-compose.cloud.yml exec marketpulse-api marketpulse status
```

---

## 5. Reverse Proxy & Cloudflare Tunnel Setup

When exposing the MarketPulse API to n8n Cloud or external webhook sources, keep the container bound to `127.0.0.1` and route traffic through a zero-trust tunnel.

### Cloudflare Tunnel Configuration (`config.yml`):
```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: marketpulse.yourdomain.com
    service: http://localhost:8001
    originRequest:
      noTLSVerify: false
  - service: http_status:404
```

### Cloudflare Access Service Token:
1. In Cloudflare Zero Trust Dashboard, navigate to **Access** -> **Service Auth**.
2. Generate a Service Token (`CF-Access-Client-Id` and `CF-Access-Client-Secret`).
3. Add an Access Policy for `marketpulse.yourdomain.com` requiring the Service Token.
4. Supply the client ID and secret in your n8n workflow HTTP Request nodes and MarketPulse `.env`.

---

## 6. Emergency Stop & Operational Recovery

If an erroneous workflow or external anomaly triggers unexpected actions, activate the global emergency stop:

```bash
# CLI command to immediately halt all active automation tasks
docker compose -f docker-compose.cloud.yml exec marketpulse-api marketpulse emergency-stop --reason "Investigating abnormal task volume"

# Reset once cleared
docker compose -f docker-compose.cloud.yml exec marketpulse-api marketpulse reset-stop
```

All incoming task execution requests will immediately fail-fast with `EmergencyStopActiveError` and record an `EMERGENCY_STOP_ACTIVATED` audit log event.
