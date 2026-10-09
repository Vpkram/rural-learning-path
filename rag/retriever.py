"""Cosine-similarity search over textbook chunks; does not call any LLM."""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np

from rag.models import RetrievedChunk, RetrievalResult, TextbookIndex

NOT_FOUND_MESSAGE = "This topic was not found in the textbook."


class QueryEmbedder(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


def retrieve(
    query: str,
    index: TextbookIndex,
    *,
    embedder: QueryEmbedder,
    top_k: int = 3,
    similarity_threshold: float = 0.35,
) -> RetrievalResult:
    """Return the best matching chunks that meet the configured threshold."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string.")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer.")
    if (
        isinstance(similarity_threshold, bool)
        or not isinstance(similarity_threshold, (int, float))
        or not math.isfinite(similarity_threshold)
        or not -1.0 <= similarity_threshold <= 1.0
    ):
        raise ValueError("similarity_threshold must be finite and between -1 and 1.")
    if embedder.model_name != index.model_name:
        raise ValueError("Query embedder model must match the textbook index model.")

    matrix = np.asarray(index.embeddings, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] != len(index.chunks) or matrix.shape[1] == 0:
        raise ValueError("Textbook index vectors do not match its chunks.")
    if not np.isfinite(matrix).all():
        raise ValueError("Textbook index contains non-finite vectors.")

    query_vectors = np.asarray(embedder.embed([query.strip()]), dtype=np.float32)
    if (
        query_vectors.ndim != 2
        or query_vectors.shape[0] != 1
        or query_vectors.shape[1] != matrix.shape[1]
        or not np.isfinite(query_vectors).all()
    ):
        raise ValueError("Query embedder returned an incompatible vector.")

    query_vector = query_vectors[0]
    query_norm = float(np.linalg.norm(query_vector))
    vector_norms = np.linalg.norm(matrix, axis=1)
    if query_norm == 0 or np.any(vector_norms == 0):
        raise ValueError("Cosine similarity is undefined for a zero-length embedding.")
    similarities = (matrix @ query_vector) / (vector_norms * query_norm)
    order = np.argsort(-similarities, kind="stable")[:top_k]
    matches = tuple(
        RetrievedChunk(index.chunks[int(position)], float(similarities[position]))
        for position in order
        if float(similarities[position]) >= similarity_threshold
    )
    if not matches:
        return RetrievalResult(found=False, matches=(), message=NOT_FOUND_MESSAGE)
    return RetrievalResult(found=True, matches=matches)
