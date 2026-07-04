"""Golden Test — embeddings extension (Phase 3; CLAUDE.md §2.3, D14 exception).

Drives the same fixture ops as the main golden test, but embeds all active
chunks (through the permanent cache) after every incremental sync; the
rebuild side syncs once and embeds once at the final HEAD. The full golden
projection — now including ``embeddings_of_active_blobs`` — must be
IDENTICAL: same chunks present, same dimensions, same exact vector bytes
(the encoder is deterministic, so cached bytes must agree even though the
incremental side computed most embeddings many ops earlier).

The encoder is a deterministic sha256-based stub (mocks live in tests only,
§2.5): golden equality is about cache/index bookkeeping, not model quality.
"""

from __future__ import annotations

import hashlib

from repograph.embed.engine import EmbeddingEngine
from repograph.gitlayer.sync import sync
from repograph.store.sqlite_store import SQLiteIndexStore
from tests.test_golden import GOLDEN_PROJECTION, _fresh_clone, golden_state

_DIM = 24


def _sha_encoder(texts: list[str]) -> list[list[float]]:
    """Deterministic across processes and runs (no salted hash())."""
    out = []
    for text in texts:
        digest = hashlib.sha256(text.encode()).digest()
        out.append([float(b) + 1.0 for b in digest[:_DIM]])
    return out


def _embed_all_active(db_path) -> int:
    """Embed every active chunk through the cache; return newly computed."""
    store = SQLiteIndexStore(db_path)
    try:
        engine = EmbeddingEngine(store, "golden-stub", encoder=_sha_encoder)
        chunks = [
            c
            for blob in sorted(store.active_blobs())
            for c in store.chunks_for_blob(blob)
        ]
        engine.embed_chunks(chunks)
        return engine.computed_count
    finally:
        store.close()


# Every op kind at least once, history-churning (mirrors the pinned example
# of the main golden test; kept short — each round costs a sync + embed).
_OPS = [
    ("add", 0, 7),
    ("modify", 3),
    ("branch", 1),
    ("switch",),
    ("merge_change", 5),
    ("modify", 5),
    ("delete", 2),
    ("revert",),
    ("add", 1, 13),
]


def test_golden_embeddings_incremental_equals_rebuild(miniproject, tmp_path):
    driver = _fresh_clone(miniproject, tmp_path / "repo")

    inc_db = tmp_path / "incremental.db"
    sync(driver.path, inc_db)
    _embed_all_active(inc_db)
    for op in _OPS:
        driver.apply(op)
        sync(driver.path, inc_db)
        _embed_all_active(inc_db)

    rebuild_db = tmp_path / "rebuild.db"
    sync(driver.path, rebuild_db)
    _embed_all_active(rebuild_db)

    incremental = golden_state(inc_db)
    rebuild = golden_state(rebuild_db)

    for name in GOLDEN_PROJECTION:
        assert incremental[name] == rebuild[name], f"projection {name!r} diverged"

    # non-vacuous: embeddings exist, and cover EVERY active chunk on both sides
    emb = incremental["embeddings_of_active_blobs"]
    assert emb, "embeddings projection is empty — extension is vacuous"
    chunks = incremental["chunks_of_active_blobs"]
    for blob, chunk_rows in chunks.items():
        embedded_ids = {cid for cid, _, _ in emb.get(blob, [])}
        assert embedded_ids == {cid for cid, _ in chunk_rows}, (
            f"blob {blob}: active chunks and cached embeddings diverge"
        )
    # all dims uniform
    dims = {dim for rows in emb.values() for _, dim, _ in rows}
    assert dims == {_DIM}


def test_incremental_embedding_work_is_cache_bounded(miniproject, tmp_path):
    """Re-embedding after a no-op sync computes zero; after one modify, only
    the changed blob's chunks are recomputed (blob-hash-keyed cache, §4)."""
    driver = _fresh_clone(miniproject, tmp_path / "repo")
    db = tmp_path / "inc.db"
    sync(driver.path, db)
    first = _embed_all_active(db)
    assert first > 0

    sync(driver.path, db)  # no-op sync
    assert _embed_all_active(db) == 0

    driver.apply(("modify", 3))
    sync(driver.path, db)
    recomputed = _embed_all_active(db)
    store = SQLiteIndexStore(db)
    try:
        files = store.files_for_ref("HEAD")
        # the modified file maps to a new blob; only its chunks were recomputed
        max_one_blob_chunks = max(
            len(store.chunks_for_blob(blob)) for blob in files.values()
        )
    finally:
        store.close()
    assert 0 < recomputed <= max_one_blob_chunks
