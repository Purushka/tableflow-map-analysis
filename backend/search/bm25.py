"""BM25 keyword search over DataFrame rows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from rank_bm25 import BM25Okapi


@dataclass
class SearchResult:
    """Unified search result used by all search backends."""
    text: str
    score: float
    source: str  # "bm25", "vector", "web:<provider>"
    rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def bm25_search(
    query: str,
    df: pd.DataFrame,
    columns: list[str],
    top_k: int = 10,
) -> list[SearchResult]:
    """Run BM25 keyword search over specified DataFrame columns.

    Concatenates the specified columns of each row into a document,
    tokenizes by whitespace, and returns the top-k results.
    """
    if df.empty or not columns:
        return []

    # Build corpus: one document per row
    valid_cols = [c for c in columns if c in df.columns]
    if not valid_cols:
        return []

    corpus_texts: list[str] = []
    for _, row in df.iterrows():
        parts = [str(row[c]) for c in valid_cols if pd.notna(row[c])]
        corpus_texts.append(" ".join(parts))

    # Tokenize
    tokenized_corpus = [doc.lower().split() for doc in corpus_texts]
    tokenized_query = query.lower().split()

    if not tokenized_query:
        return []

    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(tokenized_query)

    # Top-k by score
    ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

    results: list[SearchResult] = []
    for rank, idx in enumerate(ranked_indices):
        if scores[idx] <= 0:
            continue
        results.append(SearchResult(
            text=corpus_texts[idx],
            score=float(scores[idx]),
            source="bm25",
            rank=rank + 1,
            metadata={"row_index": idx},
        ))

    return results
