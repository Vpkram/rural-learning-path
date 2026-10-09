"""Build or load a cached textbook index; retrieval remains a separate step."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Event
from typing import Protocol

import numpy as np

from rag.chunker import chunk_pages
from rag.cleaner import clean_pages
from rag.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingCache,
    SentenceTransformerEmbeddings,
)
from rag.loader import document_page_count, iter_document_pages
from rag.models import TextbookIndex, TextChunk
from rag.retriever import NOT_FOUND_MESSAGE, retrieve


class IndexingCancelled(RuntimeError):
    """Raised when a learner cancels a textbook indexing job."""


class IndexingProgress(Protocol):
    def __call__(
        self,
        *,
        stage: str,
        pages_processed: int,
        total_pages: int,
        chunks_embedded: int,
        total_chunks: int,
    ) -> None: ...


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as textbook:
            for block in iter(lambda: textbook.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise OSError(f"Could not read textbook {path}: {exc}") from exc
    return digest.hexdigest()


def textbook_cache_key(
    path: str | Path,
    *,
    chunk_size: int = 900,
    overlap: int = 120,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    start_page: int = 1,
    end_page: int | None = None,
) -> str:
    """Compute the stable cache key used to tell whether this textbook is indexed."""
    document_path = Path(path)
    if not document_path.is_file():
        raise ValueError(f"Textbook does not exist or is not a file: {document_path}")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer.")
    if isinstance(overlap, bool) or not isinstance(overlap, int) or overlap < 0:
        raise ValueError("overlap must be a non-negative integer.")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size.")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a non-empty string.")
    if isinstance(start_page, bool) or not isinstance(start_page, int) or start_page < 1:
        raise ValueError("start_page must be a positive integer.")
    if end_page is not None and (
        isinstance(end_page, bool) or not isinstance(end_page, int) or end_page < start_page
    ):
        raise ValueError("end_page must be an integer greater than or equal to start_page.")

    identity = json.dumps(
        {
            "content": _file_digest(document_path),
            "source": str(document_path.resolve()),
            "model": model_name.strip(),
            "chunk_size": chunk_size,
            "overlap": overlap,
            "start_page": start_page,
            "end_page": end_page,
            "format": 1,
        },
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _text_chunk(item: dict[str, object]) -> TextChunk:
    chunk_id = item.get("chunk_id")
    source = item.get("source")
    page_number = item.get("page_number")
    text = item.get("text")
    if (
        not isinstance(chunk_id, str)
        or not isinstance(source, str)
        or not isinstance(text, str)
        or (page_number is not None and not isinstance(page_number, int))
    ):
        raise ValueError("Cached chunk metadata is malformed.")
    return TextChunk(chunk_id, source, page_number, text)


def index_textbook(
    path: str | Path,
    *,
    chunk_size: int = 900,
    overlap: int = 120,
    cache_directory: str | Path = Path("data") / "embeddings",
    embedder: Embedder | None = None,
    start_page: int = 1,
    end_page: int | None = None,
    batch_size: int = 32,
    progress_callback: IndexingProgress | None = None,
    cancel_event: Event | None = None,
) -> TextbookIndex:
    """Index a selected page range in cancellable embedding batches.

    Progress callbacks run on the calling thread. Streamlit can call this from
    a worker thread and poll its own queue to keep its page interactive.
    """
    document_path = Path(path)
    if not document_path.is_file():
        raise ValueError(f"Textbook does not exist or is not a file: {document_path}")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer.")
    if isinstance(overlap, bool) or not isinstance(overlap, int) or overlap < 0:
        raise ValueError("overlap must be a non-negative integer.")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size.")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer.")
    if isinstance(start_page, bool) or not isinstance(start_page, int) or start_page < 1:
        raise ValueError("start_page must be a positive integer.")
    if end_page is not None and (
        isinstance(end_page, bool) or not isinstance(end_page, int) or end_page < start_page
    ):
        raise ValueError("end_page must be an integer greater than or equal to start_page.")

    active_embedder = (
        embedder if embedder is not None else SentenceTransformerEmbeddings(DEFAULT_EMBEDDING_MODEL)
    )
    if not isinstance(active_embedder.model_name, str) or not active_embedder.model_name.strip():
        raise ValueError("Embedder must provide a non-empty model_name.")

    cache_key = textbook_cache_key(
        document_path,
        chunk_size=chunk_size,
        overlap=overlap,
        model_name=active_embedder.model_name,
        start_page=start_page,
        end_page=end_page,
    )
    cache = EmbeddingCache(cache_directory)
    cached = cache.load(cache_key)
    if cached is not None:
        metadata, vectors = cached
        try:
            chunks = tuple(_text_chunk(item) for item in metadata["chunks"])
            source = metadata["source"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Cached textbook metadata is malformed: {exc}") from exc
        if (
            not isinstance(source, str)
            or metadata.get("model_name") != active_embedder.model_name
            or len(chunks) != vectors.shape[0]
        ):
            raise ValueError("Cached textbook metadata does not match the embedding index.")
        if not chunks:
            raise ValueError("Cached textbook index contains no text chunks.")
        if progress_callback is not None:
            document_total = document_page_count(document_path)
            total_pages = min(end_page or document_total, document_total) - start_page + 1
            progress_callback(
                stage="cached",
                pages_processed=total_pages,
                total_pages=total_pages,
                chunks_embedded=len(chunks),
                total_chunks=len(chunks),
            )
        return TextbookIndex(source, active_embedder.model_name, cache_key, chunks, vectors)

    document_total = document_page_count(document_path)
    first = start_page
    last = min(end_page or document_total, document_total)
    if first > document_total:
        raise ValueError("start_page is past the end of the textbook.")
    total_pages = last - first + 1
    extracted_pages = []
    for processed, page in enumerate(
        iter_document_pages(document_path, start_page=first, end_page=last),
        start=1,
    ):
        if cancel_event is not None and cancel_event.is_set():
            raise IndexingCancelled("Textbook indexing was cancelled.")
        extracted_pages.append(page)
        if progress_callback is not None:
            progress_callback(
                stage="extract",
                pages_processed=processed,
                total_pages=total_pages,
                chunks_embedded=0,
                total_chunks=0,
            )
    pages = clean_pages(extracted_pages)
    chunks = tuple(chunk_pages(pages, chunk_size=chunk_size, overlap=overlap))
    if not chunks:
        raise ValueError(f"No readable text was found in {document_path.name}.")
    vector_batches: list[np.ndarray] = []
    embedded_count = 0
    for batch_start in range(0, len(chunks), batch_size):
        if cancel_event is not None and cancel_event.is_set():
            raise IndexingCancelled("Textbook indexing was cancelled.")
        batch_chunks = chunks[batch_start : batch_start + batch_size]
        batch_vectors = np.asarray(
            active_embedder.embed([chunk.text for chunk in batch_chunks]),
            dtype=np.float32,
        )
        if (
            batch_vectors.ndim != 2
            or batch_vectors.shape[0] != len(batch_chunks)
            or batch_vectors.shape[1] == 0
            or not np.isfinite(batch_vectors).all()
        ):
            raise ValueError("Embedder returned vectors that do not match the textbook chunks.")
        vector_batches.append(batch_vectors)
        embedded_count += len(batch_chunks)
        if progress_callback is not None:
            progress_callback(
                stage="embed",
                pages_processed=total_pages,
                total_pages=total_pages,
                chunks_embedded=embedded_count,
                total_chunks=len(chunks),
            )
    vectors = np.concatenate(vector_batches, axis=0)
    if (
        vectors.ndim != 2
        or vectors.shape[0] != len(chunks)
        or vectors.shape[1] == 0
        or not np.isfinite(vectors).all()
    ):
        raise ValueError("Embedder returned vectors that do not match the textbook chunks.")

    source = document_path.name
    chunk_metadata = [
        {
            "chunk_id": chunk.chunk_id,
            "source": chunk.source,
            "page_number": chunk.page_number,
            "text": chunk.text,
        }
        for chunk in chunks
    ]
    cache.save(
        cache_key,
        {"source": source, "model_name": active_embedder.model_name, "chunks": chunk_metadata},
        vectors,
    )
    return TextbookIndex(source, active_embedder.model_name, cache_key, chunks, vectors)


def main() -> None:
    """Index one local document and display retrieved context for a query."""
    import argparse

    parser = argparse.ArgumentParser(description="Index a local textbook and search its text.")
    parser.add_argument("textbook", type=Path, help="Path to a PDF or DOCX file")
    parser.add_argument("--query", required=True, help="Question or topic to search for")
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--chunk-size", type=int, default=900)
    parser.add_argument("--overlap", type=int, default=120)
    parser.add_argument("--cache", type=Path, default=Path("data") / "embeddings")
    args = parser.parse_args()

    embedder = SentenceTransformerEmbeddings(args.model)
    index = index_textbook(
        args.textbook,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        cache_directory=args.cache,
        embedder=embedder,
    )
    result = retrieve(
        args.query,
        index,
        embedder=embedder,
        top_k=args.top_k,
        similarity_threshold=args.threshold,
    )
    if not result.found:
        print(NOT_FOUND_MESSAGE)
        return
    for match in result.matches:
        page = (
            f"page {match.chunk.page_number}"
            if match.chunk.page_number is not None
            else "page unavailable"
        )
        print(f"[{match.similarity:.3f}] {match.chunk.source}, {page}, {match.chunk.chunk_id}")
        print(match.chunk.text)
        print()


if __name__ == "__main__":
    main()
