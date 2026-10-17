"""Unit tests for AI model providers and structured output validation."""

import json
from unittest.mock import MagicMock
import httpx
import pytest
from pydantic import BaseModel, Field
from personal_ai.agent.planner import TaskPlanner
from personal_ai.agent.task_models import ExecutionPlan, PlanStep, RiskLevel
from personal_ai.models import (
    BaseModelProvider,
    CloudProvider,
    MockProvider,
    ModelOutputValidationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelUnavailableError,
    OllamaProvider,
    get_provider,
)
from personal_ai.tools.registry import default_registry


def test_mock_provider() -> None:
    mock = MockProvider()
    health = mock.health_check()
    assert health.available is True
    assert health.provider_name == "mock"

    resp = mock.generate("Summarize this task")
    assert "Mock response" in resp.text
    assert resp.model_name == "mock-agent-v1"

    plan = mock.generate_plan("Do something", default_registry.list_tools())
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) >= 1


def test_get_provider_factory() -> None:
    assert isinstance(get_provider("mock"), MockProvider)
    assert isinstance(get_provider("ollama"), OllamaProvider)
    assert isinstance(get_provider("cloud"), CloudProvider)

    with pytest.raises(ValueError):
        get_provider("unknown_provider_xyz")


def test_ollama_provider_offline() -> None:
    # Pointing to an invalid local port to simulate offline server
    ollama = OllamaProvider(base_url="http://127.0.0.1:59999", timeout_sec=1.0)
    health = ollama.health_check()
    assert health.available is False
    assert "not running" in health.details.lower() or "error" in health.details.lower()

    with pytest.raises(ModelUnavailableError):
        ollama.generate("Test prompt")


def test_ollama_provider_mock_http() -> None:
    class DummyOutput(BaseModel):
        answer: str = Field(...)

    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})
        elif request.url.path == "/api/generate":
            return httpx.Response(200, json={
                "response": json.dumps({"answer": "Automation is powerful."}),
                "prompt_eval_count": 15,
                "eval_count": 8,
            })
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    ollama = OllamaProvider(base_url="http://mock-ollama:11434", model_name="llama3.2", client=client)

    health = ollama.health_check()
    assert health.available is True

    resp = ollama.generate(
        prompt="Tell me about automation",
        response_format=DummyOutput,
    )
    assert resp.structured_data is not None
    assert resp.structured_data["answer"] == "Automation is powerful."
    assert resp.prompt_tokens == 15


def test_ollama_provider_malformed_json() -> None:
    class DummyOutput(BaseModel):
        answer: str = Field(...)

    def mock_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "This is raw text, not valid JSON."})

    client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    ollama = OllamaProvider(base_url="http://mock-ollama:11434", client=client)

    with pytest.raises(ModelOutputValidationError):
        ollama.generate("Generate structured output", response_format=DummyOutput)


def test_cloud_provider_missing_key() -> None:
    cloud = CloudProvider(api_key="")
    health = cloud.health_check()
    assert health.available is False
    assert "CLOUD_API_KEY is not configured" in health.details

    with pytest.raises(ModelUnavailableError):
        cloud.generate("Test prompt")


def test_cloud_provider_mock_http() -> None:
    def mock_transport(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        if "Bearer test-secret-key" not in auth:
            return httpx.Response(401, json={"error": "Unauthorized"})

        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})

        elif request.url.path == "/v1/chat/completions":
            body = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={
                "choices": [{
                    "message": {"content": json.dumps({"status": "healthy"})}
                }],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            })

        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    cloud = CloudProvider(
        api_key="test-secret-key",
        base_url="https://api.openai.com/v1",
        client=client,
    )

    health = cloud.health_check()
    assert health.available is True

    class HealthOutput(BaseModel):
        status: str = Field(...)

    resp = cloud.generate("Health check", response_format=HealthOutput)
    assert resp.structured_data["status"] == "healthy"
    assert resp.prompt_tokens == 20


def test_cloud_provider_rate_limit() -> None:
    def mock_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Rate limit exceeded"})

    client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    cloud = CloudProvider(api_key="test-key", client=client)

    with pytest.raises(ModelRateLimitError):
        cloud.generate("Heavy prompt")


def test_task_planner_with_ai_provider() -> None:
    mock_provider = MockProvider()
    planner = TaskPlanner(model_provider=mock_provider)

    plan = planner.plan("Organize downloaded invoice files", use_ai=True)
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) >= 1
    assert "MockProvider" in plan.assumptions[0]


def test_task_planner_ai_fallback() -> None:
    failing_provider = MagicMock(spec=BaseModelProvider)
    failing_provider.provider_name = "failing-ai"
    failing_provider.generate_plan.side_effect = ModelProviderError("Out of memory")

    planner = TaskPlanner(model_provider=failing_provider)
    # Even if AI fails, planner falls back deterministically to rule-based plan
    plan = planner.plan("read file 'sample.txt'", use_ai=True)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "read_file"
