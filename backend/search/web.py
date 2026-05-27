"""Web search API integration — supports Tavily, Google, Bing, SerpAPI."""
from __future__ import annotations

import httpx

from .bm25 import SearchResult

_TIMEOUT = 15.0


async def web_search(
    query: str,
    provider: str,
    api_key: str,
    top_k: int = 5,
) -> list[SearchResult]:
    """Search the web using the specified provider and return unified results."""
    if not api_key:
        return []

    provider = provider.lower().strip()

    if provider == "tavily":
        return await _tavily(query, api_key, top_k)
    elif provider == "google":
        return await _google(query, api_key, top_k)
    elif provider == "bing":
        return await _bing(query, api_key, top_k)
    elif provider == "serpapi":
        return await _serpapi(query, api_key, top_k)
    else:
        return []


async def _tavily(query: str, api_key: str, top_k: int) -> list[SearchResult]:
    """Tavily Search API — optimized for RAG."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": top_k,
                "include_raw_content": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results: list[SearchResult] = []
    for rank, item in enumerate(data.get("results", [])[:top_k], 1):
        content = item.get("content", "")
        results.append(SearchResult(
            text=content,
            score=item.get("score", 0.0),
            source="web:tavily",
            rank=rank,
            metadata={"url": item.get("url", ""), "title": item.get("title", "")},
        ))
    return results


async def _google(query: str, api_key: str, top_k: int) -> list[SearchResult]:
    """Google Custom Search JSON API. api_key format: 'API_KEY:CX_ID'."""
    parts = api_key.split(":", 1)
    if len(parts) != 2:
        return []
    key, cx = parts

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": key, "cx": cx, "q": query, "num": min(top_k, 10)},
        )
        resp.raise_for_status()
        data = resp.json()

    results: list[SearchResult] = []
    for rank, item in enumerate(data.get("items", [])[:top_k], 1):
        snippet = item.get("snippet", "")
        results.append(SearchResult(
            text=snippet,
            score=1.0 / rank,
            source="web:google",
            rank=rank,
            metadata={"url": item.get("link", ""), "title": item.get("title", "")},
        ))
    return results


async def _bing(query: str, api_key: str, top_k: int) -> list[SearchResult]:
    """Bing Web Search API v7."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": api_key},
            params={"q": query, "count": top_k},
        )
        resp.raise_for_status()
        data = resp.json()

    results: list[SearchResult] = []
    web_pages = data.get("webPages", {}).get("value", [])
    for rank, item in enumerate(web_pages[:top_k], 1):
        snippet = item.get("snippet", "")
        results.append(SearchResult(
            text=snippet,
            score=1.0 / rank,
            source="web:bing",
            rank=rank,
            metadata={"url": item.get("url", ""), "title": item.get("name", "")},
        ))
    return results


async def _serpapi(query: str, api_key: str, top_k: int) -> list[SearchResult]:
    """SerpAPI Google Search."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://serpapi.com/search.json",
            params={"api_key": api_key, "q": query, "num": top_k},
        )
        resp.raise_for_status()
        data = resp.json()

    results: list[SearchResult] = []
    for rank, item in enumerate(data.get("organic_results", [])[:top_k], 1):
        snippet = item.get("snippet", "")
        results.append(SearchResult(
            text=snippet,
            score=1.0 / rank,
            source="web:serpapi",
            rank=rank,
            metadata={"url": item.get("link", ""), "title": item.get("title", "")},
        ))
    return results
