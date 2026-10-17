"""Cloud AI Model Provider adapter (OpenAI-compatible endpoints)."""

import json
from typing import Any, Dict, List, Optional, Type
import httpx
from pydantic import BaseModel, ValidationError
from personal_ai.agent.task_models import ExecutionPlan
from personal_ai.config import settings
from personal_ai.logging.setup import get_logger
from personal_ai.models.base import (
    BaseModelProvider,
    ModelOutputValidationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelResponse,
    ModelUnavailableError,
    ProviderHealth,
)
from personal_ai.tools.registry import ToolDefinition

logger = get_logger(__name__)


class CloudProvider(BaseModelProvider):
    """Cloud model provider connecting to OpenAI-compatible REST APIs."""

    provider_name: str = "cloud"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_sec: float = 60.0,
        client: Optional[httpx.Client] = None,
    ):
        self.api_key = api_key or settings.cloud_api_key or ""
        self.base_url = (base_url or settings.cloud_api_base or "https://api.openai.com/v1").rstrip("/")
        self.model_name = model_name or settings.cloud_model or "gpt-4o-mini"
        self.timeout_sec = timeout_sec
        self._client = client or httpx.Client(timeout=timeout_sec)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health_check(self) -> ProviderHealth:
        """Check if cloud API endpoint is configured and reachable."""
        if not self.api_key:
            return ProviderHealth(
                provider_name=self.provider_name,
                available=False,
                model_name=self.model_name,
                details="CLOUD_API_KEY is not configured in environment.",
            )

        endpoint = f"{self.base_url}/models"
        try:
            resp = self._client.get(endpoint, headers=self._headers())
            if resp.status_code == 200:
                return ProviderHealth(
                    provider_name=self.provider_name,
                    available=True,
                    model_name=self.model_name,
                    details="Cloud API authenticated and reachable.",
                )
            elif resp.status_code == 401:
                return ProviderHealth(
                    provider_name=self.provider_name,
                    available=False,
                    model_name=self.model_name,
                    details="Authentication failed (HTTP 401): Check CLOUD_API_KEY.",
                )
            return ProviderHealth(
                provider_name=self.provider_name,
                available=False,
                model_name=self.model_name,
                details=f"API returned status {resp.status_code}: {resp.text}",
            )
        except Exception as e:
            return ProviderHealth(
                provider_name=self.provider_name,
                available=False,
                model_name=self.model_name,
                details=f"Connection failed: {e}",
            )

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_format: Optional[Type[BaseModel]] = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        if not self.api_key:
            raise ModelUnavailableError("CLOUD_API_KEY is required to call cloud model provider.")

        endpoint = f"{self.base_url}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.post(endpoint, json=payload, headers=self._headers())
            if resp.status_code == 401:
                raise ModelProviderError("Invalid or unauthorized API key for cloud provider.")
            elif resp.status_code == 429:
                raise ModelRateLimitError("Cloud API rate limit or quota exceeded.")
            elif resp.status_code != 200:
                raise ModelProviderError(f"Cloud API returned HTTP {resp.status_code}: {resp.text}")

            result = resp.json()
            choice = result.get("choices", [{}])[0]
            raw_text = choice.get("message", {}).get("content", "")

            structured = None
            if response_format:
                try:
                    parsed_json = json.loads(raw_text)
                    structured = response_format.model_validate(parsed_json).model_dump()
                except (json.JSONDecodeError, ValidationError) as e:
                    raise ModelOutputValidationError(f"Failed to validate response into {response_format.__name__}: {e}")

            usage = result.get("usage", {})
            return ModelResponse(
                text=raw_text,
                structured_data=structured,
                model_name=self.model_name,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                raw_response=result,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ModelUnavailableError(f"Cannot connect to Cloud API at {self.base_url}: {e}")
        except httpx.TimeoutException as e:
            raise ModelProviderError(f"Cloud API request timed out after {self.timeout_sec}s: {e}")

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
            raise ModelOutputValidationError("Cloud provider did not return structured plan data.")

        return ExecutionPlan.model_validate(resp.structured_data)
