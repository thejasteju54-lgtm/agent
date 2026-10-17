"""Command Line Interface for Personal AI Automation System."""

import json
import sys
import click
from personal_ai import __version__
from personal_ai.config import settings
from personal_ai.logging.setup import setup_logging, get_logger
from personal_ai.storage.database import get_db
from personal_ai.storage.repositories import TaskRepository, StepRepository, ApprovalRepository
from personal_ai.agent.planner import TaskPlanner
from personal_ai.agent.executor import TaskExecutor
from personal_ai.agent.task_models import PlanStep, TaskStatus

logger = get_logger(__name__)


@click.group()
@click.version_option(version=__version__, prog_name="personal-ai")
@click.option("--debug", is_flag=True, help="Enable verbose debug logging.")
def cli(debug: bool) -> None:
    """Personal AI Automation System CLI."""
    log_level = "DEBUG" if debug else settings.log_level
    setup_logging(log_level=log_level)


@cli.command("init-db")
def init_db_cmd() -> None:
    """Initialize database tables and run pending migrations."""
    click.echo(f"Initializing database at: {settings.database_path}...")
    db = get_db()
    db.initialize_schema()
    click.echo("Database initialization complete.")


@cli.command("status")
def status_cmd() -> None:
    """Check system health, configuration, and database connection."""
    click.echo(f"=== Personal AI Automation System v{__version__} ===")
    click.echo(f"Environment:       {settings.environment}")
    click.echo(f"Project Root:      {settings.project_root}")
    click.echo(f"Database Path:     {settings.database_path}")
    click.echo(f"Artifacts Dir:     {settings.artifacts_dir}")
    click.echo(f"Logs Dir:          {settings.log_dir}")
    click.echo(f"Approval Mode:     {settings.approval_mode}")
    click.echo(f"AI Provider:       {settings.default_provider} (Model: {settings.ollama_model})")

    # Check database
    db_exists = settings.database_path.exists()
    click.echo(f"\nDatabase File Exists: {db_exists}")
    if db_exists:
        try:
            db = get_db()
            with db.connection() as conn:
                task_count = conn.execute("SELECT COUNT(*) as cnt FROM tasks").fetchone()["cnt"]
                step_count = conn.execute("SELECT COUNT(*) as cnt FROM task_steps").fetchone()["cnt"]
                approval_count = conn.execute("SELECT COUNT(*) as cnt FROM approvals WHERE status = 'pending'").fetchone()["cnt"]
                artifact_count = conn.execute("SELECT COUNT(*) as cnt FROM artifacts").fetchone()["cnt"]
                click.echo(f"Tasks in DB:        {task_count}")
                click.echo(f"Steps Recorded:     {step_count}")
                click.echo(f"Pending Approvals:  {approval_count}")
                click.echo(f"Artifacts Stored:   {artifact_count}")
        except Exception as e:
            click.echo(f"Database error: {e}", err=True)
    else:
        click.echo("Run 'personal-ai init-db' to create and initialize the database.")


