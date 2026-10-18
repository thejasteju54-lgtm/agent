# AGENTS.md — Developer and AI Agent Guidelines

## 1. Project Overview
MarketPulse AI is an India-first financial market research, intelligence, and automation runtime built for Windows desktop and cloud environments. It integrates with n8n for workflow automation, provides local Ollama and cloud LLM execution, maintains strict SQLite/PostgreSQL persistence, and operates under human-in-the-loop safety boundaries.

Personal AI Automation System provides foundational OS-level automation utilities (Playwright browser tools, Win32 clipboard memory, desktop interaction).

## 2. Port Allocation & Service Decoupling
To prevent local socket collisions, the services are strictly bound to isolated ports:
- **Port 8000**: Personal AI Webhook Server (`127.0.0.1:8000`)
- **Port 8001**: MarketPulse AI FastAPI Server & Web Dashboard (`127.0.0.1:8001`)
- **Port 5678**: Local n8n Workflow Automation Container (`127.0.0.1:5678`)

## 3. Directory Map
- `src/marketpulse/`: Core MarketPulse AI application package.
  - `config.py`: Central Pydantic settings loading from `.env`.
  - `cli.py`: Click CLI entry point (`marketpulse`).
  - `api/`: FastAPI application, endpoints (`/api/v1/*`), webhook routes (`/webhook/*`), dependencies.
  - `dashboard/`: Glassmorphic single-page web dashboard and static assets (`/static`).
  - `research/`: Market research collectors, normalizer, market brief, watchlist intelligence, model service.
  - `agent/`: Security guardrails, tool registry, task orchestrator, permissions.
  - `storage/`: Database connection, schema migrations (v1-v6), models, backup utility.
  - `n8n/`: HTTP client with Cloudflare Access and callback retry logic.
- `src/personal_ai/`: Base automation library (Win32 desktop, clipboard, browser).
- `workflows/n8n/`: Importable production n8n workflows (`MP-01`, `MP-02`, `MP-03`).
- `tests/`: Automated test suite (unit, integration, security, webhooks).
- `data/`: Local SQLite databases (`marketpulse.db`, `personal_ai.db`) and backups.
- `artifacts/`: Downloaded files, generated reports (`artifacts/reports/`), screenshots.
- `logs/`: Secret-redacting rotating application logs.

## 4. Master Engineering Rules
1. **Windows Native**: Always use `Path` from `pathlib` for file paths and cross-platform compatibility.
2. **Deterministic Operations**: Use deterministic parsers and normalization for financial figures, tickers, and dates. Zero fuzzy hallucination.
3. **Structured Persistence**: Never lose task or step states across process restarts. Every step status and result must be saved to SQLite/PostgreSQL.
4. **Safety & Risk Categorization**:
   - `LOW`: Public read-only queries, local draft saves, market brief generation.
   - `MEDIUM`: Modifying existing research files, accessing authenticated sites.
   - `HIGH`: Destructive disk commands, external publications (requires explicit human approval).
5. **Permanent Trading Prohibition**: Brokerage order placement, trading, and fund transfers are permanently prohibited (`ProhibitedActionError`).
6. **Absolute Non-Fabrication**: LLM text is never treated as verified financial truth without a corresponding `EvidenceRecord` row.
7. **No Blind Execution**: Never claim an action succeeded without verifying the target state.
8. **Tests First**: Any new feature or bug fix must include passing unit or integration tests.
