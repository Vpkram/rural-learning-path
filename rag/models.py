"""Small immutable data structures shared by the retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class DocumentPage:
    source: str
    page_number: int | None
    text: str


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    source: str
    page_number: int | None
    text: str


@dataclass(frozen=True)
class TextbookIndex:
    source: str
    model_name: str
    cache_key: str
    chunks: tuple[TextChunk, ...]
    embeddings: NDArray[np.float32]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: TextChunk
    similarity: float


@dataclass(frozen=True)
class RetrievalResult:
    found: bool
    matches: tuple[RetrievedChunk, ...]
    message: str | None = None
