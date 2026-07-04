"""Phase 5: the index-wide embedding pass (codesherpa.retrieve.warm).

init/sync own embedding computation; the MCP server only reports warming.
These tests cover the pass itself: incremental behavior, progress callbacks,
hook safety (never download inside a hook), and vector-space invalidation
when the embedding tag (model or text version) changes.
"""

from __future__ import annotations

import hashlib

import pytest

from codesherpa.embed.engine import EmbeddingEngine
from codesherpa.retrieve.warm import (
    embed_index,
    embedding_tag,
    ensure_embedding_compat,
    missing_embeddings,
)
from codesherpa.store.sqlite_store import SQLiteIndexStore
from tests.support.factories import make_chunk


@pytest.fixture()
def store(tmp_path) -> SQLiteIndexStore:
    s = SQLiteIndexStore(tmp_path / "warm-test.db")
    yield s
    s.close()


def _encoder(dim: int):
    def encode(texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            out.append([float(b) + 1.0 for b in digest[:dim]])
        return out

    return encode


def _populate(store: SQLiteIndexStore, n: int) -> None:
    for i in range(n):
        chunk = make_chunk(
            blob_hash=f"{i:040x}",
            byte_start=0,
            byte_end=60,
            file_path=f"src/m{i}.py",
            code=f"def fn_{i}():\n    return {i}\n",
            breadcrumb=f"src/m{i}.py :: module :: def fn_{i}()",
        )
        store.add_blob(chunk.blob_hash, "python", 60)
        store.add_chunks([chunk])


def test_embed_index_is_incremental_and_reports_progress(store):
    _populate(store, 5)
    assert missing_embeddings(store) == 5

    engine = EmbeddingEngine(store, "warm-stub", batch_size=2, encoder=_encoder(8))
    calls: list[tuple[int, int]] = []
    computed = embed_index(store, engine=engine, progress=lambda d, t: calls.append((d, t)))

    assert computed == 5
    assert missing_embeddings(store) == 0
    # progress: initial 0/5 then monotone batch steps ending at 5/5
    assert calls[0] == (0, 5)
    assert calls[-1] == (5, 5)
    assert [d for d, _ in calls] == sorted(d for d, _ in calls)

    # second pass: pure cache hit, no progress noise, zero computed
    calls.clear()
    assert embed_index(store, engine=engine, progress=lambda d, t: calls.append((d, t))) == 0
    assert calls == []


def test_hook_safe_pass_never_loads_an_uncached_model(store, tmp_path):
    _populate(store, 3)
    # no injected encoder + empty model cache dir: a load would download
    engine = EmbeddingEngine(store, "no-such/model", cache_dir=tmp_path / "empty-cache")
    assert not engine.has_local_encoder()
    assert embed_index(store, engine=engine, require_cached_model=True) == 0
    assert missing_embeddings(store) == 3  # untouched; server reports warming


def test_tag_change_wipes_stale_vectors_and_repins_dim(store):
    _populate(store, 4)
    engine_a = EmbeddingEngine(store, "model-a", encoder=_encoder(8))
    embed_index(store, engine=engine_a)
    assert store.get_meta("embed_tag") == embedding_tag("model-a")
    assert store.get_meta("vec_dim") in (None, "8")  # None if sqlite-vec absent

    # switching models must not mix vector spaces: old vectors are wiped and
    # the vec table re-pins to the new dimension
    engine_b = EmbeddingEngine(store, "model-b", encoder=_encoder(16))
    computed = embed_index(store, engine=engine_b)
    assert computed == 4  # every chunk re-embedded in the new space
    assert store.get_meta("embed_tag") == embedding_tag("model-b")
    assert missing_embeddings(store) == 0
    dims = {
        row[0]
        for row in store.conn.execute("SELECT DISTINCT dim FROM embeddings").fetchall()
    }
    assert dims == {16}


def test_same_tag_never_wipes(store):
    _populate(store, 2)
    engine = EmbeddingEngine(store, "model-a", encoder=_encoder(8))
    embed_index(store, engine=engine)
    assert ensure_embedding_compat(store, embedding_tag("model-a")) is False
    assert missing_embeddings(store) == 0
