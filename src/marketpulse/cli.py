"""Command Line Interface for MarketPulse AI platform."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Optional
import click
import uvicorn

from marketpulse import __version__
from marketpulse.config import mp_settings
from marketpulse.logging.setup import get_logger, setup_logging
from marketpulse.storage.artifacts import MarketPulseArtifactStore
from marketpulse.storage.database import get_engine, get_session, init_db, seed_initial_registry
from marketpulse.storage.migrations import apply_migrations, get_current_schema_version
from marketpulse.storage.models import (
    ArtifactRecord,
    AutomationTask,
    Company,
    ResearchJob,
    ResearchReport,
    SourceRegistry,
    TaskStatus,
)

logger = get_logger(__name__)


@click.group()
@click.version_option(version=__version__, prog_name="marketpulse")
@click.option("--debug", is_flag=True, help="Enable verbose debug logging.")
def cli(debug: bool) -> None:
    """MarketPulse AI — Indian Financial-Market Intelligence Platform."""
    log_level = "DEBUG" if debug else mp_settings.log_level
    setup_logging(log_level=log_level)


@cli.command("init-db")
def init_db_cmd() -> None:
    """Initialize MarketPulse database tables, migrations, and seed data."""
    click.echo(f"Initializing MarketPulse database at: {mp_settings.database_url}...")
    init_db()
    with get_session() as session:
        seed_initial_registry(session)
    engine = get_engine()
    ver = get_current_schema_version(engine)
    click.echo(f"Database initialization complete. Current schema version: {ver}")


@cli.command("status")
def status_cmd() -> None:
    """Inspect system health, configuration, storage, and database records."""
    click.echo(f"=== MarketPulse AI Platform v{__version__} ===")
    click.echo(f"Environment:       {mp_settings.environment}")
    click.echo(f"Operating Mode:    {mp_settings.operating_mode}")
    click.echo(f"Project Root:      {mp_settings.project_root}")
    click.echo(f"Database URL:      {mp_settings.database_url}")
    click.echo(f"Artifacts Dir:     {mp_settings.artifacts_dir}")
    click.echo(f"Logs Dir:          {mp_settings.log_dir}")
    click.echo(f"API Server:        http://{mp_settings.api_host}:{mp_settings.api_port}")
    click.echo(f"n8n Base URL:      {mp_settings.n8n_base_url}")
    click.echo(f"n8n API Key:       {'Configured' if mp_settings.n8n_api_key else 'Not Configured (Optional for local)'}")
    click.echo(f"AI Provider:       {mp_settings.default_model_provider} (Model: {mp_settings.ollama_model})")

    engine = get_engine()
    try:
        ver = get_current_schema_version(engine)
        click.echo(f"\nDatabase Connection: CONNECTED (Schema v{ver})")
        with get_session() as session:
            tasks_count = session.query(AutomationTask).count()
            jobs_count = session.query(ResearchJob).count()
            reports_count = session.query(ResearchReport).count()
            artifacts_count = session.query(ArtifactRecord).count()
            companies_count = session.query(Company).count()
            sources_count = session.query(SourceRegistry).count()

            click.echo(f"Automation Tasks:  {tasks_count}")
            click.echo(f"Research Jobs:     {jobs_count}")
            click.echo(f"Research Reports:  {reports_count}")
            click.echo(f"Artifacts Stored:  {artifacts_count}")
            click.echo(f"Listed Companies:  {companies_count}")
            click.echo(f"Approved Sources:  {sources_count}")
    except Exception as e:
        click.echo(f"\nDatabase Connection: ERROR ({e})")


@cli.command("serve")
@click.option("--host", default=None, help="Host address to bind.")
@click.option("--port", default=None, type=int, help="Port to bind.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload on code change.")
def serve_cmd(host: Optional[str], port: Optional[int], reload: bool) -> None:
    """Start the MarketPulse FastAPI application server."""
    h = host or mp_settings.api_host
    p = port or mp_settings.api_port
    click.echo(f"Starting MarketPulse API server on http://{h}:{p}...")
    try:
        uvicorn.run("marketpulse.api.app:app", host=h, port=p, reload=reload)
    except OSError as e:
        if getattr(e, "winerror", None) == 10048 or "10048" in str(e):
            click.echo(
                click.style(
                    f"\n[PORT CONFLICT] Port {p} is already in use by another MarketPulse server or process.\n"
                    f"To free port {p}, stop the existing server or run MarketPulse on another port:\n"
                    f"  marketpulse serve --port {p + 1}",
                    fg="yellow",
                    bold=True,
                ),
                err=True,
            )
            sys.exit(1)
        raise


@cli.command("test-env")
def test_env_cmd() -> None:
    """Validate environment settings, required paths, and write permissions."""
    click.echo("Running environment validation checks...")
    mp_settings.ensure_directories()
    checks = [
        ("Artifacts Directory", mp_settings.artifacts_dir.exists()),
        ("Logs Directory", mp_settings.log_dir.exists()),
        ("Data Directory", mp_settings.data_dir.exists()),
    ]
    all_ok = True
    for name, ok in checks:
        status_text = click.style("PASS", fg="green") if ok else click.style("FAIL", fg="red")
        click.echo(f" - {name:<25} [{status_text}]")
        if not ok:
            all_ok = False

    if all_ok:
        click.echo(click.style("Environment is fully valid and ready for execution.", fg="green"))
    else:
        click.echo(click.style("One or more environment checks failed.", fg="red"), err=True)
        sys.exit(1)


@cli.command("sources")
def sources_cmd() -> None:
    """List approved market research sources in the registry."""
    with get_session() as session:
        sources = session.query(SourceRegistry).all()
        if not sources:
            click.echo("No sources registered. Run 'marketpulse init-db' first.")
            return

        click.echo(f"{'SOURCE ID':<25} | {'METHOD':<10} | {'LIMIT/M':<7} | {'RELIABILITY':<11} | NAME")
        click.echo("-" * 90)
        for s in sources:
            click.echo(
                f"{s.id:<25} | {s.retrieval_method:<10} | {s.rate_limit_per_minute:<7} | {s.reliability_score:<11} | {s.name}"
            )


@cli.command("collect")
@click.option("--source", default=None, help="Specific source ID to collect from (e.g. 'rbi_press_releases').")
@click.option("--symbol", default=None, help="Filter for specific Indian company ticker.")
@click.option("--max-items", default=10, type=int, help="Maximum items to ingest.")
def collect_cmd(source: Optional[str], symbol: Optional[str], max_items: int) -> None:
    """Collect and normalize evidence records from approved market sources."""
    from marketpulse.research.collectors import SourceCollector
    with get_session() as session:
        collector = SourceCollector(session=session)
        target = source or "permitted_financial_rss"
        click.echo(f"Starting research collection from '{target}' (Symbol filter: {symbol or 'None'})...")
        res = collector.collect_from_source(source_id=target, target_symbol=symbol, max_items=max_items)
        if res.get("status") == "COMPLETED":
            click.echo(click.style("Collection completed successfully!", fg="green"))
            click.echo(f" - Items parsed:          {res.get('items_parsed', 0)}")
            click.echo(f" - New evidence records:  {res.get('new_evidence_records', 0)}")
            click.echo(f" - Duplicates skipped:    {res.get('duplicates_skipped', 0)}")
            click.echo(f" - Incomplete flagged:    {res.get('incomplete_flagged', 0)}")
        else:
            click.echo(click.style(f"Collection ended with status: {res.get('status')}", fg="yellow"))


@cli.group("task")
def task_group() -> None:
    """Manage and inspect automated research and workflow tasks."""
    pass


@task_group.command("list")
@click.option("--status", default=None, help="Filter by status (PENDING, RUNNING, COMPLETED, etc.).")
@click.option("--limit", default=20, type=int, help="Maximum tasks to show.")
def task_list_cmd(status: Optional[str], limit: int) -> None:
    """List recent automation tasks."""
    with get_session() as session:
        query = session.query(AutomationTask)
        if status:
            query = query.filter(AutomationTask.status == status.upper())
        tasks = query.order_by(AutomationTask.started_at.desc()).limit(limit).all()

        if not tasks:
            click.echo("No tasks found.")
            return

        click.echo(f"{'TASK ID':<36} | {'TYPE':<10} | {'STATUS':<12} | {'PROMPT':<35} | STARTED")
        click.echo("-" * 115)
        for t in tasks:
            prompt_preview = t.prompt[:32] + "..." if len(t.prompt) > 35 else t.prompt
            click.echo(
                f"{t.id:<36} | {t.task_type:<10} | {t.status:<12} | {prompt_preview:<35} | {t.started_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )


@task_group.command("show")
@click.argument("task_id")
def task_show_cmd(task_id: str) -> None:
    """Display detailed task information and generated artifacts."""
    with get_session() as session:
        task = session.query(AutomationTask).filter(AutomationTask.id == task_id).first()
        if not task:
            click.echo(f"Error: Task '{task_id}' not found.", err=True)
            return

        click.echo(f"Task ID:             {task.id}")
        click.echo(f"Type:                {task.task_type}")
        click.echo(f"Status:              {task.status}")
        click.echo(f"Prompt:              {task.prompt}")
        click.echo(f"Step Limit:          {task.step_limit} (Current: {task.current_step})")
        click.echo(f"Requires Approval:   {task.requires_approval}")
        click.echo(f"Started At:          {task.started_at}")
        click.echo(f"Completed At:        {task.completed_at}")
        if task.cancellation_reason:
            click.echo(f"Cancellation Reason: {task.cancellation_reason}")
        if task.error_message:
            click.echo(f"Error:               {task.error_message}")
        if task.result_summary:
            click.echo(f"\nResult Summary:\n{task.result_summary}")

        artifacts = session.query(ArtifactRecord).filter(ArtifactRecord.task_id == task_id).all()
        click.echo(f"\nArtifacts ({len(artifacts)}):")
        for a in artifacts:
            click.echo(f" - [{a.artifact_type}] {a.name} ({a.size_bytes} bytes) -> {a.file_path}")


@task_group.command("cancel")
@click.argument("task_id")
@click.option("--reason", default="Cancelled via CLI", help="Reason for cancellation.")
def task_cancel_cmd(task_id: str, reason: str) -> None:
    """Cancel an active or pending task."""
    with get_session() as session:
        task = session.query(AutomationTask).filter(AutomationTask.id == task_id).first()
        if not task:
            click.echo(f"Error: Task '{task_id}' not found.", err=True)
            return

        if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
            click.echo(f"Cannot cancel task in terminal state '{task.status}'.", err=True)
            return

        task.status = TaskStatus.CANCELLED.value
        task.cancellation_reason = reason
        task.completed_at = datetime.now(timezone.utc)
        session.commit()
        click.echo(f"Task '{task_id}' has been cancelled.")


# ---------------------------------------------------------------------------
# Market Brief CLI
# ---------------------------------------------------------------------------
@cli.command("brief")
@click.option("--date", "session_date_str", default=None, help="Session date in YYYY-MM-DD (defaults to today).")
def brief_cmd(session_date_str: Optional[str]) -> None:
    """Generate an Indian market session brief with verified statistics and IST trading calendar."""
    from datetime import date
    from marketpulse.research.market_brief import MarketBriefGenerator

    target_date = None
    if session_date_str:
        try:
            target_date = date.fromisoformat(session_date_str)
        except ValueError:
            click.echo(f"Invalid date format '{session_date_str}'. Expected YYYY-MM-DD.", err=True)
            return

    with get_session() as session:
        generator = MarketBriefGenerator(session=session)
        brief = generator.generate_brief(session_date=target_date)

    click.echo(f"=== Indian Market Brief — {brief.session_date} ===")
    click.echo(f"Session State:     {brief.session_state.value}")
    click.echo(f"Generated (IST):   {brief.generated_at_ist}")
    click.echo(f"Data Freshness:    {brief.data_freshness_label}")
    click.echo(f"\n{brief.executive_summary}\n")

    if brief.verified_statistics:
        click.echo("Verified Market Statistics:")
        for s in brief.verified_statistics:
            click.echo(f" - {s.company_name} ({s.symbol}): {s.value} (Date: {s.observation_date}, Source: {s.source_reference})")
    else:
        click.echo("Verified Market Statistics: None recorded in historical window.")

    if brief.artifact_path:
        click.echo(f"\nReport Artifact:   {brief.artifact_path}")


# ---------------------------------------------------------------------------
# Watchlist Intelligence CLI
# ---------------------------------------------------------------------------
@cli.group("watchlist")
def watchlist_group() -> None:
    """Manage monitored symbols, alert rules, and evaluate disclosures."""
    pass


@watchlist_group.command("list")
@click.option("--watchlist", "wl_name", default="NIFTY_CORE", help="Watchlist name to inspect.")
def watchlist_list_cmd(wl_name: str) -> None:
    """List all enrolled symbols and rules in a watchlist."""
    from marketpulse.research.watchlist_intelligence import WatchlistIntelligenceManager

    with get_session() as session:
        mgr = WatchlistIntelligenceManager(session=session)
        symbols = mgr.list_watchlist_symbols(wl_name)
        wl = mgr.get_or_create_watchlist(wl_name)

        click.echo(f"=== Watchlist: {wl.name} ({len(symbols)} symbols) ===")
        if wl.description:
            click.echo(f"Description: {wl.description}")
        click.echo(f"Symbols:     {', '.join(symbols) if symbols else 'None'}")

        rules = wl.alert_rules
        click.echo(f"Active Rules ({len(rules)}):")
        for r in rules:
            click.echo(f" - [{r.rule_type}] Cooldown: {r.cooldown_minutes}m, Config: {r.threshold_config_json}")


@watchlist_group.command("add")
@click.argument("symbol")
@click.option("--watchlist", "wl_name", default="NIFTY_CORE", help="Target watchlist name.")
@click.option("--notes", default=None, help="Optional analyst notes.")
def watchlist_add_cmd(symbol: str, wl_name: str, notes: Optional[str]) -> None:
    """Add a company symbol to a watchlist."""
    from marketpulse.research.watchlist_intelligence import WatchlistIntelligenceManager

    with get_session() as session:
        mgr = WatchlistIntelligenceManager(session=session)
        item = mgr.add_symbol_to_watchlist(wl_name, symbol, notes=notes)
        session.commit()
        click.echo(f"Added {symbol.upper()} to watchlist '{wl_name}'.")


@watchlist_group.command("remove")
@click.argument("symbol")
@click.option("--watchlist", "wl_name", default="NIFTY_CORE", help="Target watchlist name.")
def watchlist_remove_cmd(symbol: str, wl_name: str) -> None:
    """Remove a company symbol from a watchlist."""
    from marketpulse.research.watchlist_intelligence import WatchlistIntelligenceManager

    with get_session() as session:
        mgr = WatchlistIntelligenceManager(session=session)
        removed = mgr.remove_symbol_from_watchlist(wl_name, symbol)
        session.commit()
        if removed:
            click.echo(f"Removed {symbol.upper()} from watchlist '{wl_name}'.")
        else:
            click.echo(f"Symbol '{symbol.upper()}' was not in watchlist '{wl_name}'.")


@watchlist_group.command("evaluate")
def watchlist_evaluate_cmd() -> None:
    """Evaluate recent evidence records against all active watchlists and alert rules."""
    from marketpulse.research.watchlist_intelligence import WatchlistIntelligenceManager
    from marketpulse.storage.models import EvidenceRecord

    with get_session() as session:
        mgr = WatchlistIntelligenceManager(session=session)
        records = session.query(EvidenceRecord).order_by(EvidenceRecord.retrieved_at.desc()).limit(50).all()
        result = mgr.evaluate_evidence_records(records)
        session.commit()

    click.echo(f"=== Watchlist Alert Evaluation ===")
    click.echo(f"Evaluated Watchlists: {result.evaluated_watchlist_count}")
    click.echo(f"Monitored Symbols:    {result.evaluated_symbol_count}")
    click.echo(f"Alerts Triggered:     {result.alerts_triggered_count}")

    for alert in result.alerts:
        click.echo(f"\n[{alert.severity}] {alert.title}")
        click.echo(f"Symbol:    {alert.company_symbol} ({alert.company_name})")
        click.echo(f"Rationale: {alert.trigger_rationale}")
        if alert.source_url:
            click.echo(f"Source:    {alert.source_url}")


# ---------------------------------------------------------------------------
# Research On-Demand CLI
# ---------------------------------------------------------------------------
@cli.command("research")
@click.argument("prompt")
@click.option("--symbol", default=None, help="Target NSE/BSE company symbol override.")
@click.option("--ai-provider", default=None, help="AI model provider (mock, ollama, cloud).")
def research_cmd(prompt: str, symbol: Optional[str], ai_provider: Optional[str]) -> None:
    """Execute on-demand research on an Indian listed company or market theme."""
    from marketpulse.research.pipeline import ResearchPipeline

    click.echo(f"Executing research pipeline for: '{prompt}'...")
    with get_session() as session:
        pipeline = ResearchPipeline(session=session, model_provider=ai_provider)
        report = pipeline.run(prompt=prompt, company_symbol=symbol)
        session.commit()

    click.echo(f"\n=== {report.title} ===")
    click.echo(f"Report ID:         {report.report_id}")
    click.echo(f"Company:           {report.company_name} ({report.company_symbol})")
    click.echo(f"Sector:            {report.sector_name}")
    click.echo(f"\nExecutive Summary:\n{report.executive_summary}\n")
    click.echo(f"Key Findings ({len(report.key_developments)}):")
    for d in report.key_developments:
        click.echo(f" - {d}")

    click.echo(f"\nScenario Analysis:")
    click.echo(f" - Bull: {report.scenarios.bull_case}")
    click.echo(f" - Base: {report.scenarios.base_case}")
    click.echo(f" - Bear: {report.scenarios.bear_case}")

    click.echo(f"\nVerified Evidence Citations ({len(report.evidence_references)}):")
    for ev in report.evidence_references[:3]:
        click.echo(f" - {ev['fact']} -> {ev['url']}")

    if report.artifact_location:
        click.echo(f"\nSaved Report Artifact: {report.artifact_location}")


# ---------------------------------------------------------------------------
# Permitted Schedules CLI
# ---------------------------------------------------------------------------
@cli.group("schedule")
def schedule_group() -> None:
    """Manage and trigger permitted automated schedules."""
    pass


@schedule_group.command("list")
def schedule_list_cmd() -> None:
    """List all configured automation schedules."""
    from marketpulse.storage.models import ScheduleDefinition
    with get_session() as session:
        schedules = session.query(ScheduleDefinition).order_by(ScheduleDefinition.created_at.asc()).all()
        if not schedules:
            click.echo("No schedules configured. Run 'marketpulse init-db' first.")
            return

        click.echo(f"{'SCHEDULE ID':<22} | {'TYPE':<12} | {'TIMING':<15} | {'ACTIVE':<6} | {'DRY':<5} | NAME")
        click.echo("-" * 95)
        for s in schedules:
            timing = s.cron_expression or s.schedule_type
            click.echo(f"{s.id:<22} | {s.task_type:<12} | {timing:<15} | {str(s.is_active):<6} | {str(s.dry_run):<5} | {s.name}")


@schedule_group.command("trigger")
@click.argument("schedule_id")
@click.option("--dry-run", is_flag=True, default=False, help="Run simulation without state modification.")
def schedule_trigger_cmd(schedule_id: str, dry_run: bool) -> None:
    """Trigger execution of an automated schedule."""
    from marketpulse.storage.models import ScheduleDefinition
    from marketpulse.agent.orchestrator import TaskOrchestrator
    with get_session() as session:
        sch = session.query(ScheduleDefinition).filter_by(id=schedule_id).first()
        if not sch:
            click.echo(f"Error: Schedule '{schedule_id}' not found.", err=True)
            return

        is_dry = dry_run or sch.dry_run
        now_utc = datetime.now(timezone.utc)
        sch.last_run_at = now_utc

        if is_dry:
            click.echo(click.style(f"Triggered DRY RUN for '{sch.name}' ({sch.id}). No persistent state changed.", fg="yellow"))
            click.echo(f" - Task Type: {sch.task_type}")
            click.echo(f" - Prompt:    {sch.prompt}")
            session.commit()
            return

        orchestrator = TaskOrchestrator(session=session)
        task = orchestrator.submit_task(prompt=sch.prompt, task_type=sch.task_type, step_limit=25)
        session.commit()
        click.echo(click.style(f"Dispatched task '{task.id}' for schedule '{sch.name}'.", fg="green"))


# ---------------------------------------------------------------------------
# Emergency Stop CLI
# ---------------------------------------------------------------------------
@cli.command("emergency-stop")
@click.option("--reason", default="Emergency stop triggered via CLI", help="Reason for emergency stop.")
def emergency_stop_cmd(reason: str) -> None:
    """Immediately halt all active and incoming MarketPulse automation tasks."""
    from marketpulse.agent.security import emergency_stop
    emergency_stop.trigger(reason=reason)
    click.echo(click.style(f"EMERGENCY STOP ACTIVATED: {reason}", fg="red", bold=True))


@cli.command("reset-stop")
def reset_stop_cmd() -> None:
    """Clear emergency stop flag and restore normal execution."""
    from marketpulse.agent.security import emergency_stop
    emergency_stop.reset()
    click.echo(click.style("Emergency stop has been CLEARED. Tasks may resume.", fg="green"))


# ---------------------------------------------------------------------------
# Database Backup & Restore CLI
# ---------------------------------------------------------------------------
@cli.group("backup")
def backup_group() -> None:
    """Manage database online backups and disaster recovery."""
    pass


@backup_group.command("create")
@click.option("--label", default=None, help="Optional descriptive tag for backup file.")
def backup_create_cmd(label: Optional[str]) -> None:
    """Create a consistent online backup with checksum verification."""
    from marketpulse.storage.backup import DatabaseBackupManager
    mgr = DatabaseBackupManager()
    try:
        res = mgr.create_backup(label=label)
        click.echo(click.style("Database backup created successfully!", fg="green"))
        click.echo(f" - File:     {res['backup_filename']}")
        click.echo(f" - Size:     {res['size_bytes']} bytes")
        click.echo(f" - SHA-256:  {res['sha256']}")
        click.echo(f" - Path:     {res['backup_path']}")
    except Exception as e:
        click.echo(click.style(f"Backup failed: {e}", fg="red"), err=True)


@backup_group.command("list")
def backup_list_cmd() -> None:
    """List available database backups."""
    from marketpulse.storage.backup import DatabaseBackupManager
    mgr = DatabaseBackupManager()
    backups = mgr.list_backups()
    if not backups:
        click.echo("No backups found.")
        return

    click.echo(f"{'FILENAME':<42} | {'SIZE (BYTES)':<12} | CREATED (UTC)")
    click.echo("-" * 80)
    for b in backups:
        click.echo(f"{b['backup_filename']:<42} | {b.get('size_bytes', 0):<12} | {b.get('created_at', '-')}")


@backup_group.command("restore")
@click.argument("backup_path")
def backup_restore_cmd(backup_path: str) -> None:
    """Restore database from a verified backup file."""
    from marketpulse.storage.backup import DatabaseBackupManager
    mgr = DatabaseBackupManager()
    try:
        res = mgr.restore_backup(Path(backup_path))
        click.echo(click.style("Database restored successfully!", fg="green"))
        click.echo(f" - Restored from: {res['restored_from']}")
        click.echo(f" - Target DB:     {res['database_path']}")
        click.echo(f" - Schema Vers:   {res['schema_version']}")
    except Exception as e:
        click.echo(click.style(f"Restore failed: {e}", fg="red"), err=True)


def main() -> None:
    """Main CLI entry point."""
    cli()


if __name__ == "__main__":
    main()

