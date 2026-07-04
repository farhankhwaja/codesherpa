"""Unit tests for the SQLite IndexStore implementation (Phase 1)."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from repograph.contracts.index_contract import IndexStore
from repograph.contracts.types import Chunk, Edge, EdgeKind, SymbolKind, SymbolNode
from repograph.store.sqlite_store import SQLiteIndexStore


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteIndexStore:
    s = SQLiteIndexStore(tmp_path / "index.db")
    yield s
    s.close()


def make_chunk(blob: str = "b" * 40, start: int = 0, end: int = 10, **kw) -> Chunk:
    defaults = dict(
        blob_hash=blob,
        byte_start=start,
        byte_end=end,
        file_path="pyserver/db.py",
        language="python",
        code="def connect():\n    pass\n"[: end - start],
        breadcrumb="pyserver/db.py :: Database :: def connect()",
    )
    defaults.update(kw)
    return Chunk(**defaults)


def test_is_a_contract_implementation(store: SQLiteIndexStore) -> None:
    assert isinstance(store, IndexStore)


def test_schema_tables_exist(store: SQLiteIndexStore) -> None:
    names = {
        row[0]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    for required in ("meta", "blobs", "files", "chunks", "chunks_fts", "symbols", "edges", "embeddings"):
        assert required in names, f"missing table {required}"
    assert store.get_meta("schema_version") == "1"


# ------------------------------------------------------------------- blobs


def test_blob_roundtrip_and_soft_deactivation(store: SQLiteIndexStore) -> None:
    store.add_blob("a" * 40, "python", 123)
    store.add_blob("b" * 40, "typescript", 456)
    assert store.has_blob("a" * 40)
    assert not store.has_blob("c" * 40)
    assert store.active_blobs() == {"a" * 40, "b" * 40}

    store.set_blobs_active(["a" * 40], active=False)
    assert store.active_blobs() == {"b" * 40}
    # soft: the row is still there, and re-adding reactivates
    assert store.has_blob("a" * 40)
    store.add_blob("a" * 40, "python", 123)
    assert store.active_blobs() == {"a" * 40, "b" * 40}


def test_add_blob_is_idempotent(store: SQLiteIndexStore) -> None:
    store.add_blob("a" * 40, "python", 1)
    store.add_blob("a" * 40, "python", 1)
    count = store.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
    assert count == 1


# ------------------------------------------------------------------- files


def test_map_files_replaces_per_ref(store: SQLiteIndexStore) -> None:
    store.map_files("HEAD", {"a.py": "1" * 40, "b.py": "2" * 40})
    store.map_files("HEAD", {"a.py": "3" * 40})
    store.map_files("refs/heads/dev", {"c.py": "4" * 40})
    assert store.files_for_ref("HEAD") == {"a.py": "3" * 40}
    assert store.files_for_ref("refs/heads/dev") == {"c.py": "4" * 40}
    assert store.files_for_ref("refs/heads/nope") == {}


# ------------------------------------------------------------------ chunks


def test_chunk_roundtrip(store: SQLiteIndexStore) -> None:
    chunk = make_chunk()
    store.add_blob(chunk.blob_hash, "python", 100)
    store.add_chunks([chunk])
    got = store.get_chunk(chunk.chunk_id)
    assert got == chunk
    assert store.get_chunk("nope:0:1") is None
    assert store.chunks_for_blob(chunk.blob_hash) == [chunk]


def test_add_chunks_idempotent_including_fts(store: SQLiteIndexStore) -> None:
    chunk = make_chunk()
    store.add_blob(chunk.blob_hash, "python", 100)
    store.add_chunks([chunk])
    store.add_chunks([chunk])
    n_chunks = store.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_fts = store.conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    assert n_chunks == 1
    assert n_fts == 1


def test_chunks_for_blob_ordered_by_byte_start(store: SQLiteIndexStore) -> None:
    blob = "d" * 40
    store.add_blob(blob, "python", 100)
    c2 = make_chunk(blob=blob, start=50, end=60)
    c1 = make_chunk(blob=blob, start=0, end=50)
    store.add_chunks([c2, c1])
    assert [c.byte_start for c in store.chunks_for_blob(blob)] == [0, 50]


# --------------------------------------------------------------------- FTS


def test_fts_search_finds_code_and_respects_active(store: SQLiteIndexStore) -> None:
    blob_a, blob_b = "a" * 40, "b" * 40
    store.add_blob(blob_a, "python", 100)
    store.add_blob(blob_b, "python", 100)
    store.add_chunks(
        [
            make_chunk(blob=blob_a, code="def retry_request(url):\n    pass\n"),
            make_chunk(blob=blob_b, code="def unrelated_thing():\n    pass\n"),
        ]
    )
    hits = store.fts_search("retry_request")
    assert [cid for cid, _ in hits] == [f"{blob_a}:0:10"]

    store.set_blobs_active([blob_a], active=False)
    assert store.fts_search("retry_request") == []


def test_fts_search_never_raises_on_weird_queries(store: SQLiteIndexStore) -> None:
    store.add_blob("a" * 40, "python", 10)
    store.add_chunks([make_chunk(blob="a" * 40)])
    for query in ('"unbalanced', "a AND OR NOT (", "col:val*", "", "!!!", "日本語"):
        store.fts_search(query)  # must not raise


# ----------------------------------------------------------------- symbols


def _symbol(name: str, blob: str = "a" * 40, start: int = 0) -> SymbolNode:
    return SymbolNode(
        symbol=name,
        kind=SymbolKind.FUNCTION,
        blob_hash=blob,
        byte_start=start,
        byte_end=start + 10,
        file_path="pyserver/http.py",
        signature=f"def {name}()",
    )


def test_symbol_definitions_and_active_filter(store: SQLiteIndexStore) -> None:
    store.add_blob("a" * 40, "python", 10)
    store.add_symbols([_symbol("retry_request")])
    defs = store.get_definitions("retry_request")
    assert len(defs) == 1
    assert defs[0].kind is SymbolKind.FUNCTION
    assert store.get_definitions("nope") == []

    store.set_blobs_active(["a" * 40], active=False)
    assert store.get_definitions("retry_request") == []


def test_symbol_search_ranks_exact_prefix_substring(store: SQLiteIndexStore) -> None:
    store.add_blob("a" * 40, "python", 10)
    store.add_symbols(
        [
            _symbol("fetch", start=0),
            _symbol("fetch_tasks", start=20),
            _symbol("prefetch", start=40),
            _symbol("unrelated", start=60),
        ]
    )
    names = [s.symbol for s in store.symbol_search("fetch")]
    assert names == ["fetch", "fetch_tasks", "prefetch"]


def test_edges_roundtrip_and_direction(store: SQLiteIndexStore) -> None:
    e = Edge(src="n1", dst="n2", kind=EdgeKind.CALLS)
    store.add_edges([e, e])  # idempotent
    assert store.get_edges("n1") == [e]
    assert store.get_edges("n1", kind=EdgeKind.IMPORTS) == []
    assert store.get_edges("n2") == []
    assert store.get_edges("n2", incoming=True) == [e]
    n = store.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    assert n == 1


# -------------------------------------------------------------- embeddings


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


def test_embedding_cache_roundtrip(store: SQLiteIndexStore) -> None:
    vec = _unit([1.0, 2.0, 3.0, 4.0])
    store.put_embedding("c1", vec, model="test-model")
    got = store.get_embedding("c1")
    assert got is not None
    assert got == pytest.approx(vec, abs=1e-6)
    assert store.get_embedding("missing") is None


def test_vector_search_orders_by_similarity(store: SQLiteIndexStore) -> None:
    blob = "a" * 40
    store.add_blob(blob, "python", 10)
    c1 = make_chunk(blob=blob, start=0, end=10)
    c2 = make_chunk(blob=blob, start=10, end=20)
    c3 = make_chunk(blob=blob, start=20, end=30)
    store.add_chunks([c1, c2, c3])

    store.put_embedding(c1.chunk_id, _unit([1.0, 0.0, 0.0, 0.0]), "m")
    store.put_embedding(c2.chunk_id, _unit([0.9, 0.1, 0.0, 0.0]), "m")
    store.put_embedding(c3.chunk_id, _unit([0.0, 0.0, 1.0, 0.0]), "m")

    hits = store.vector_search(_unit([1.0, 0.0, 0.0, 0.0]), limit=3)
    assert [cid for cid, _ in hits] == [c1.chunk_id, c2.chunk_id, c3.chunk_id]
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


def test_vector_search_respects_active(store: SQLiteIndexStore) -> None:
    blob = "a" * 40
    store.add_blob(blob, "python", 10)
    c1 = make_chunk(blob=blob, start=0, end=10)
    store.add_chunks([c1])
    store.put_embedding(c1.chunk_id, _unit([1.0, 0.0, 0.0]), "m")

    store.set_blobs_active([blob], active=False)
    assert store.vector_search(_unit([1.0, 0.0, 0.0])) == []


def test_dim_mismatch_rejected(store: SQLiteIndexStore) -> None:
    store.put_embedding("c1", _unit([1.0, 0.0, 0.0]), "m")
    with pytest.raises(ValueError):
        store.put_embedding("c2", _unit([1.0, 0.0, 0.0, 0.0]), "m")


# ------------------------------------------------------------------- meta


def test_meta_roundtrip(store: SQLiteIndexStore) -> None:
    assert store.get_meta("nope") is None
    store.set_meta("last_sync", "2026-07-04T00:00:00Z")
    store.set_meta("last_sync", "2026-07-05T00:00:00Z")
    assert store.get_meta("last_sync") == "2026-07-05T00:00:00Z"


def test_persistence_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    s1 = SQLiteIndexStore(db)
    s1.add_blob("a" * 40, "python", 10)
    s1.close()
    s2 = SQLiteIndexStore(db)
    try:
        assert s2.active_blobs() == {"a" * 40}
    finally:
        s2.close()


def test_wal_mode_and_integrity(store: SQLiteIndexStore) -> None:
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    ok = store.conn.execute("PRAGMA integrity_check").fetchone()[0]
    assert ok == "ok"
