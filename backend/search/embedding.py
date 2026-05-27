"""Local vector embedding using sentence-transformers (all-MiniLM-L6-v2)."""
from __future__ import annotations

import numpy as np

_MODEL = None
_MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model():
    """Lazy-load the sentence transformer model (process-level singleton)."""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(_MODEL_NAME)
    return _MODEL


def embed(texts: list[str]) -> np.ndarray:
    """Embed a list of texts into L2-normalized vectors.

    Returns:
        np.ndarray of shape (n, 384) with unit-length rows.
    """
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vectors, dtype=np.float32)


def cosine_similarity(query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between a query vector and document vectors.

    Since vectors are L2-normalized, dot product equals cosine similarity.

    Args:
        query_vec: shape (384,) or (1, 384)
        doc_vecs: shape (n, 384)

    Returns:
        np.ndarray of shape (n,) with similarity scores.
    """
    if query_vec.ndim == 2:
        query_vec = query_vec[0]
    return doc_vecs @ query_vec
