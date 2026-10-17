# AGENTS.md — Developer and AI Agent Guidelines

## 1. Project Overview
The Personal AI Automation System is a modular, dependable automation runtime built for Windows. It provides natural language task decomposition, automated execution, browser/desktop control, persistent history in SQLite, clipboard memory, and human-in-the-loop approval workflows.

## 2. Directory Map
- `src/personal_ai/`: Core application package.
  - `config.py`: Pydantic settings loading from `.env` and environment variables.
  - `cli.py`: Click-based CLI entry points.
  - `storage/`: Database connection, schema migrations, repositories, and artifact handling.
  - `logging/`: Structured console and rotating file logging.
  - `agent/`: Planner, executor, task models, permissions, and verification (Phase 2).
  - `tools/`: Tool registry and tool implementations (Phase 2 & 3).
  - `models/`: Provider-agnostic LLM client adapters (Phase 4).
- `tests/`: Automated test suite (unit, integration, browser, security).
- `data/`: Local SQLite databases and persistent state (git-ignored).
- `artifacts/`: Downloaded files, generated reports, diagnostic screenshots (git-ignored).
- `logs/`: Rotating application log files (git-ignored).

## 3. Engineering Rules
1. **Windows Native**: Always use `Path` from `pathlib` for file paths and cross-platform compatibility.
2. **Deterministic Operations**: Use Python standard library and deterministic functions for operations that do not require fuzzy semantic reasoning.
3. **Structured Persistence**: Never lose task or step states across process restarts. Every step status and result must be saved to SQLite.
4. **Safety & Risk Categorization**:
   - `LOW`: Public read-only queries, local draft saves.
   - `MEDIUM`: Modifying existing files, changing settings.
   - `HIGH`: Destructive disk/database commands, sending messages, external irreversible actions (requires human approval).
5. **No Blind Execution**: Never claim an action succeeded without verifying the target state.
6. **Tests First**: Any new feature or bug fix must include passing unit or integration tests.
