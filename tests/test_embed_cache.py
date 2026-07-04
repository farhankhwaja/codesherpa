"""Embedding engine tests: permanent cache, batching, normalization."""

from __future__ import annotations

import math

import pytest

from repograph.embed.engine import EmbeddingEngine
from tests.support.factories import make_chunk
from tests.support.memstore import InMemoryIndexStore


class CountingEncoder:
    """Deterministic stub encoder that records every batch it sees."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        out = []
        for text in texts:
            h = hash(text) % 997
            out.append([float(h), 1.0, float(len(text) % 31)])
        return out

    @property
    def total_texts(self) -> int:
        return sum(len(b) for b in self.batches)


def _chunks(n: int) -> list:
    return [
        make_chunk(
            blob_hash=f"{i:040x}",
            byte_start=0,
            byte_end=50,
            code=f"def fn_{i}():\n    return {i}\n",
            breadcrumb=f"m{i}.py :: module :: def fn_{i}()",
        )
        for i in range(n)
    ]


def test_reindex_unchanged_chunks_computes_zero_new_embeddings():
    """Phase 3 criterion: re-indexing an unchanged fixture -> 0 new embeddings."""
    store = InMemoryIndexStore()
    for c in _chunks(10):
        store.add_blob(c.blob_hash, "python", 100)
    encoder = CountingEncoder()
    engine = EmbeddingEngine(store, "stub-model", encoder=encoder)

    first = engine.embed_chunks(_chunks(10))
    assert engine.computed_count == 10
    assert encoder.total_texts == 10

    # same chunks again — must be served fully from cache
    second = engine.embed_chunks(_chunks(10))
    assert engine.computed_count == 10, "re-index must compute 0 new embeddings"
    assert encoder.total_texts == 10
    assert second == first

    # a fresh engine over the same store also sees the cache (it is permanent)
    engine2 = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    engine2.embed_chunks(_chunks(10))
    assert engine2.computed_count == 0


def test_only_misses_are_computed():
    store = InMemoryIndexStore()
    engine = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    engine.embed_chunks(_chunks(4))
    engine.embed_chunks(_chunks(7))  # 4 cached + 3 new
    assert engine.computed_count == 7


def test_batching_respects_batch_size():
    store = InMemoryIndexStore()
    encoder = CountingEncoder()
    engine = EmbeddingEngine(store, "stub-model", encoder=encoder, batch_size=32)
    engine.embed_chunks(_chunks(70))
    assert [len(b) for b in encoder.batches] == [32, 32, 6]


def test_vectors_are_normalized():
    store = InMemoryIndexStore()
    engine = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    vectors = engine.embed_chunks(_chunks(3))
    for vec in vectors.values():
        assert math.sqrt(sum(v * v for v in vec)) == pytest.approx(1.0)
    q = engine.embed_query("where is retry logic")
    assert math.sqrt(sum(v * v for v in q)) == pytest.approx(1.0)


def test_embedded_text_is_breadcrumb_plus_code():
    store = InMemoryIndexStore()
    encoder = CountingEncoder()
    engine = EmbeddingEngine(store, "stub-model", encoder=encoder)
    chunk = make_chunk()
    engine.embed_chunks([chunk])
    assert encoder.batches[0][0] == f"{chunk.breadcrumb}\n{chunk.code}"


def test_nomic_prefixes_applied():
    store = InMemoryIndexStore()
    encoder = CountingEncoder()
    engine = EmbeddingEngine(store, "nomic-ai/nomic-embed-text-v1.5", encoder=encoder)
    chunk = make_chunk()
    engine.embed_chunks([chunk])
    engine.embed_query("find retry logic")
    assert encoder.batches[0][0].startswith("search_document: ")
    assert encoder.batches[1][0] == "search_query: find retry logic"


def test_duplicate_chunks_in_one_call_computed_once():
    store = InMemoryIndexStore()
    engine = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    chunk = make_chunk()
    engine.embed_chunks([chunk, chunk, chunk])
    assert engine.computed_count == 1


def test_invalid_batch_size_raises():
    with pytest.raises(ValueError):
        EmbeddingEngine(InMemoryIndexStore(), "m", batch_size=0)
