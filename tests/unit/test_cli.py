"""Unit tests for the CLI commands."""

from pathlib import Path
from click.testing import CliRunner
from personal_ai.cli import cli
from personal_ai.config import settings
from personal_ai.storage.database import Database
from personal_ai.storage.repositories import TaskRepository


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "personal-ai" in result.output


def test_cli_init_db_and_status(tmp_path: Path) -> None:
    runner = CliRunner()
    test_db = tmp_path / "cli_test.db"
    settings.database_path = test_db

    # Run init-db
    result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0
    assert "Database initialization complete" in result.output

    # Run status
    status_result = runner.invoke(cli, ["status"])
    assert status_result.exit_code == 0
    assert "Personal AI Automation System" in status_result.output
    assert "Tasks in DB:        0" in status_result.output


def test_cli_task_list_and_show(tmp_path: Path) -> None:
    runner = CliRunner()
    test_db = tmp_path / "cli_task_test.db"
    db = Database(test_db)
    db.initialize_schema()
    settings.database_path = test_db

    repo = TaskRepository(db=db)
    repo.create_task("task-1234", "Download quarterly report", status="RUNNING")

    # List tasks
    list_res = runner.invoke(cli, ["task", "list"])
    assert list_res.exit_code == 0
    assert "task-1234" in list_res.output
    assert "Download quarterly report" in list_res.output

    # Show task
    show_res = runner.invoke(cli, ["task", "show", "task-1234"])
    assert show_res.exit_code == 0
    assert "task-1234" in show_res.output
    assert "RUNNING" in show_res.output
