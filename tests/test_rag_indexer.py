from types import SimpleNamespace
from threading import Event

import numpy as np
import pytest

from rag.indexer import IndexingCancelled, index_textbook


class CountingEmbedder:
    model_name = "deterministic-test-model"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return np.array([[1.0, float(index + 1)] for index, _text in enumerate(texts)], dtype=np.float32)


def test_indexer_caches_textbook_embeddings_by_content_and_settings(monkeypatch, tmp_path):
    textbook = tmp_path / "book.pdf"
    textbook.write_bytes(b"stable test content")
    monkeypatch.setattr(
        "rag.indexer.document_page_count",
        lambda path: 1,
    )
    monkeypatch.setattr(
        "rag.indexer.iter_document_pages",
        lambda path, **kwargs: iter(
            [SimpleNamespace(source=path.name, page_number=6, text="retrieval text " * 10)]
        ),
    )
    embedder = CountingEmbedder()

    first = index_textbook(
        textbook,
        chunk_size=30,
        overlap=5,
        cache_directory=tmp_path / "cache",
        embedder=embedder,
    )
    second = index_textbook(
        textbook,
        chunk_size=30,
        overlap=5,
        cache_directory=tmp_path / "cache",
        embedder=embedder,
    )

    assert first.cache_key == second.cache_key
    assert len(first.chunks) == len(second.chunks)
    assert embedder.calls == 1
    assert all(chunk.page_number == 6 for chunk in second.chunks)


def test_indexer_uses_new_cache_entry_when_textbook_changes(monkeypatch, tmp_path):
    textbook = tmp_path / "book.pdf"
    textbook.write_bytes(b"version one")
    monkeypatch.setattr("rag.indexer.document_page_count", lambda path: 1)
    monkeypatch.setattr(
        "rag.indexer.iter_document_pages",
        lambda path, **kwargs: iter(
            [SimpleNamespace(source=path.name, page_number=1, text=path.read_bytes().decode())]
        ),
    )
    embedder = CountingEmbedder()
    first = index_textbook(textbook, cache_directory=tmp_path / "cache", embedder=embedder)
    textbook.write_bytes(b"version two")
    second = index_textbook(textbook, cache_directory=tmp_path / "cache", embedder=embedder)

    assert first.cache_key != second.cache_key
    assert embedder.calls == 2


def test_indexer_reports_pages_and_embedding_batches(monkeypatch, tmp_path):
    textbook = tmp_path / "book.pdf"
    textbook.write_bytes(b"progress test")
    monkeypatch.setattr("rag.indexer.document_page_count", lambda path: 2)
    monkeypatch.setattr(
        "rag.indexer.iter_document_pages",
        lambda path, **kwargs: iter(
            [
                SimpleNamespace(source=path.name, page_number=1, text="first page text " * 5),
                SimpleNamespace(source=path.name, page_number=2, text="second page text " * 5),
            ]
        ),
    )
    events = []
    index_textbook(
        textbook,
        chunk_size=20,
        overlap=0,
        batch_size=1,
        cache_directory=tmp_path / "cache",
        embedder=CountingEmbedder(),
        progress_callback=lambda **event: events.append(event),
    )

    assert [event["pages_processed"] for event in events if event["stage"] == "extract"] == [1, 2]
    embedded = [event for event in events if event["stage"] == "embed"]
    assert len(embedded) > 1
    assert embedded[-1]["chunks_embedded"] == embedded[-1]["total_chunks"]


def test_indexer_cancellation_stops_before_the_next_embedding_batch(monkeypatch, tmp_path):
    textbook = tmp_path / "book.pdf"
    textbook.write_bytes(b"cancel test")
    monkeypatch.setattr("rag.indexer.document_page_count", lambda path: 1)
    monkeypatch.setattr(
        "rag.indexer.iter_document_pages",
        lambda path, **kwargs: iter(
            [SimpleNamespace(source=path.name, page_number=1, text="cancel batch " * 40)]
        ),
    )
    cancel = Event()

    class CancellingEmbedder(CountingEmbedder):
        def embed(self, texts):
            vectors = super().embed(texts)
            cancel.set()
            return vectors

    with pytest.raises(IndexingCancelled):
        index_textbook(
            textbook,
            chunk_size=20,
            overlap=0,
            batch_size=1,
            cache_directory=tmp_path / "cache",
            embedder=CancellingEmbedder(),
            cancel_event=cancel,
        )
