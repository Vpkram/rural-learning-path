import numpy as np
import pytest

from rag.models import TextChunk, TextbookIndex
from rag.retriever import NOT_FOUND_MESSAGE, retrieve


class QueryEmbedder:
    model_name = "test-model"

    def __init__(self, vector):
        self.vector = np.asarray(vector, dtype=np.float32)

    def embed(self, texts):
        assert len(texts) == 1
        return self.vector.reshape(1, -1)


def test_retrieval_returns_top_k_chunks_with_similarity_scores():
    chunks = (
        TextChunk("a", "book.pdf", 1, "match"),
        TextChunk("b", "book.pdf", 2, "partial"),
        TextChunk("c", "book.pdf", 3, "different"),
    )
    index = TextbookIndex(
        "book.pdf",
        "test-model",
        "cache",
        chunks,
        np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32),
    )
    result = retrieve("topic", index, embedder=QueryEmbedder([1, 0]), top_k=2, similarity_threshold=0.5)

    assert result.found
    assert [match.chunk.chunk_id for match in result.matches] == ["a", "b"]
    assert result.matches[0].similarity == pytest.approx(1.0)


def test_retrieval_returns_not_found_without_matches_above_threshold():
    chunks = (TextChunk("c", "book.pdf", 1, "other topic"),)
    index = TextbookIndex("book.pdf", "test-model", "cache", chunks, np.array([[0, 1]], dtype=np.float32))
    result = retrieve(
        "missing topic",
        index,
        embedder=QueryEmbedder([1, 0]),
        similarity_threshold=0.4,
    )
    assert not result.found
    assert result.matches == ()
    assert result.message == NOT_FOUND_MESSAGE


def test_retrieval_rejects_invalid_settings_or_mismatched_model():
    chunks = (TextChunk("c", "book.pdf", 1, "text"),)
    index = TextbookIndex("book.pdf", "test-model", "cache", chunks, np.array([[1, 0]], dtype=np.float32))
    with pytest.raises(ValueError, match="top_k"):
        retrieve("text", index, embedder=QueryEmbedder([1, 0]), top_k=0)
    with pytest.raises(ValueError, match="similarity_threshold"):
        retrieve("text", index, embedder=QueryEmbedder([1, 0]), similarity_threshold=1.1)
    wrong_model = QueryEmbedder([1, 0])
    wrong_model.model_name = "other-model"
    with pytest.raises(ValueError, match="must match"):
        retrieve("text", index, embedder=wrong_model)
