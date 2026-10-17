"""Data repositories for tasks, steps, approvals, and clipboard."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from personal_ai.storage.database import Database, get_db


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskRepository:
    """Repository for managing task persistence and state transitions."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def create_task(
        self,
        task_id: str,
        prompt: str,
        status: str = "PENDING",
        plan_json: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new task record."""
        now = _utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tasks (id, prompt, status, plan_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, prompt, status, plan_json, now, now),
            )
        return self.get_task(task_id)  # type: ignore

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a task by ID."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def update_status(
        self,
        task_id: str,
        status: str,
        error_message: Optional[str] = None,
        result_summary: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update task status and completion details."""
        now = _utc_now_iso()
        completed_at = now if status in ("COMPLETED", "FAILED", "CANCELLED") else None

        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?,
                    error_message = COALESCE(?, error_message),
                    result_summary = COALESCE(?, result_summary),
                    updated_at = ?,
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (status, error_message, result_summary, now, completed_at, task_id),
            )
        return self.get_task(task_id)

    def update_plan(self, task_id: str, plan: Dict[str, Any] | str) -> Optional[Dict[str, Any]]:
        """Update task execution plan."""
        plan_str = plan if isinstance(plan, str) else json.dumps(plan)
        now = _utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET plan_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (plan_str, now, task_id),
            )
        return self.get_task(task_id)

    def list_tasks(self, limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List tasks ordered by created_at descending."""
        with self.db.connection() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]


class StepRepository:
    """Repository for managing task execution steps."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def create_step(
        self,
        step_id: str,
        task_id: str,
        step_number: int,
        tool_name: str,
        input_params: Optional[Dict[str, Any] | str] = None,
        risk_level: str = "low",
        requires_approval: bool = False,
    ) -> Dict[str, Any]:
        """Record an execution step."""
        now = _utc_now_iso()
        params_str = (
            input_params if isinstance(input_params, str)
            else json.dumps(input_params) if input_params is not None
            else None
        )

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO task_steps (
                    id, task_id, step_number, tool_name, input_params,
                    status, risk_level, requires_approval, started_at
                )
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
                """,
                (step_id, task_id, step_number, tool_name, params_str, risk_level, int(requires_approval), now),
            )
        return self.get_step(step_id)  # type: ignore

    def get_step(self, step_id: str) -> Optional[Dict[str, Any]]:
        """Fetch step by ID."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM task_steps WHERE id = ?", (step_id,)).fetchone()
            return dict(row) if row else None

    def update_step(
        self,
        step_id: str,
        status: str,
        output_result: Optional[str] = None,
        error_message: Optional[str] = None,
        approved: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update step execution result."""
        now = _utc_now_iso()
        completed_at = now if status in ("COMPLETED", "FAILED", "SKIPPED") else None

        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE task_steps
                SET status = ?,
                    output_result = COALESCE(?, output_result),
                    error_message = COALESCE(?, error_message),
                    approved = CASE WHEN ? IS NOT NULL THEN ? ELSE approved END,
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (
                    status,
                    output_result,
                    error_message,
                    1 if approved is not None else None,
                    1 if approved else 0,
                    completed_at,
                    step_id,
                ),
            )
        return self.get_step(step_id)

    def get_steps_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Fetch all steps for a given task sorted by step_number."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_number ASC",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_steps(self, task_id: str) -> List[Dict[str, Any]]:
        """Alias for get_steps_for_task."""
        return self.get_steps_for_task(task_id)


class ApprovalRepository:
    """Repository for human approval requests and decisions."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def create_approval(
        self,
        approval_id: str,
        task_id: str,
        step_id: Optional[str],
        action_description: str,
        risk_level: str,
    ) -> Dict[str, Any]:
        """Create a pending approval request."""
        now = _utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                    id, task_id, step_id, action_description, risk_level, status, requested_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (approval_id, task_id, step_id, action_description, risk_level, now),
            )
        return self.get_approval(approval_id)  # type: ignore

    def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve approval by ID."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            return dict(row) if row else None

    def resolve_approval(
        self,
        approval_id: str,
        status: str,  # 'approved' or 'rejected'
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve an approval request."""
        now = _utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, resolved_at = ?, resolution_reason = ?
                WHERE id = ?
                """,
                (status, now, reason, approval_id),
            )
        return self.get_approval(approval_id)

    def get_pending_approvals(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all pending approvals, optionally filtered by task."""
        with self.db.connection() as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE status = 'pending' AND task_id = ? ORDER BY requested_at ASC",
                    (task_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE status = 'pending' ORDER BY requested_at ASC"
                ).fetchall()
            return [dict(r) for r in rows]
    
    list_pending_approvals = get_pending_approvals


class ClipboardRepository:
    """Repository for clipboard history storage and search."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def save_entry(
        self,
        entry_id: str,
        content_hash: str,
        content_type: str,
        content_text: Optional[str],
        preview_path: Optional[str] = None,
        source_app: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save or update clipboard entry by content_hash."""
        now = _utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO clipboard_entries (
                    id, content_hash, content_type, content_text, preview_path, source_app, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_hash) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    source_app = COALESCE(excluded.source_app, clipboard_entries.source_app)
                """,
                (entry_id, content_hash, content_type, content_text, preview_path, source_app, now, now),
            )
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM clipboard_entries WHERE content_hash = ?", (content_hash,)).fetchone()
            return dict(row)

    def search_entries(
        self,
        query: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search clipboard history with optional query and content_type filters."""
        with self.db.connection() as conn:
            clauses = []
            params = []
            if query:
                clauses.append("content_text LIKE ?")
                params.append(f"%{query}%")
            if content_type:
                clauses.append("content_type = ?")
                params.append(content_type)

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)

            rows = conn.execute(
                f"SELECT * FROM clipboard_entries {where_sql} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_entry(self, entry_id: str) -> bool:
        """Delete entry by ID."""
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM clipboard_entries WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve clipboard entry by ID."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM clipboard_entries WHERE id = ?", (entry_id,)).fetchone()
            return dict(row) if row else None

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent clipboard entry."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM clipboard_entries ORDER BY updated_at DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def clear_all(self) -> int:
        """Clear all clipboard entries and return count of deleted items."""
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM clipboard_entries")
            return cursor.rowcount
