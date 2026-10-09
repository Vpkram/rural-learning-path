from types import SimpleNamespace

import numpy as np
import pytest

from rag.embeddings import (
    EmbeddingCache,
    EmbeddingError,
    SentenceTransformerEmbeddings,
    _load_sentence_transformer,
)


class FakeModel:
    def encode(self, texts, **_kwargs):
        return np.array([[len(text), 1] for text in texts], dtype=np.float32)


def test_embedding_adapter_reuses_loaded_model(monkeypatch):
    calls = []

    def fake_loader(model_name):
        calls.append(model_name)
        return FakeModel()

    monkeypatch.setattr("rag.embeddings._load_sentence_transformer", fake_loader)
    adapter = SentenceTransformerEmbeddings("test-model")
    result = adapter.embed(["alpha", "beta"])
    assert result.shape == (2, 2)
    assert calls == ["test-model"]


def test_sentence_transformer_load_is_local_only(monkeypatch):
    received = {}

    def fake_sentence_transformer(model_name, **kwargs):
        received["model_name"] = model_name
        received.update(kwargs)
        return FakeModel()

    monkeypatch.setitem(
        __import__("sys").modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=fake_sentence_transformer),
    )
    _load_sentence_transformer.cache_clear()
    try:
        first_model = _load_sentence_transformer("local-test-model")
        second_model = _load_sentence_transformer("local-test-model")
    finally:
        _load_sentence_transformer.cache_clear()
    assert received == {
        "model_name": "local-test-model",
        "device": "cpu",
        "local_files_only": True,
    }
    assert first_model is second_model


def test_embedding_cache_round_trips_metadata_and_vectors(tmp_path):
    cache = EmbeddingCache(tmp_path)
    key = "a" * 64
    metadata = {
        "chunks": [
            {"chunk_id": "c1", "text": "first"},
            {"chunk_id": "c2", "text": "second"},
        ]
    }
    vectors = np.array([[1, 0], [0, 1]], dtype=np.float32)
    path = cache.save(key, metadata, vectors)

    loaded = cache.load(key)
    assert path.exists()
    assert loaded is not None
    loaded_metadata, loaded_vectors = loaded
    assert loaded_metadata == metadata
    np.testing.assert_array_equal(loaded_vectors, vectors)


def test_embedding_cache_is_pickle_free_and_reports_corruption(tmp_path):
    cache = EmbeddingCache(tmp_path)
    key = "b" * 64
    path = tmp_path / f"{key}.npz"
    path.write_text("not an npz", encoding="utf-8")
    with pytest.raises(EmbeddingError, match="unreadable"):
        cache.load(key)


def test_embedding_cache_requires_hex_key(tmp_path):
    with pytest.raises(ValueError, match="hexadecimal"):
        EmbeddingCache(tmp_path).load("../unsafe")
