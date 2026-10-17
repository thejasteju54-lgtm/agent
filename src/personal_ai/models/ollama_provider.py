"""Ollama local AI model provider adapter."""

import json
import uuid
from typing import Any, Dict, List, Optional, Type
import httpx
from pydantic import BaseModel, ValidationError
from personal_ai.agent.task_models import ExecutionPlan, PlanStep, RiskLevel
from personal_ai.config import settings
from personal_ai.logging.setup import get_logger
from personal_ai.models.base import (
    BaseModelProvider,
    ModelOutputValidationError,
    ModelProviderError,
    ModelResponse,
    ModelUnavailableError,
    ProviderHealth,
)
from personal_ai.tools.registry import ToolDefinition

logger = get_logger(__name__)


class OllamaProvider(BaseModelProvider):
    """Local model provider using Ollama HTTP API."""

    provider_name: str = "ollama"

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_sec: float = 60.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model_name = model_name or settings.ollama_model
        self.timeout_sec = timeout_sec
        self._client = client or httpx.Client(timeout=timeout_sec)

    def health_check(self) -> ProviderHealth:
        """Check if local Ollama daemon is reachable and model is available."""
        endpoint = f"{self.base_url}/api/tags"
        try:
            resp = self._client.get(endpoint)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                installed = any(self.model_name in m for m in models)
                details = f"Server online. Installed models: {', '.join(models) if models else 'none'}"
                return ProviderHealth(
                    provider_name=self.provider_name,
                    available=installed,
                    model_name=self.model_name,
                    details=details if installed else f"Model '{self.model_name}' not installed. Run 'ollama pull {self.model_name}'.",
                )
            return ProviderHealth(
                provider_name=self.provider_name,
                available=False,
                model_name=self.model_name,
                details=f"Ollama server returned status {resp.status_code}",
            )
        except httpx.ConnectError:
            return ProviderHealth(
                provider_name=self.provider_name,
                available=False,
                model_name=self.model_name,
                details=f"Ollama not running at {self.base_url}. Start it with 'ollama serve'.",
            )
        except Exception as e:
            return ProviderHealth(
                provider_name=self.provider_name,
                available=False,
                model_name=self.model_name,
                details=f"Connection check error: {e}",
            )

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_format: Optional[Type[BaseModel]] = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        endpoint = f"{self.base_url}/api/generate"
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system_prompt:
            payload["system"] = system_prompt
        if response_format:
            payload["format"] = "json"

        try:
            resp = self._client.post(endpoint, json=payload)
            if resp.status_code != 200:
                raise ModelProviderError(f"Ollama returned HTTP {resp.status_code}: {resp.text}")

            result = resp.json()
            raw_text = result.get("response", "")

            structured = None
            if response_format:
                try:
                    parsed_json = json.loads(raw_text)
                    structured = response_format.model_validate(parsed_json).model_dump()
                except (json.JSONDecodeError, ValidationError) as e:
                    raise ModelOutputValidationError(f"Failed to validate Ollama response into {response_format.__name__}: {e}")

            return ModelResponse(
                text=raw_text,
                structured_data=structured,
                model_name=self.model_name,
                prompt_tokens=result.get("prompt_eval_count"),
                completion_tokens=result.get("eval_count"),
                raw_response=result,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ModelUnavailableError(f"Cannot connect to Ollama at {self.base_url}: {e}")
        except httpx.TimeoutException as e:
            raise ModelProviderError(f"Ollama request timed out after {self.timeout_sec}s: {e}")

    def generate_plan(
        self,
        prompt: str,
        available_tools: List[ToolDefinition],
    ) -> ExecutionPlan:
        tool_descriptions = "\n".join([
            f"- {t.name}: {t.description} (Risk: {t.risk_level.value}, Inputs: {t.input_schema})"
            for t in available_tools
        ])

        system_prompt = (
            "You are an AI task decomposition planner. Given a user automation request and a list of available tools, "
            "return a JSON object following this exact schema:\n"
            "{\n"
            '  "task_id": "string",\n'
            '  "prompt": "string",\n'
            '  "steps": [\n'
            '    {\n'
            '      "step_id": "string",\n'
            '      "step_number": 1,\n'
            '      "tool_name": "string",\n'
            '      "description": "string",\n'
            '      "input_params": {},\n'
            '      "risk_level": "low|medium|high",\n'
            '      "requires_approval": false,\n'
            '      "expected_outcome": "string"\n'
            "    }\n"
            "  ],\n"
            '  "assumptions": ["string"],\n'
            '  "requires_clarification": false,\n'
            '  "clarification_question": null\n'
            "}\n\n"
            f"Available tools:\n{tool_descriptions}"
        )

        resp = self.generate(
            prompt=f"Create execution plan for: '{prompt}'",
            system_prompt=system_prompt,
            response_format=ExecutionPlan,
        )
        if not resp.structured_data:
            raise ModelOutputValidationError("Ollama did not return structured plan data.")

        return ExecutionPlan.model_validate(resp.structured_data)