@cli.command("run")
@click.argument("task_prompt")
@click.option("-y", "--yes", is_flag=True, help="Auto-approve medium and high risk actions.")
@click.option("--dry-run", is_flag=True, help="Generate plan only without executing steps.")
@click.option("--ai", is_flag=True, help="Use configured AI model for intelligent task planning.")
def run_task_cmd(task_prompt: str, yes: bool, dry_run: bool, ai: bool) -> None:
    """Plan and execute a natural-language automation task."""
    click.echo(f"\n[Personal AI] Planning task: '{task_prompt}'")
    from personal_ai.models import get_provider

    provider = get_provider() if ai else None
    planner = TaskPlanner(model_provider=provider)
    plan = planner.plan(task_prompt, use_ai=ai)

    if plan.requires_clarification:
        click.echo(f"\n[Clarification Required]: {plan.clarification_question}", err=True)
        sys.exit(1)

    if plan.assumptions:
        click.echo("\nAssumptions:")
        for a in plan.assumptions:
            click.echo(f"  * {a}")

    click.echo(f"\nGenerated Execution Plan ({len(plan.steps)} steps):")
    for s in plan.steps:
        approval_flag = " [REQUIRES APPROVAL]" if s.requires_approval else ""
        click.echo(f"  {s.step_number}. [{s.tool_name}] (Risk: {s.risk_level.value}){approval_flag}: {s.description}")

    if dry_run:
        click.echo("\n[Dry Run] Plan generated. Skipping execution.")
        return

    def cli_approval_callback(step: PlanStep) -> bool:
        click.echo(f"\n[APPROVAL REQUIRED] Step {step.step_number} ({step.risk_level.value.upper()} RISK):")
        click.echo(f"  Action: {step.description}")
        click.echo(f"  Params: {step.input_params}")
        return click.confirm("Do you approve this action?", default=False)

    click.echo("\nStarting Execution...")
    executor = TaskExecutor()
    report = executor.execute(
        plan=plan,
        auto_approve=yes,
        approval_callback=cli_approval_callback,
    )

    click.echo("\n" + "=" * 60)
    click.echo(f"Task Status:    {report.status.value}")
    click.echo(f"Summary:        {report.summary}")
    click.echo(f"Steps:          {report.steps_completed}/{report.steps_total} completed")
    if report.artifacts:
        click.echo(f"Artifacts:      {len(report.artifacts)} generated")
    if report.error_message:
        click.echo(f"Error:          {report.error_message}", err=True)
        sys.exit(1)


@cli.group("model")
def model_group() -> None:
    """Inspect and test AI model providers."""
    pass


@model_group.command("status")
def model_status_cmd() -> None:
    """Check connectivity and status for configured AI providers."""
    from personal_ai.models import OllamaProvider, CloudProvider

    click.echo("=== AI Model Providers Health Check ===")
    click.echo(f"Default Provider: {settings.default_provider}")

    # 1. Ollama
    ollama = OllamaProvider()
    o_health = ollama.health_check()
    o_icon = "[ONLINE]" if o_health.available else "[OFFLINE]"
    click.echo(f"\n* Ollama ({settings.ollama_base_url}) - Model: {settings.ollama_model} {o_icon}")
    click.echo(f"  Details: {o_health.details}")

    # 2. Cloud
    cloud = CloudProvider()
    c_health = cloud.health_check()
    c_icon = "[ONLINE]" if c_health.available else "[OFFLINE]"
    click.echo(f"\n* Cloud Provider ({cloud.base_url}) - Model: {cloud.model_name} {c_icon}")
    click.echo(f"  Details: {c_health.details}")


@model_group.command("test")
@click.argument("prompt", default="Explain the word 'automation' in one sentence.")
@click.option("--provider", default=None, help="Provider to test: 'ollama', 'cloud', or 'mock'.")
def model_test_cmd(prompt: str, provider: Optional[str]) -> None:
    """Test text generation with an AI provider."""
    from personal_ai.models import get_provider

    prov_type = provider or settings.default_provider
    click.echo(f"Testing generation with provider '{prov_type}'...")
    try:
        p = get_provider(prov_type)
        resp = p.generate(prompt=prompt)
        click.echo(f"\nResponse from {resp.model_name}:")
        click.echo(resp.text)
    except Exception as e:
        click.echo(f"Generation error: {e}", err=True)
        sys.exit(1)


@cli.group("task")
def task_group() -> None:
    """Manage and inspect automated tasks."""
    pass


