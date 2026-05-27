"""Reciprocal Rank Fusion (RRF) for hybrid search result merging."""
from __future__ import annotations

from .bm25 import SearchResult


def reciprocal_rank_fusion(
    *result_lists: list[SearchResult],
    k: int = 60,
    top_k: int = 10,
) -> list[SearchResult]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion.

    Formula: score(doc) = sum(1 / (k + rank_i)) for each list where doc appears.
    Standard k=60 balances contribution from highly-ranked and lower-ranked items.

    Deduplication is by text content — if the same text appears in multiple
    lists, their RRF scores are summed (hybrid boost).
    """
    # Accumulate RRF scores by text
    scored: dict[str, float] = {}
    best_result: dict[str, SearchResult] = {}

    for result_list in result_lists:
        for result in result_list:
            text_key = result.text.strip()
            if not text_key:
                continue
            rrf_score = 1.0 / (k + result.rank)
            scored[text_key] = scored.get(text_key, 0.0) + rrf_score

            # Keep the result with more metadata
            if text_key not in best_result or len(result.metadata) > len(best_result[text_key].metadata):
                best_result[text_key] = result

    # Sort by RRF score descending
    ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)[:top_k]

    results: list[SearchResult] = []
    for rank, (text_key, rrf_score) in enumerate(ranked, 1):
        original = best_result[text_key]
        results.append(SearchResult(
            text=original.text,
            score=rrf_score,
            source=f"rrf({original.source})",
            rank=rank,
            metadata=original.metadata,
        ))

    return results
