"""Google Gemini provider."""
from .base import LLMProvider, ModelInfo, LLMResponse, LLMUsage


class GeminiRecitationError(Exception):
    """Raised when Gemini blocks output due to copyright/recitation filter."""
    pass


def _extract_text(response):
    """Extract text from Gemini response, handling recitation blocks."""
    if not response.candidates:
        raise ValueError(
            f"Gemini returned no candidates "
            f"(prompt_feedback={response.prompt_feedback})"
        )
    candidate = response.candidates[0]
    # finish_reason 4 = RECITATION (copyright block)
    fr = getattr(candidate, "finish_reason", None)
    if fr == 4:
        raise GeminiRecitationError(
            "Gemini blocked output: content filter detected "
            "potential copyrighted material (finish_reason=RECITATION). "
            "This is a model-level restriction, not a code error."
        )
    return response.text.strip()


def _extract_usage(response) -> LLMUsage:
    """Extract token usage from a Gemini response object."""
    meta = getattr(response, 'usage_metadata', None)
    if meta:
        return LLMUsage(
            input_tokens=getattr(meta, 'prompt_token_count', 0) or 0,
            output_tokens=getattr(meta, 'candidates_token_count', 0) or 0,
        )
    return LLMUsage()


def _extract_text_and_usage(response) -> LLMResponse:
    """Extract text and usage from a Gemini response."""
    return LLMResponse(
        text=_extract_text(response),
        usage=_extract_usage(response),
    )


class GoogleProvider(LLMProvider):
    @classmethod
    def provider_id(cls) -> str:
        return "google"

    @classmethod
    def label(cls) -> str:
        return "Google Gemini"

    @classmethod
    def models(cls) -> list[ModelInfo]:
        return [
            ModelInfo("gemini-2.5-flash", "Gemini 2.5 Flash", "google", 1000000, 65536),
            ModelInfo("gemini-2.5-pro", "Gemini 2.5 Pro", "google", 1000000, 65536),
        ]

    @classmethod
    async def call(cls, model, system, user, max_tokens, api_key) -> str:
        import asyncio
        import google.generativeai as genai

        def _sync_call():
            genai.configure(api_key=api_key)
            gen_model = genai.GenerativeModel(model, system_instruction=system)
            response = gen_model.generate_content(
                user,
                generation_config=genai.GenerationConfig(max_output_tokens=max_tokens),
            )
            return _extract_text(response)

        return await asyncio.to_thread(_sync_call)

    @classmethod
    async def call_vision(cls, model, system, user_text, image_data, media_type, max_tokens, api_key) -> LLMResponse:
        import asyncio
        import base64
        import google.generativeai as genai

        def _sync_call():
            genai.configure(api_key=api_key)
            gen_model = genai.GenerativeModel(model, system_instruction=system)
            image_bytes = base64.b64decode(image_data)
            image_part = {"mime_type": media_type, "data": image_bytes}
            response = gen_model.generate_content(
                [user_text, image_part],
                generation_config=genai.GenerationConfig(max_output_tokens=max_tokens),
            )
            return _extract_text_and_usage(response)

        return await asyncio.to_thread(_sync_call)

    @classmethod
    async def call_vision_conversation(cls, model, system, messages, max_tokens, api_key) -> LLMResponse:
        import asyncio
        import base64
        import google.generativeai as genai

        def _sync_call():
            genai.configure(api_key=api_key)
            gen_model = genai.GenerativeModel(model, system_instruction=system)

            contents = []
            for msg in messages:
                role = "model" if msg["role"] == "assistant" else "user"
                content = msg["content"]
                if isinstance(content, str):
                    parts = [content]
                else:
                    parts = []
                    for block in content:
                        if block["type"] == "image":
                            parts.append({
                                "mime_type": block["media_type"],
                                "data": base64.b64decode(block["data"]),
                            })
                        elif block["type"] == "text":
                            parts.append(block["text"])
                contents.append({"role": role, "parts": parts})

            response = gen_model.generate_content(
                contents,
                generation_config=genai.GenerationConfig(max_output_tokens=max_tokens),
            )
            return _extract_text_and_usage(response)

        return await asyncio.to_thread(_sync_call)

    @classmethod
    def api_key_pattern(cls) -> str:
        return "AIza"

    @classmethod
    def api_key_placeholder(cls) -> str:
        return "AIza..."
