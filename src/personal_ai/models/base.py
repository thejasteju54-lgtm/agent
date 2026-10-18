from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from personal_ai.agent.task_models import ExecutionPlan
    from personal_ai.tools.registry import ToolDefinition


class ModelProviderError(Exception):
    """Base exception for model provider errors."""
    pass


class ModelUnavailableError(ModelProviderError):
    """Raised when the requested model provider service is unreachable."""
    pass


class ModelRateLimitError(ModelProviderError):
    """Raised when an API rate limit or quota is exceeded."""
    pass


class ModelOutputValidationError(ModelProviderError):
    """Raised when model response cannot be parsed into expected structured schema."""
    pass


class ProviderHealth(BaseModel):
    """Health status and metadata of a model provider."""
    provider_name: str
    available: bool
    model_name: str
    details: Optional[str] = None


class ModelResponse(BaseModel):
    """Structured response from a model invocation."""
    text: str
    structured_data: Optional[Dict[str, Any]] = None
    model_name: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    raw_response: Optional[Dict[str, Any]] = None


class BaseModelProvider(ABC):
    """Abstract interface for all LLM providers."""

    provider_name: str = "base"

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Verify provider availability and connectivity."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_format: Optional[Type[BaseModel]] = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        """Generate response text or structured data from the model."""
        pass

    @abstractmethod
    def generate_plan(
        self,
        prompt: str,
        available_tools: List[ToolDefinition],
    ) -> ExecutionPlan:
        """Decompose a natural language prompt into an ExecutionPlan using available tools."""
        pass
