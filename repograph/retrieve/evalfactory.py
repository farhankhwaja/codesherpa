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
from repograph.gitlayer.repo import open_repo, repo_root
from repograph.gitlayer.sync import default_db_path, sync
from repograph.retrieve.config import RetrievalConfig
from repograph.retrieve.pack import pack_results
from repograph.retrieve.retriever import HybridRetriever
from repograph.retrieve.warm import embed_index
from repograph.store.sqlite_store import SQLiteIndexStore

_MODES = ("hybrid", "bm25", "vector")


class IndexNotBuiltError(RuntimeError):
    """The repo has no .repograph/index.db yet — `repograph init` first."""


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


def _wire(store: SQLiteIndexStore, config: RetrievalConfig) -> EmbeddingEngine:
    return EmbeddingEngine(
        store,
        config.embed_model,
        batch_size=config.embed_batch_size,
        cache_dir=config.model_cache_dir,
        trust_remote_code=config.embed_trust_remote_code,
    )


def _index_and_embed(repo_path: str) -> tuple[SQLiteIndexStore, EmbeddingEngine, RetrievalConfig]:
    """Sync ``repo_path`` (blobs, chunks, FTS, symbol graph) and embed every
    active chunk through the permanent cache. Re-invocations only pay for
    genuinely new chunks. Eval-harness wiring — the production server never
    does this at startup (see build_retriever)."""
    root = Path(repo_path)
    sync(root)
    store = SQLiteIndexStore(default_db_path(root.resolve()))
    config = RetrievalConfig()
    embedder = _wire(store, config)
    embed_index(store, config=config, engine=embedder)
    return store, embedder, config


def build_retriever(repo_path: str, config: RetrievalConfig | None = None):
    """Production wiring: ``(HybridRetriever, store)`` over the repo's EXISTING index.

    Consumed by ``python -m repograph.mcp_server`` / ``repograph serve``.
    Deliberately does NOT sync, embed, or load any model: index building and
    embedding belong to ``repograph init``/``sync`` (Phase 5 §3e — the MCP
    handshake must complete immediately, models load lazily on the first
    dense query). Raises :class:`IndexNotBuiltError` when no index exists and
    ``NotARepositoryError`` outside a git repo.
    """
    root = repo_root(open_repo(Path(repo_path)))
    db = default_db_path(root)
    if not db.is_file():
        raise IndexNotBuiltError(
            f"no index at {db} — run `repograph init` in the repository first"
        )
    store = SQLiteIndexStore(db)
    cfg = config or RetrievalConfig()
    return HybridRetriever(store, _wire(store, cfg), config=cfg), store


def build_eval_retriever(repo_path: str, mode: str = "hybrid") -> Retriever:
    """Retriever factory for eval/run_eval.py (D17): mode ∈ hybrid|bm25|vector."""
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")
    store, embedder, config = _index_and_embed(repo_path)
    if mode == "hybrid":
        return HybridRetriever(store, embedder, config=config)
    return SingleChannelRetriever(store, embedder, mode, config=config)
