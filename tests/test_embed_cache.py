"""Embedding engine tests: permanent cache, batching, normalization.

Runs against the real SQLiteIndexStore (embedding cache table + vec0/meta),
with a deterministic stub encoder (mocks live in tests only, §2.5).
"""

from __future__ import annotations

import math

import pytest

from repograph.embed.engine import EmbeddingEngine
from repograph.store.sqlite_store import SQLiteIndexStore
from tests.support.factories import make_chunk


@pytest.fixture()
def store(tmp_path) -> SQLiteIndexStore:
    s = SQLiteIndexStore(tmp_path / "embed-test.db")
    yield s
    s.close()


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


def test_reindex_unchanged_chunks_computes_zero_new_embeddings(store):
    """Phase 3 criterion: re-indexing an unchanged fixture -> 0 new embeddings."""
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
    assert second.keys() == first.keys()
    for cid in first:  # cache returns float32-packed values
        assert second[cid] == pytest.approx(first[cid], rel=1e-6)

    # a fresh engine over the same store also sees the cache (it is permanent)
    engine2 = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    engine2.embed_chunks(_chunks(10))
    assert engine2.computed_count == 0


def test_cache_survives_store_reopen(store, tmp_path):
    """The cache is a table in the index DB, not process state."""
    engine = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    engine.embed_chunks(_chunks(5))
    store.close()

    reopened = SQLiteIndexStore(tmp_path / "embed-test.db")
    try:
        engine2 = EmbeddingEngine(reopened, "stub-model", encoder=CountingEncoder())
        engine2.embed_chunks(_chunks(5))
        assert engine2.computed_count == 0
    finally:
        reopened.close()


def test_only_misses_are_computed(store):
    engine = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    engine.embed_chunks(_chunks(4))
    engine.embed_chunks(_chunks(7))  # 4 cached + 3 new
    assert engine.computed_count == 7


def test_batching_respects_batch_size(store):
    encoder = CountingEncoder()
    engine = EmbeddingEngine(store, "stub-model", encoder=encoder, batch_size=32)
    engine.embed_chunks(_chunks(70))
    assert [len(b) for b in encoder.batches] == [32, 32, 6]


def test_vectors_are_normalized(store):
    engine = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    vectors = engine.embed_chunks(_chunks(3))
    for vec in vectors.values():
        assert math.sqrt(sum(v * v for v in vec)) == pytest.approx(1.0)
    q = engine.embed_query("where is retry logic")
    assert math.sqrt(sum(v * v for v in q)) == pytest.approx(1.0)


def test_cached_roundtrip_is_float32_stable(store):
    """What the store returns is what later reads see (float32 packing)."""
    engine = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    chunk = make_chunk()
    first = engine.embed_chunks([chunk])[chunk.chunk_id]
    again = store.get_embedding(chunk.chunk_id)
    assert again == pytest.approx(first, rel=1e-6)


def test_embedded_text_is_breadcrumb_plus_code(store):
    encoder = CountingEncoder()
    engine = EmbeddingEngine(store, "stub-model", encoder=encoder)
    chunk = make_chunk()
    engine.embed_chunks([chunk])
    assert encoder.batches[0][0] == f"{chunk.breadcrumb}\n{chunk.code}"


def test_nomic_prefixes_applied(store):
    encoder = CountingEncoder()
    engine = EmbeddingEngine(store, "nomic-ai/nomic-embed-text-v1.5", encoder=encoder)
    chunk = make_chunk()
    engine.embed_chunks([chunk])
    engine.embed_query("find retry logic")
    assert encoder.batches[0][0].startswith("search_document: ")
    assert encoder.batches[1][0] == "search_query: find retry logic"


def test_duplicate_chunks_in_one_call_computed_once(store):
    engine = EmbeddingEngine(store, "stub-model", encoder=CountingEncoder())
    chunk = make_chunk()
    engine.embed_chunks([chunk, chunk, chunk])
    assert engine.computed_count == 1


def test_invalid_batch_size_raises(store):
    with pytest.raises(ValueError):
        EmbeddingEngine(store, "m", batch_size=0)
