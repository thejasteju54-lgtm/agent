"""Unit tests for ArtifactManager."""

from personal_ai.storage.artifacts import ArtifactManager
from personal_ai.storage.repositories import TaskRepository


def test_save_general_artifact(artifact_manager: ArtifactManager) -> None:
    res = artifact_manager.save_text("note.txt", "Sample general artifact note", task_id=None)
    assert res["file_name"] == "note.txt"
    assert res["task_id"] is None
    assert res["mime_type"] == "text/plain"
    assert res["size_bytes"] == len("Sample general artifact note")

    retrieved = artifact_manager.get_artifact(res["id"])
    assert retrieved is not None
    assert retrieved["file_name"] == "note.txt"


def test_save_task_artifact(artifact_manager: ArtifactManager, task_repo: TaskRepository) -> None:
    # First create task so foreign key constraint is satisfied
    task_repo.create_task("task-001", "Generate artifact task")

    res = artifact_manager.save_text("note.txt", "Sample artifact note", task_id="task-001")
    assert res["file_name"] == "note.txt"
    assert res["task_id"] == "task-001"
    assert res["mime_type"] == "text/plain"
    assert res["size_bytes"] == len("Sample artifact note")

    task_artifacts = artifact_manager.list_artifacts_for_task("task-001")
    assert len(task_artifacts) == 1
    assert task_artifacts[0]["id"] == res["id"]


def test_save_json_artifact(artifact_manager: ArtifactManager, task_repo: TaskRepository) -> None:
    task_repo.create_task("task-002", "Generate json task")

    payload = {"status": "ok", "count": 42}
    res = artifact_manager.save_json("report.json", payload, task_id="task-002")
    assert res["mime_type"] == "application/json"
    assert res["size_bytes"] > 0
