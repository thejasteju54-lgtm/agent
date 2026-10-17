"""Central tool registry and tool execution interface."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Type
from pydantic import BaseModel
from personal_ai.agent.task_models import RiskLevel
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)


class ToolDefinition(BaseModel):
    """Metadata describing a registered tool."""
    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.LOW
    timeout_sec: float = 30.0
    modifies_state: bool = False
    requires_approval: bool = False
    input_schema: Optional[Dict[str, Any]] = None


class BaseTool(ABC):
    """Abstract base class for all automation tools."""

    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.LOW
    timeout_sec: float = 30.0
    modifies_state: bool = False
    requires_approval: bool = False
    args_schema: Optional[Type[BaseModel]] = None

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with validated inputs."""
        pass

    def get_definition(self) -> ToolDefinition:
        """Return structured metadata definition for planner/agent."""
        schema = self.args_schema.model_json_schema() if self.args_schema else None
        return ToolDefinition(
            name=self.name,
            description=self.description,
            risk_level=self.risk_level,
            timeout_sec=self.timeout_sec,
            modifies_state=self.modifies_state,
            requires_approval=self.requires_approval,
            input_schema=schema,
        )


class FunctionalTool(BaseTool):
    """A tool created from a python callable and schema."""

    def __init__(
        self,
        name: str,
        description: str,
        func: Callable[..., Any],
        risk_level: RiskLevel = RiskLevel.LOW,
        timeout_sec: float = 30.0,
        modifies_state: bool = False,
        requires_approval: bool = False,
        args_schema: Optional[Type[BaseModel]] = None,
    ):
        self.name = name
        self.description = description
        self.func = func
        self.risk_level = risk_level
        self.timeout_sec = timeout_sec
        self.modifies_state = modifies_state
        self.requires_approval = requires_approval
        self.args_schema = args_schema

    def execute(self, **kwargs: Any) -> Any:
        if self.args_schema:
            validated = self.args_schema(**kwargs)
            return self.func(**validated.model_dump())
        return self.func(**kwargs)


class ToolRegistry:
    """Registry maintaining available tools and execution boundaries."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a new tool instance."""
        if tool.name in self._tools:
            logger.warning("Overwriting existing tool registration: %s", tool.name)
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s (Risk: %s)", tool.name, tool.risk_level)

    def get(self, name: str) -> Optional[BaseTool]:
        """Fetch a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        """List all registered tools."""
        return [tool.get_definition() for tool in self._tools.values()]

    def execute_tool(self, name: str, params: Dict[str, Any]) -> Any:
        """Find and execute a tool by name with input validation."""
        tool = self.get(name)
        if not tool:
            raise ValueError(f"Tool '{name}' is not registered.")
        return tool.execute(**params)


# Global singleton registry instance
default_registry = ToolRegistry()
