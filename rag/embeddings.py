"""CPU sentence-transformer embeddings and safe on-disk embedding caches."""

from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from zipfile import BadZipFile

import numpy as np

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingError(RuntimeError):
    """Raised when local embedding generation or cache access fails."""


@lru_cache(maxsize=2)
def _load_sentence_transformer(model_name: str) -> Any:
    """Load each configured CPU embedding model at most once per process."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingError(
            "sentence-transformers is unavailable. Install the project requirements to index textbooks."
        ) from exc
    try:
        return SentenceTransformer(model_name, device="cpu", local_files_only=True)
    except Exception as exc:
        raise EmbeddingError(
            f"Could not load the local embedding model '{model_name}' from this computer: {exc}. "
            "The application does not download embedding models automatically."
        ) from exc


class SentenceTransformerEmbeddings:
    """Lazy, CPU-only embedding adapter."""

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name must be a non-empty string.")
        self.model_name = model_name.strip()

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("texts must contain at least one non-empty string.")
        model = _load_sentence_transformer(self.model_name)
        try:
            vectors = np.asarray(
                model.encode(
                    texts,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            )
        except Exception as exc:
            raise EmbeddingError(f"Local embedding generation failed: {exc}") from exc
        if vectors.ndim != 2 or vectors.shape[0] != len(texts):
            raise EmbeddingError("Embedding model returned an unexpected vector shape.")
        if vectors.shape[1] == 0 or not np.isfinite(vectors).all():
            raise EmbeddingError("Embedding model returned empty or non-finite vectors.")
        return vectors


class EmbeddingCache:
    """Persist chunk metadata and vectors using pickle-free NumPy archives."""

    def __init__(self, cache_directory: str | Path) -> None:
        self.cache_directory = Path(cache_directory)

    def _path(self, cache_key: str) -> Path:
        if not cache_key or any(character not in "0123456789abcdef" for character in cache_key):
            raise ValueError("cache_key must be a lowercase hexadecimal digest.")
        return self.cache_directory / f"{cache_key}.npz"

    def load(self, cache_key: str) -> tuple[dict[str, Any], np.ndarray] | None:
        path = self._path(cache_key)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as archive:
                metadata = json.loads(str(archive["metadata"].item()))
                vectors = np.asarray(archive["embeddings"], dtype=np.float32)
        except (OSError, ValueError, KeyError, json.JSONDecodeError, BadZipFile) as exc:
            raise EmbeddingError(f"Embedding cache is unreadable at {path}: {exc}") from exc
        if not isinstance(metadata, dict) or vectors.ndim != 2:
            raise EmbeddingError(f"Embedding cache has invalid data at {path}.")
        chunks = metadata.get("chunks")
        if (
            not isinstance(chunks, list)
            or vectors.shape[0] != len(chunks)
            or vectors.shape[0] == 0
            or vectors.shape[1] == 0
            or not np.isfinite(vectors).all()
        ):
            raise EmbeddingError(f"Embedding cache has inconsistent vectors at {path}.")
        return metadata, vectors

    def save(self, cache_key: str, metadata: dict[str, Any], embeddings: np.ndarray) -> Path:
        path = self._path(cache_key)
        vectors = np.asarray(embeddings, dtype=np.float32)
        chunks = metadata.get("chunks")
        if vectors.ndim != 2 or not vectors.shape[0] or not vectors.shape[1]:
            raise ValueError("embeddings must be a non-empty 2D matrix.")
        if not isinstance(chunks, list) or len(chunks) != vectors.shape[0]:
            raise ValueError("metadata chunks must match the number of embedding rows.")
        if not np.isfinite(vectors).all():
            raise ValueError("embeddings must contain only finite values.")

        self.cache_directory.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".npz",
                prefix=f"{cache_key}.",
                dir=self.cache_directory,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                np.savez_compressed(
                    temporary_file,
                    metadata=np.asarray(json.dumps(metadata, ensure_ascii=False)),
                    embeddings=vectors,
                )
            os.replace(temporary_path, path)
        except (OSError, TypeError, ValueError) as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise EmbeddingError(f"Could not write embedding cache at {path}: {exc}") from exc
        return path
