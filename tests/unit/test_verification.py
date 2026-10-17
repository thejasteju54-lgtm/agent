"""Unit tests for StepVerifier."""

from pathlib import Path
from personal_ai.agent.verification import StepVerifier


def test_verify_file_exists(temp_dir: Path) -> None:
    test_file = temp_dir / "target.txt"

    # Before creation
    res_before = StepVerifier.verify_file_exists(test_file)
    assert not res_before.passed

    # After creation
    test_file.write_text("verification sample data")
    res_after = StepVerifier.verify_file_exists(test_file)
    assert res_after.passed
    assert res_after.details["size_bytes"] > 0


def test_verify_content_matches() -> None:
    output = "Operation completed with 42 items indexed."
    assert StepVerifier.verify_content_matches(output, "42 items").passed
    assert not StepVerifier.verify_content_matches(output, "error code 500").passed


def test_verify_step_write_file(temp_dir: Path) -> None:
    test_file = str(temp_dir / "verified_write.txt")
    Path(test_file).write_text("persisted content")

    res = StepVerifier.verify_step(
        tool_name="write_file",
        params={"path": test_file, "content": "persisted content"},
        output={"status": "success"},
    )
    assert res.passed
