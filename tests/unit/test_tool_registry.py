"""Unit tests for ToolRegistry and filesystem tools."""

from pathlib import Path
import pytest
from pydantic import BaseModel, Field
from personal_ai.agent.task_models import RiskLevel
from personal_ai.tools.registry import BaseTool, FunctionalTool, ToolRegistry
from personal_ai.tools.filesystem import (
    ReadFileTool,
    WriteFileTool,
    ListDirectoryTool,
    DeleteFileTool,
)


def test_tool_registry_registration() -> None:
    registry = ToolRegistry()

    class DummyInput(BaseModel):
        msg: str = Field(...)

    class DummyTool(BaseTool):
        name = "dummy"
        description = "A dummy test tool"
        args_schema = DummyInput

        def execute(self, msg: str) -> str:
            return f"Echo: {msg}"

    tool = DummyTool()
    registry.register(tool)

    assert registry.get("dummy") is tool
    defn = registry.list_tools()[0]
    assert defn.name == "dummy"
    assert defn.risk_level == RiskLevel.LOW

    res = registry.execute_tool("dummy", {"msg": "hello"})
    assert res == "Echo: hello"


def test_filesystem_tools(temp_dir: Path) -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(DeleteFileTool())

    file_path = str(temp_dir / "sample.txt")

    # 1. Write file
    w_res = registry.execute_tool("write_file", {"path": file_path, "content": "Hello World"})
    assert w_res["status"] == "success"
    assert Path(file_path).read_text(encoding="utf-8") == "Hello World"

    # 2. Read file
    r_res = registry.execute_tool("read_file", {"path": file_path})
    assert r_res["content"] == "Hello World"

    # 3. List directory
    l_res = registry.execute_tool("list_directory", {"path": str(temp_dir)})
    assert l_res["total_entries"] == 1
    assert l_res["entries"][0]["name"] == "sample.txt"

    # 4. Delete file
    d_res = registry.execute_tool("delete_file", {"path": file_path})
    assert d_res["deleted"] is True
    assert not Path(file_path).exists()