@task_group.command("list")
@click.option("--limit", default=20, help="Maximum number of tasks to return.")
@click.option("--status", default=None, help="Filter by status (e.g. COMPLETED, FAILED, RUNNING).")
def list_tasks_cmd(limit: int, status: str | None) -> None:
    """List recent automation tasks."""
    repo = TaskRepository()
    tasks = repo.list_tasks(limit=limit, status=status)
    if not tasks:
        click.echo("No tasks found.")
        return

    click.echo(f"{'ID':<36} | {'STATUS':<12} | {'CREATED':<20} | PROMPT")
    click.echo("-" * 100)
    for t in tasks:
        prompt_snippet = (t["prompt"][:45] + "...") if len(t["prompt"]) > 45 else t["prompt"]
        click.echo(f"{t['id']:<36} | {t['status']:<12} | {t['created_at'][:19]:<20} | {prompt_snippet}")


@task_group.command("show")
@click.argument("task_id")
def show_task_cmd(task_id: str) -> None:
    """Display detailed execution information for a task."""
    task_repo = TaskRepository()
    step_repo = StepRepository()
    approval_repo = ApprovalRepository()

    task = task_repo.get_task(task_id)
    if not task:
        click.echo(f"Task with ID '{task_id}' not found.", err=True)
        sys.exit(1)

    click.echo(f"Task ID:         {task['id']}")
    click.echo(f"Status:          {task['status']}")
    click.echo(f"Created:         {task['created_at']}")
    click.echo(f"Completed:       {task.get('completed_at') or 'N/A'}")
    click.echo(f"Prompt:          {task['prompt']}")
    if task.get("result_summary"):
        click.echo(f"Summary:         {task['result_summary']}")
    if task.get("error_message"):
        click.echo(f"Error:           {task['error_message']}")

    if task.get("plan_json"):
        click.echo("\nExecution Plan:")
        try:
            parsed = json.loads(task["plan_json"])
            click.echo(json.dumps(parsed, indent=2))
        except Exception:
            click.echo(task["plan_json"])

    steps = step_repo.get_steps_for_task(task_id)
    if steps:
        click.echo("\nExecution Steps:")
        for s in steps:
            click.echo(
                f"  [{s['step_number']}] Tool: {s['tool_name']} | Status: {s['status']} | Risk: {s['risk_level']}"
            )
            if s.get("input_params"):
                click.echo(f"      Input: {s['input_params']}")
            if s.get("output_result"):
                click.echo(f"      Output: {s['output_result']}")
            if s.get("error_message"):
                click.echo(f"      Error: {s['error_message']}")

    approvals = approval_repo.get_pending_approvals(task_id)
    if approvals:
        click.echo("\nPending Approvals:")
        for a in approvals:
            click.echo(f"  Approval ID: {a['id']} | Action: {a['action_description']} | Risk: {a['risk_level']}")


@task_group.command("cancel")
@click.argument("task_id")
def cancel_task_cmd(task_id: str) -> None:
    """Cancel a pending or running task."""
    task_repo = TaskRepository()
    task = task_repo.get_task(task_id)
    if not task:
        click.echo(f"Task '{task_id}' not found.", err=True)
        sys.exit(1)

    if task["status"] in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
        click.echo(f"Task is already {task['status']}. Cannot cancel.")
        return

    task_repo.update_status(task_id, TaskStatus.CANCELLED.value, result_summary="Cancelled via CLI")
    click.echo(f"Task '{task_id}' marked as CANCELLED.")


@task_group.command("approve")
@click.argument("approval_id")
@click.option("--reason", default="Approved via CLI", help="Approval notes or justification.")
def approve_cmd(approval_id: str, reason: str) -> None:
    """Approve a pending high-risk action."""
    approval_repo = ApprovalRepository()
    approval = approval_repo.get_approval(approval_id)
    if not approval:
        click.echo(f"Approval request '{approval_id}' not found.", err=True)
        sys.exit(1)

    if approval["status"] != "pending":
        click.echo(f"Approval request is already {approval['status']}.")
        return

    approval_repo.resolve_approval(approval_id, "approved", reason)
    click.echo(f"Approval '{approval_id}' granted.")


def main() -> None:
    """CLI entrypoint."""
    cli()


if __name__ == "__main__":
    main()
