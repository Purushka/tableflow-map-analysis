"""LLM Provider abstraction."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ModelInfo:
    id: str
    label: str
    provider: str
    context_window: int = 128000
    max_output: int = 8192


@dataclass
class LLMUsage:
    """Token usage statistics from an LLM call."""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LLMResponse:
    """Response from an LLM call, including text and usage statistics."""
    text: str
    usage: LLMUsage = field(default_factory=LLMUsage)


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    @classmethod
    @abstractmethod
    def provider_id(cls) -> str:
        ...

    @classmethod
    @abstractmethod
    def label(cls) -> str:
        ...

    @classmethod
    @abstractmethod
    def models(cls) -> list[ModelInfo]:
        ...

    @classmethod
    @abstractmethod
    async def call(
        cls,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        api_key: str,
    ) -> str:
        ...

    @classmethod
    async def call_vision(
        cls,
        model: str,
        system: str,
        user_text: str,
        image_data: str,
        media_type: str,
        max_tokens: int,
        api_key: str,
    ) -> str:
        """Call LLM with an image (base64-encoded) + text prompt."""
        raise NotImplementedError(f"{cls.provider_id()} does not support vision")

    @classmethod
    async def call_vision_conversation(
        cls,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int,
        api_key: str,
    ) -> str:
        """Multi-turn vision call with message history.

        Messages use a provider-neutral format:
        - User with image: {"role": "user", "content": [
              {"type": "image", "data": "<b64>", "media_type": "image/jpeg"},
              {"type": "text", "text": "..."}
          ]}
        - User text-only: {"role": "user", "content": "plain text"}
        - Assistant:       {"role": "assistant", "content": "response text"}
        """
        raise NotImplementedError(
            f"{cls.provider_id()} does not support vision conversation"
        )

    @classmethod
    def api_key_pattern(cls) -> str:
        return ""

    @classmethod
    def api_key_placeholder(cls) -> str:
        return "Enter API key..."
