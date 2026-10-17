"""Filesystem automation tools with security constraints."""

from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from personal_ai.agent.task_models import RiskLevel
from personal_ai.tools.registry import BaseTool, default_registry
from personal_ai.config import settings
from personal_ai.logging.setup import get_logger

from personal_ai.agent.security import validate_path_safety, PathSecurityError

logger = get_logger(__name__)


def _resolve_safe_path(
    target_path: str | Path,
    allow_write: bool = False,
    allow_delete: bool = False,
) -> Path:
    """Resolve and validate that the path is accessible and outside protected system roots."""
    return validate_path_safety(target_path, allow_write=allow_write, allow_delete=allow_delete)


class ReadFileInput(BaseModel):
    path: str = Field(..., description="Path to the file to read.")
    max_bytes: int = Field(default=50000, description="Maximum bytes to read.")


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read text content from a local file safely."
    risk_level = RiskLevel.LOW
    args_schema = ReadFileInput

    def execute(self, path: str, max_bytes: int = 50000) -> Dict[str, Any]:
        target = _resolve_safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {target}")
        if not target.is_file():
            raise ValueError(f"Path is not a regular file: {target}")

        content = target.read_text(encoding="utf-8", errors="replace")[:max_bytes]
        return {
            "path": str(target),
            "size_bytes": target.stat().st_size,
            "content": content,
            "truncated": target.stat().st_size > max_bytes,
        }


class WriteFileInput(BaseModel):
    path: str = Field(..., description="Path to the file to write.")
    content: str = Field(..., description="Text content to write.")
    overwrite: bool = Field(default=False, description="Whether to overwrite if file already exists.")


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write content to a file. Overwriting an existing file is Medium risk."
    risk_level = RiskLevel.LOW  # Will dynamically upgrade if overwriting
    modifies_state = True
    args_schema = WriteFileInput

    def execute(self, path: str, content: str, overwrite: bool = False) -> Dict[str, Any]:
        target = _resolve_safe_path(path, allow_write=True)
        existed = target.exists()

        if existed and not overwrite:
            raise FileExistsError(f"File already exists and overwrite=False: {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        return {
            "path": str(target),
            "size_bytes": len(content.encode("utf-8")),
            "overwritten": existed,
            "status": "success",
        }


class ListDirectoryInput(BaseModel):
    path: str = Field(default=".", description="Directory path to list.")


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "List entries in a local directory."
    risk_level = RiskLevel.LOW
    args_schema = ListDirectoryInput

    def execute(self, path: str = ".") -> Dict[str, Any]:
        target = _resolve_safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Directory not found: {target}")
        if not target.is_dir():
            raise ValueError(f"Path is not a directory: {target}")

        entries = []
        for p in target.iterdir():
            entries.append({
                "name": p.name,
                "is_dir": p.is_dir(),
                "size_bytes": p.stat().st_size if p.is_file() else None,
            })
        return {
            "directory": str(target),
            "total_entries": len(entries),
            "entries": entries,
        }


class DeleteFileInput(BaseModel):
    path: str = Field(..., description="Path to the file to delete.")


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Permanently delete a file. HIGH RISK action requiring explicit human approval."
    risk_level = RiskLevel.HIGH
    requires_approval = True
    modifies_state = True
    args_schema = DeleteFileInput

    def execute(self, path: str) -> Dict[str, Any]:
        target = _resolve_safe_path(path, allow_delete=True)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {target}")
        if not target.is_file():
            raise ValueError(f"Path is not a file: {target}")

        target.unlink()
        return {
            "path": str(target),
            "deleted": True,
            "status": "success",
        }


# Register filesystem tools to default registry
default_registry.register(ReadFileTool())
default_registry.register(WriteFileTool())
default_registry.register(ListDirectoryTool())
default_registry.register(DeleteFileTool())
