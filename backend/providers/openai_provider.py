"""OpenAI provider."""
import asyncio
from .base import LLMProvider, ModelInfo, LLMResponse, LLMUsage


def _extract_usage(response) -> LLMUsage:
    """Extract token usage from an OpenAI response object."""
    if hasattr(response, 'usage') and response.usage:
        return LLMUsage(
            input_tokens=getattr(response.usage, 'prompt_tokens', 0) or 0,
            output_tokens=getattr(response.usage, 'completion_tokens', 0) or 0,
        )
    return LLMUsage()


class OpenAIProvider(LLMProvider):
    @classmethod
    def provider_id(cls) -> str:
        return "openai"

    @classmethod
    def label(cls) -> str:
        return "OpenAI"

    @classmethod
    def models(cls) -> list[ModelInfo]:
        return [
            ModelInfo("gpt-4o", "GPT-4o", "openai", 128000, 16384),
            ModelInfo("gpt-4o-mini", "GPT-4o Mini", "openai", 128000, 16384),
            ModelInfo("gpt-4.1", "GPT-4.1", "openai", 1000000, 32768),
            ModelInfo("gpt-4.1-mini", "GPT-4.1 Mini", "openai", 1000000, 32768),
        ]

    @classmethod
    async def call(cls, model, system, user, max_tokens, api_key) -> str:
        from openai import OpenAI

        def _sync():
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return response.choices[0].message.content.strip()

        return await asyncio.to_thread(_sync)

    @classmethod
    async def call_vision(cls, model, system, user_text, image_data, media_type, max_tokens, api_key) -> LLMResponse:
        from openai import OpenAI

        def _sync():
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}},
                    ]},
                ],
            )
            return LLMResponse(
                text=response.choices[0].message.content.strip(),
                usage=_extract_usage(response),
            )

        return await asyncio.to_thread(_sync)

    @classmethod
    async def call_vision_conversation(cls, model, system, messages, max_tokens, api_key) -> LLMResponse:
        from openai import OpenAI

        def _convert_content(content):
            """Convert provider-neutral content to OpenAI format."""
            if isinstance(content, str):
                return content
            converted = []
            for block in content:
                if block["type"] == "image":
                    data_url = f"data:{block['media_type']};base64,{block['data']}"
                    converted.append({
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    })
                elif block["type"] == "text":
                    converted.append({"type": "text", "text": block["text"]})
            return converted

        def _sync():
            client = OpenAI(api_key=api_key)
            openai_messages = [{"role": "system", "content": system}]
            for msg in messages:
                openai_messages.append({
                    "role": msg["role"],
                    "content": _convert_content(msg["content"]),
                })
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=openai_messages,
            )
            return LLMResponse(
                text=response.choices[0].message.content.strip(),
                usage=_extract_usage(response),
            )

        return await asyncio.to_thread(_sync)

    @classmethod
    def api_key_pattern(cls) -> str:
        return "sk-"

    @classmethod
    def api_key_placeholder(cls) -> str:
        return "sk-..."
