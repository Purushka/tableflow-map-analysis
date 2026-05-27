"""Anthropic Claude provider."""
from .base import LLMProvider, ModelInfo, LLMResponse, LLMUsage


def _extract_usage(response) -> LLMUsage:
    """Extract token usage from an Anthropic response object."""
    if hasattr(response, 'usage') and response.usage:
        return LLMUsage(
            input_tokens=getattr(response.usage, 'input_tokens', 0) or 0,
            output_tokens=getattr(response.usage, 'output_tokens', 0) or 0,
        )
    return LLMUsage()


class AnthropicProvider(LLMProvider):
    @classmethod
    def provider_id(cls) -> str:
        return "anthropic"

    @classmethod
    def label(cls) -> str:
        return "Anthropic"

    @classmethod
    def models(cls) -> list[ModelInfo]:
        return [
            ModelInfo("claude-sonnet-4-20250514", "Claude Sonnet 4", "anthropic", 200000, 8192),
            ModelInfo("claude-haiku-4-5-20251001", "Claude Haiku 4.5", "anthropic", 200000, 8192),
        ]

    @classmethod
    async def call(cls, model, system, user, max_tokens, api_key) -> str:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text.strip()

    @classmethod
    async def call_vision(cls, model, system, user_text, image_data, media_type, max_tokens, api_key) -> LLMResponse:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": user_text},
            ]}],
        )
        return LLMResponse(
            text=response.content[0].text.strip(),
            usage=_extract_usage(response),
        )

    @classmethod
    async def call_vision_conversation(cls, model, system, messages, max_tokens, api_key) -> LLMResponse:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)

        def _convert_content(content):
            """Convert provider-neutral content to Anthropic format."""
            if isinstance(content, str):
                return content
            converted = []
            for block in content:
                if block["type"] == "image":
                    converted.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": block["media_type"],
                            "data": block["data"],
                        },
                    })
                elif block["type"] == "text":
                    converted.append({"type": "text", "text": block["text"]})
            return converted

        anthropic_messages = [
            {"role": msg["role"], "content": _convert_content(msg["content"])}
            for msg in messages
        ]
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=anthropic_messages,
        )
        return LLMResponse(
            text=response.content[0].text.strip(),
            usage=_extract_usage(response),
        )

    @classmethod
    def api_key_pattern(cls) -> str:
        return "sk-ant-"

    @classmethod
    def api_key_placeholder(cls) -> str:
        return "sk-ant-..."
