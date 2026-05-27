"""Vector semantic search over DataFrame rows."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .bm25 import SearchResult
from .embedding import embed, cosine_similarity


def vector_search(
    query: str,
    df: pd.DataFrame,
    columns: list[str],
    top_k: int = 10,
    doc_embeddings: np.ndarray | None = None,
    corpus_texts: list[str] | None = None,
) -> tuple[list[SearchResult], np.ndarray, list[str]]:
    """Run vector semantic search over specified DataFrame columns.

    Returns:
        (results, doc_embeddings, corpus_texts) — the embeddings and corpus
        are returned so callers can cache them across multiple queries.
    """
    if df.empty or not columns:
        return [], np.array([]), []

    valid_cols = [c for c in columns if c in df.columns]
    if not valid_cols:
        return [], np.array([]), []

    # Build corpus if not cached
    if corpus_texts is None:
        corpus_texts = []
        for _, row in df.iterrows():
            parts = [str(row[c]) for c in valid_cols if pd.notna(row[c])]
            corpus_texts.append(" ".join(parts))

    # Compute document embeddings if not cached
    if doc_embeddings is None:
        doc_embeddings = embed(corpus_texts)

    # Embed the query (single short string)
    query_vec = embed([query])

    # Cosine similarity
    scores = cosine_similarity(query_vec, doc_embeddings)

    # Top-k
    ranked_indices = np.argsort(scores)[::-1][:top_k]

    results: list[SearchResult] = []
    for rank, idx in enumerate(ranked_indices):
        idx = int(idx)
        if scores[idx] <= 0:
            continue
        results.append(SearchResult(
            text=corpus_texts[idx],
            score=float(scores[idx]),
            source="vector",
            rank=rank + 1,
            metadata={"row_index": idx},
        ))

    return results, doc_embeddings, corpus_texts
