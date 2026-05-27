"""SCNet (国家超算互联网平台) provider — OpenAI-compatible API."""
import asyncio
from .base import LLMProvider, ModelInfo, LLMResponse, LLMUsage

_BASE_URL = "https://api.scnet.cn/api/llm/v1"


def _extract_usage(response) -> LLMUsage:
    """Extract token usage from an OpenAI-compatible response object."""
    if hasattr(response, 'usage') and response.usage:
        return LLMUsage(
            input_tokens=getattr(response.usage, 'prompt_tokens', 0) or 0,
            output_tokens=getattr(response.usage, 'completion_tokens', 0) or 0,
        )
    return LLMUsage()


class SCNetProvider(LLMProvider):
    @classmethod
    def provider_id(cls) -> str:
        return "scnet"

    @classmethod
    def label(cls) -> str:
        return "SCNet 超算互联网"

    @classmethod
    def models(cls) -> list[ModelInfo]:
        return [
            # ── Flagship ──
            ModelInfo("DeepSeek-V3.2", "DeepSeek V3.2", "scnet", 128000, 16384),
            ModelInfo("MiniMax-M2.5", "MiniMax M2.5", "scnet", 128000, 16384),
            ModelInfo("MiniMax-M2", "MiniMax M2", "scnet", 128000, 16384),
            # ── Reasoning ──
            ModelInfo("DeepSeek-R1-0528", "DeepSeek R1 0528", "scnet", 128000, 16384),
            ModelInfo("Qwen3-235B-A22B-Thinking-2507", "Qwen3 235B Thinking", "scnet", 32000, 16384),
            ModelInfo("Qwen3-235B-A22B", "Qwen3 235B", "scnet", 32000, 16384),
            ModelInfo("QwQ-32B", "QwQ 32B", "scnet", 32000, 16384),
            # ── Mid-size ──
            ModelInfo("Qwen3-30B-A3B-Instruct-2507", "Qwen3 30B Instruct", "scnet", 256000, 16384),
            ModelInfo("Qwen3-30B-A3B", "Qwen3 30B", "scnet", 128000, 16384),
            ModelInfo("DeepSeek-R1-Distill-Qwen-32B", "DeepSeek R1 Distill 32B", "scnet", 32000, 16384),
            ModelInfo("DeepSeek-R1-Distill-Llama-70B", "DeepSeek R1 Distill 70B", "scnet", 32000, 16384),
            # ── Small ──
            ModelInfo("DeepSeek-R1-Distill-Qwen-7B", "DeepSeek R1 Distill 7B", "scnet", 32000, 16384),
            # ── Coding ──
            ModelInfo("Qwen3-Coder-480B-A35B-Instruct", "Qwen3 Coder 480B", "scnet", 32000, 16384),
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
            return response.choices[0].message.content.strip()

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
                text=response.choices[0].message.content.strip(),
                usage=_extract_usage(response),
            )

        return await asyncio.to_thread(_sync)

    @classmethod
    def api_key_pattern(cls) -> str:
        return "sk-"

    @classmethod
    def api_key_placeholder(cls) -> str:
        return "sk-MzMy..."
