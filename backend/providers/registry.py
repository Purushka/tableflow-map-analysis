"""Provider registry and unified call_llm() entry point."""
from .base import LLMProvider, ModelInfo, LLMResponse, LLMUsage
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider
from .google_provider import GoogleProvider
from .ollama_provider import OllamaProvider
from .scnet_provider import SCNetProvider
from .openrouter_provider import OpenRouterProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {}
_MODEL_TO_PROVIDER: dict[str, str] = {}


def init_providers():
    """Register all built-in providers."""
    for cls in [AnthropicProvider, OpenAIProvider, GoogleProvider, OllamaProvider, SCNetProvider, OpenRouterProvider]:
        pid = cls.provider_id()
        _PROVIDERS[pid] = cls
        for m in cls.models():
            _MODEL_TO_PROVIDER[m.id] = pid


def get_provider(provider_id: str) -> type[LLMProvider]:
    if provider_id not in _PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id}")
    return _PROVIDERS[provider_id]


def get_provider_for_model(model_id: str) -> type[LLMProvider]:
    pid = _MODEL_TO_PROVIDER.get(model_id)
    if not pid:
        raise ValueError(f"Unknown model: {model_id}. Available: {list(_MODEL_TO_PROVIDER.keys())}")
    return _PROVIDERS[pid]


def get_provider_id_for_model(model_id: str) -> str:
    """Return the provider_id for a given model_id."""
    pid = _MODEL_TO_PROVIDER.get(model_id)
    if not pid:
        raise ValueError(f"Unknown model: {model_id}")
    return pid


def get_all_providers() -> list[dict]:
    result = []
    for pid, cls in _PROVIDERS.items():
        result.append({
            "id": pid,
            "label": cls.label(),
            "api_key_pattern": cls.api_key_pattern(),
            "api_key_placeholder": cls.api_key_placeholder(),
            "models": [
                {"id": m.id, "label": m.label, "provider": m.provider, "context_window": m.context_window}
                for m in cls.models()
            ],
        })
    return result


def get_all_models() -> list[dict]:
    """Flat list of all models with their provider."""
    result = []
    for pid, cls in _PROVIDERS.items():
        for m in cls.models():
            result.append({
                "id": m.id,
                "label": m.label,
                "provider": pid,
                "provider_label": cls.label(),
            })
    return result


async def call_llm(model: str, system: str, user: str, max_tokens: int, api_key: str) -> str:
    """Universal LLM call - resolves provider from model ID."""
    provider = get_provider_for_model(model)
    return await provider.call(model, system, user, max_tokens, api_key)


async def call_vision_llm(
    model: str, system: str, user_text: str,
    image_data: str, media_type: str,
    max_tokens: int, api_key: str,
) -> LLMResponse:
    """Universal vision LLM call - sends image + text to the model.
    Returns LLMResponse with text and usage statistics."""
    provider = get_provider_for_model(model)
    result = await provider.call_vision(model, system, user_text, image_data, media_type, max_tokens, api_key)
    # Backward compat: if provider returns str, wrap it
    if isinstance(result, str):
        return LLMResponse(text=result)
    return result


async def call_vision_conversation(
    model: str, system: str, messages: list[dict],
    max_tokens: int, api_key: str,
) -> LLMResponse:
    """Multi-turn vision LLM call with message history.
    Returns LLMResponse with text and usage statistics."""
    provider = get_provider_for_model(model)
    result = await provider.call_vision_conversation(
        model, system, messages, max_tokens, api_key
    )
    # Backward compat: if provider returns str, wrap it
    if isinstance(result, str):
        return LLMResponse(text=result)
    return result
