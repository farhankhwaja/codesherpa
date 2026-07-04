"""Retriever factory for the eval harness (eval/run_eval.py, DECISIONS D17).

``build_eval_retriever(repo_path, mode)`` with mode ∈ {hybrid, bm25, vector}:
indexes the repo for real (gitlayer sync -> cAST -> SQLite store -> graph),
embeds every active chunk through the permanent cache, and returns either the
full §7.5 hybrid pipeline or a single-channel baseline. The single-channel
retrievers exist so the §13 comparison gate ("hybrid strictly beats BM25-only
and vector-only") measures the channels through identical packing.
"""

from __future__ import annotations

from pathlib import Path

from repograph.contracts.retrieval_contract import Retriever
from repograph.contracts.types import PackedContext, RetrievalSource
from repograph.embed.engine import EmbeddingEngine
from repograph.gitlayer.sync import default_db_path, sync
from repograph.retrieve.config import RetrievalConfig
from repograph.retrieve.pack import pack_results
from repograph.retrieve.retriever import HybridRetriever
from repograph.store.sqlite_store import SQLiteIndexStore

_MODES = ("hybrid", "bm25", "vector")


class SingleChannelRetriever(HybridRetriever):
    """BM25-only / vector-only baseline: one channel -> budget packing.

    No router, no fusion, no rerank, no expansion — the §13 gate compares the
    hybrid pipeline against each retrieval method alone, packed identically.
    Structural lookups (get_definition, ...) inherit from HybridRetriever.
    """

    def __init__(self, store, embedder, channel: str, *, config=None) -> None:
        baseline = config or RetrievalConfig()
        baseline.rerank_enabled = False
        baseline.expansion_enabled = False
        super().__init__(store, embedder, config=baseline)
        if channel not in ("bm25", "vector"):
            raise ValueError(f"unknown channel {channel!r}")
        self._channel = channel

    def search(self, query: str, budget_tokens: int = 4000) -> PackedContext:
        if self._channel == "bm25":
            ranked = self._store.fts_search(query, limit=self._config.bm25_top)
            source = RetrievalSource.BM25
        else:
            ranked = self._store.vector_search(
                self._embedder.embed_query(query), limit=self._config.vector_top
            )
            source = RetrievalSource.VECTOR
        candidates = []
        for cid, score in ranked:
            chunk = self._store.get_chunk(cid)
            if chunk is not None:
                candidates.append(self._result(chunk, score, source))
        return pack_results(query, candidates, budget_tokens)


def _index_and_embed(repo_path: str) -> tuple[SQLiteIndexStore, EmbeddingEngine, RetrievalConfig]:
    """Sync ``repo_path`` (blobs, chunks, FTS, symbol graph) and embed every
    active chunk through the permanent cache. Re-invocations only pay for
    genuinely new chunks."""
    root = Path(repo_path)
    sync(root)
    store = SQLiteIndexStore(default_db_path(root.resolve()))
    config = RetrievalConfig()
    embedder = EmbeddingEngine(
        store,
        config.embed_model,
        batch_size=config.embed_batch_size,
        cache_dir=config.model_cache_dir,
        trust_remote_code=config.embed_trust_remote_code,
    )
    chunks = [
        c for blob in sorted(store.active_blobs()) for c in store.chunks_for_blob(blob)
    ]
    embedder.embed_chunks(chunks)
    return store, embedder, config


def build_retriever(repo_path: str):
    """Production wiring: ``(HybridRetriever, store)`` over the repo's index.

    Consumed by ``python -m repograph.mcp_server`` and ``repograph serve``
    (repograph/mcp_server/__main__.py imports it lazily by this exact name —
    proposed by the graph-mcp worktree in PROGRESS.md).
    """
    store, embedder, config = _index_and_embed(repo_path)
    return HybridRetriever(store, embedder, config=config), store


def build_eval_retriever(repo_path: str, mode: str = "hybrid") -> Retriever:
    """Retriever factory for eval/run_eval.py (D17): mode ∈ hybrid|bm25|vector."""
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")
    store, embedder, config = _index_and_embed(repo_path)
    if mode == "hybrid":
        return HybridRetriever(store, embedder, config=config)
    return SingleChannelRetriever(store, embedder, mode, config=config)
