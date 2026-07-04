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
    rerank_top: int = 30
    """§7.5 nominally reranks the fused top 50, but CE forward passes dominate
    warm latency on CPU (fused-top-50 at 1200 chars measured p95 ≈ 750 ms vs
    the §13 gate of < 500 ms). Depth 30 + 1000-char passages meet the gate
    with identical gold-set quality — §15 spirit clause, see DECISIONS.md."""
    # TODO(upgrade): §6 primary BAAI/bge-reranker-v2-m3 rejected for CPU
    # latency (p95 6696 ms vs the 500 ms §13 gate; +0.034 MRR — EVAL_LOG.md).
    # Revisit on GPU / quantized runtimes.
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_max_chars: int = 1000
    """Per-passage character cap fed to the cross-encoder. Sequence length
    dominates CE cost on CPU; the breadcrumb + opening lines carry most of
    the relevance signal."""

    # 1-hop graph expansion
    expansion_enabled: bool = True
    expansion_top: int = 10
    expansion_discount: float = 0.6

    # budget packing
    default_budget_tokens: int = 4000

    # embeddings — winner of the Phase 3 fixture benchmark (DECISIONS.md):
    # nomic vec recall@5 1.00 / MRR 0.867 vs MiniLM 0.92 / 0.831; jina scored
    # 1.00 / 0.890 but cannot load under transformers>=5 (disqualified).
    embed_model: str = "nomic-ai/nomic-embed-text-v1.5"
    embed_batch_size: int = 32
    embed_trust_remote_code: bool = True
    """nomic-embed ships custom modeling code; required by the default model."""

    model_cache_dir: Path = field(default_factory=default_cache_dir)
