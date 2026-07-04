"""Retrieval pipeline configuration (CLAUDE.md §7.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def default_cache_dir() -> Path:
    """Model cache location (CLAUDE.md §6: cache under ~/.cache/repograph/)."""
    return Path.home() / ".cache" / "repograph" / "models"


@dataclass
class RetrievalConfig:
    """Tunables for the hybrid retrieval pipeline.

    Defaults mirror CLAUDE.md §7.5: BM25/vector top 100, symbol top 20,
    RRF k=60, rerank fused top 50, expand top 10 with a 0.6 discount,
    4000-token default budget.
    """

    # candidate list sizes
    bm25_top: int = 100
    vector_top: int = 100
    symbol_top: int = 20

    # reciprocal rank fusion
    rrf_k: int = 60

    # cross-encoder rerank
    rerank_enabled: bool = True
    rerank_top: int = 50
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_max_chars: int = 2000
    """Per-passage character cap fed to the cross-encoder (latency guard)."""

    # 1-hop graph expansion
    expansion_enabled: bool = True
    expansion_top: int = 10
    expansion_discount: float = 0.6

    # budget packing
    default_budget_tokens: int = 4000

    # embeddings
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_batch_size: int = 32

    model_cache_dir: Path = field(default_factory=default_cache_dir)
