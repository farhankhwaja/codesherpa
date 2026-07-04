"""Index-wide embedding pass — owned by ``sherpa init`` / ``sherpa sync``.

The MCP server must NEVER compute chunk embeddings or download models inside
its startup/handshake (Phase 5 hardening): init/sync call :func:`embed_index`
up front, and the server only *reports* a warming status while embeddings are
missing (sherpa/mcp_server/server.py).

The embedding cache is keyed by chunk identity, which is content-addressed —
but the *vectors* additionally depend on the model and on the exact text fed
to it. :func:`embedding_tag` captures both; :func:`ensure_embedding_compat`
wipes stale vectors when the tag changes (switching ``embed_model`` in
config, or a bump of :data:`EMBED_TEXT_VERSION`) so one index never mixes
vector spaces.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from codesherpa.contracts.index_contract import IndexStore
from codesherpa.contracts.types import Chunk
from codesherpa.embed.engine import EmbeddingEngine, model_is_cached

__all__ = [
    "EMBED_TEXT_VERSION",
    "embedding_tag",
    "active_chunks",
    "missing_embeddings",
    "ensure_embedding_compat",
    "embed_index",
]

EMBED_TEXT_VERSION = 1
"""Version of the text handed to the embedder (EmbeddingEngine.chunk_text).
Bump whenever that text changes shape so cached vectors are recomputed."""

Progress = Callable[[int, int], None]
"""progress(done, total) — called before the first batch and after each one."""


def embedding_tag(model_name: str) -> str:
    return f"{model_name}|text=v{EMBED_TEXT_VERSION}"


def active_chunks(store: IndexStore) -> list[Chunk]:
    """Every chunk of every active blob, in deterministic order."""
    return [
        chunk
        for blob in sorted(store.active_blobs())
        for chunk in store.chunks_for_blob(blob)
    ]


def missing_embeddings(store: IndexStore) -> int:
    """How many active chunks have no cached embedding yet."""
    conn = getattr(store, "conn", None)
    if conn is not None:
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM chunks c
            JOIN blobs b ON b.blob_hash = c.blob_hash AND b.active = 1
            LEFT JOIN embeddings e ON e.chunk_id = c.chunk_id
            WHERE e.chunk_id IS NULL
            """
        ).fetchone()[0]
    return sum(
        1 for chunk in active_chunks(store) if store.get_embedding(chunk.chunk_id) is None
    )


def ensure_embedding_compat(store: IndexStore, tag: str) -> bool:
    """Wipe cached vectors when the embedding tag changed; returns True if wiped.

    A tag change means the stored vectors live in a different space (other
    model, other input text) — keeping them would silently mix spaces inside
    one KNN table. The wipe also clears the vec0 table and its pinned dim so
    a model with a different dimension can be indexed afterwards.
    """
    current = store.get_meta("embed_tag")
    if current == tag:
        return False
    wiped = False
    if current is not None:
        conn = getattr(store, "conn", None)
        if conn is None:
            raise RuntimeError(
                "embedding tag changed but this store cannot clear stale vectors; "
                f"stored={current!r} requested={tag!r}"
            )
        with conn:
            conn.execute("DELETE FROM embeddings")
            conn.execute("DROP TABLE IF EXISTS vec_chunks")
            conn.execute("DELETE FROM meta WHERE key = 'vec_dim'")
        wiped = True
    store.set_meta("embed_tag", tag)
    return wiped


def embed_index(
    store: IndexStore,
    *,
    config=None,
    engine: Optional[EmbeddingEngine] = None,
    progress: Optional[Progress] = None,
    require_cached_model: bool = False,
) -> int:
    """Embed every active chunk that lacks a vector; returns the number computed.

    Incremental by construction: the permanent cache means re-runs only pay
    for genuinely new chunks. ``require_cached_model=True`` makes this a no-op
    when the model is not on disk yet — git hooks use it so a hook never
    triggers a model download (first downloads belong to ``sherpa init``).
    """
    from codesherpa.retrieve.config import RetrievalConfig  # local: avoid cycles

    cfg = config or RetrievalConfig()
    if engine is None:
        engine = EmbeddingEngine(
            store,
            cfg.embed_model,
            batch_size=cfg.embed_batch_size,
            cache_dir=cfg.model_cache_dir,
            trust_remote_code=cfg.embed_trust_remote_code,
        )
    ensure_embedding_compat(store, embedding_tag(engine.model_name))
    misses = [
        chunk
        for chunk in active_chunks(store)
        if store.get_embedding(chunk.chunk_id) is None
    ]
    if not misses:
        return 0
    if require_cached_model and not engine.has_local_encoder():
        return 0  # never download inside a hook; server reports warming
    total = len(misses)
    if progress is not None:
        progress(0, total)
    before = engine.computed_count
    for start in range(0, total, engine.batch_size):
        batch = misses[start : start + engine.batch_size]
        engine.embed_chunks(batch)
        if progress is not None:
            progress(min(start + len(batch), total), total)
    return engine.computed_count - before
