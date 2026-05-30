"""OpenRouter provider — aggregated access to hundreds of models via OpenAI-compatible API."""
import asyncio
from .base import LLMProvider, ModelInfo, LLMResponse, LLMUsage

_BASE_URL = "https://openrouter.ai/api/v1"


def _extract_usage(response) -> LLMUsage:
    """Extract token usage from an OpenAI-compatible response object."""
    if hasattr(response, 'usage') and response.usage:
        return LLMUsage(
            input_tokens=getattr(response.usage, 'prompt_tokens', 0) or 0,
            output_tokens=getattr(response.usage, 'completion_tokens', 0) or 0,
        )
    return LLMUsage()


def _extract_text(response) -> str:
    """Extract text from response, handling thinking models where content may be null."""
    choice = response.choices[0]
    msg = choice.message
    # Primary content
    text = getattr(msg, 'content', None)
    if text:
        return text.strip()
    # Thinking models: content in reasoning_content or tool calls
    reasoning = getattr(msg, 'reasoning_content', None)
    if reasoning:
        return reasoning.strip()
    # Some providers nest it differently
    if hasattr(msg, 'reasoning') and msg.reasoning:
        return msg.reasoning.strip()
    raise ValueError(
        f"OpenRouter returned empty content. "
        f"finish_reason={getattr(choice, 'finish_reason', '?')}, "
        f"model={getattr(response, 'model', '?')}"
    )


class OpenRouterProvider(LLMProvider):
    @classmethod
    def provider_id(cls) -> str:
        return "openrouter"

    @classmethod
    def label(cls) -> str:
        return "OpenRouter"

    @classmethod
    def models(cls) -> list[ModelInfo]:
        return [
            # ── Vision / Multimodal (for map analysis) ──
            ModelInfo("qwen/qwen3-vl-235b-a22b-instruct", "Qwen3 VL 235B Instruct", "openrouter", 128000, 32768),
            ModelInfo("qwen/qwen3-vl-235b-a22b-thinking", "Qwen3 VL 235B Thinking", "openrouter", 128000, 32768),
            ModelInfo("qwen/qwen2.5-vl-72b-instruct", "Qwen2.5 VL 72B Instruct", "openrouter", 128000, 16384),
            ModelInfo("qwen/qwen2.5-vl-32b-instruct", "Qwen2.5 VL 32B Instruct", "openrouter", 128000, 16384),
            ModelInfo("qwen/qwen3-vl-8b-instruct", "Qwen3 VL 8B Instruct", "openrouter", 128000, 16384),
            ModelInfo("qwen/qwen3-vl-32b-instruct", "Qwen3 VL 32B Instruct", "openrouter", 128000, 32768),
            ModelInfo("qwen/qwen3-vl-30b-a3b-instruct", "Qwen3 VL 30B A3B Instruct", "openrouter", 128000, 16384),
            # ── Cross-family vision (use as critic for independent verification) ──
            ModelInfo("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5 (via OR)", "openrouter", 200000, 8192),
            ModelInfo("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet (via OR)", "openrouter", 200000, 8192),
            ModelInfo("anthropic/claude-3-haiku", "Claude 3 Haiku (via OR)", "openrouter", 200000, 4096),
            ModelInfo("openai/gpt-4o", "GPT-4o (via OR)", "openrouter", 128000, 16384),
            ModelInfo("openai/gpt-4o-mini", "GPT-4o mini (via OR)", "openrouter", 128000, 16384),
            # ── Cheap critic / extractor candidates (Gemini & Llama) ──
            ModelInfo("google/gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite (via OR)", "openrouter", 1000000, 65536),
            ModelInfo("google/gemini-2.0-flash-001", "Gemini 2.0 Flash (via OR)", "openrouter", 1000000, 65536),
            ModelInfo("google/gemini-2.0-flash-lite-001", "Gemini 2.0 Flash Lite (via OR)", "openrouter", 1000000, 65536),
            ModelInfo("meta-llama/llama-3.2-11b-vision-instruct", "Llama 3.2 11B Vision (via OR)", "openrouter", 128000, 8192),
            # ── Text-only flagship ──
            ModelInfo("deepseek/deepseek-r1", "DeepSeek R1", "openrouter", 128000, 16384),
            ModelInfo("deepseek/deepseek-chat-v3-0324", "DeepSeek V3", "openrouter", 128000, 16384),
            ModelInfo("qwen/qwen3-235b-a22b", "Qwen3 235B", "openrouter", 128000, 16384),
        ]

    @classmethod
    async def call(cls, model, system, user, max_tokens, api_key) -> str:
        from openai import OpenAI

        def _sync():
            client = OpenAI(api_key=api_key, base_url=_BASE_URL, timeout=600)
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return _extract_text(response)

        return await asyncio.to_thread(_sync)

    @classmethod
    async def call_vision(cls, model, system, user_text, image_data, media_type, max_tokens, api_key) -> LLMResponse:
        from openai import OpenAI

        def _sync():
            client = OpenAI(api_key=api_key, base_url=_BASE_URL, timeout=600)
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
                text=_extract_text(response),
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
            client = OpenAI(api_key=api_key, base_url=_BASE_URL, timeout=600)
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
                text=_extract_text(response),
                usage=_extract_usage(response),
            )

        return await asyncio.to_thread(_sync)

    @classmethod
    def api_key_pattern(cls) -> str:
        return "sk-or-"

    @classmethod
    def api_key_placeholder(cls) -> str:
        return "sk-or-v1-..."
