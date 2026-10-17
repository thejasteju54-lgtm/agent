"""AI Model Providers package."""

from typing import Optional
from personal_ai.config import settings
from .base import (
    BaseModelProvider,
    ModelOutputValidationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelResponse,
    ModelUnavailableError,
    ProviderHealth,
)
from .ollama_provider import OllamaProvider
from .cloud_provider import CloudProvider
from .mock_provider import MockProvider

__all__ = [
    "BaseModelProvider",
    "ModelOutputValidationError",
    "ModelProviderError",
    "ModelRateLimitError",
    "ModelResponse",
    "ModelUnavailableError",
    "ProviderHealth",
    "OllamaProvider",
    "CloudProvider",
    "MockProvider",
    "get_provider",
]


def get_provider(provider_type: Optional[str] = None) -> BaseModelProvider:
    """Factory to retrieve configured AI model provider instance."""
    ptype = (provider_type or settings.default_provider).lower()

    if ptype == "ollama":
        return OllamaProvider()
    elif ptype == "cloud":
        return CloudProvider()
    elif ptype == "mock":
        return MockProvider()
    else:
        raise ValueError(f"Unknown model provider type: '{ptype}'. Supported: 'ollama', 'cloud', 'mock'.")
