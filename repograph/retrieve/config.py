"""Retrieval pipeline configuration (CLAUDE.md §7.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from repograph.embed.engine import default_cache_dir

__all__ = ["RetrievalConfig", "default_cache_dir"]


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
    rerank_top: int = 20
    """§7.5 nominally reranks the fused top 50, but CE forward passes dominate
    warm latency on CPU and real cAST chunks are mostly whole-file (every
    passage hits the char cap): depth 30 measured p95 = 519 ms vs the §13
    gate of < 500 ms; depth 20 + 700-char passages measure ~380 ms with
    unchanged gold-set quality — §15 spirit clause, see DECISIONS.md."""
    # TODO(upgrade): §6 primary BAAI/bge-reranker-v2-m3 rejected for CPU
    # latency (p95 6696 ms vs the 500 ms §13 gate; +0.034 MRR — EVAL_LOG.md).
    # Revisit on GPU / quantized runtimes.
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_max_chars: int = 700
    """Per-passage character cap fed to the cross-encoder. Sequence length
    dominates CE cost on CPU; passages are query-focused windows
    (retrieve/passages.py), not head-truncations. 1000 chars measured
    p95 = 523 ms on real chunks."""

    rerank_channel_head: int = 8
    """CE candidates are the UNION of each channel's head (this many from
    vector and BM25, half from symbols) before filling from fused order —
    fused-only selection let BM25 stopword floods push a vector-rank-4 chunk
    to fused-rank-26, beyond the CE's window entirely (DECISIONS.md)."""

    rerank_blend_vector: bool = True
    """Rank-fuse the CE ordering with the vector ordering instead of letting
    the CE overwrite scores. A web-trained CE is unreliable on
    vocabulary-mismatch code queries where the embedder is strong; RRF over
    (CE rank, vector rank) keeps both signals. False = pure CE scores."""

    rerank_blend_vector_weight: float = 4.0
    """Vector-list weight in the CE blend (CE weight is 1). The dense channel
    is the primary signal; the CE acts as a booster/tie-breaker that can lift
    a chunk it ranks highly but cannot bury a vector-top chunk. Chosen by
    grid on the hardened gold set (w=1..6: recall@5 0.914 -> 0.971 at w=4,
    plateau after) — table in DECISIONS.md."""

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
