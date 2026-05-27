"""Ollama local LLM provider."""
from .base import LLMProvider, ModelInfo


class OllamaProvider(LLMProvider):
    @classmethod
    def provider_id(cls) -> str:
        return "ollama"

    @classmethod
    def label(cls) -> str:
        return "Ollama (Local)"

    @classmethod
    def models(cls) -> list[ModelInfo]:
        return [
            ModelInfo("llama3.3", "Llama 3.3 70B", "ollama", 128000, 4096),
            ModelInfo("mistral", "Mistral 7B", "ollama", 32000, 4096),
            ModelInfo("qwen2.5", "Qwen 2.5", "ollama", 128000, 4096),
        ]

    @classmethod
    async def call(cls, model, system, user, max_tokens, api_key) -> str:
        import httpx
        base_url = api_key or "http://localhost:11434"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {"num_predict": max_tokens},
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()

    @classmethod
    def api_key_pattern(cls) -> str:
        return "http"

    @classmethod
    def api_key_placeholder(cls) -> str:
        return "http://localhost:11434"
