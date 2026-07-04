"""Shared builder for the Phase 3 eval gate (test + EVAL_LOG report script).

Builds the fixture index once, embeds with the chosen model, and produces
comparable reports for hybrid+rerank, hybrid-norerank, BM25-only and
vector-only over the gold query set.
"""

from __future__ import annotations

from pathlib import Path

from repograph.embed.engine import EmbeddingEngine
from repograph.retrieve.config import RetrievalConfig
from repograph.retrieve.rerank import CrossEncoderReranker
from repograph.retrieve.retriever import HybridRetriever
from tests.support.evallib import EvalReport, evaluate, load_gold_queries
from tests.support.indexer import index_miniproject
from tests.support.memstore import InMemoryIndexStore

ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = ROOT / "eval" / "gold_queries.jsonl"

# Chosen by benchmark on the fixture gold set — see DECISIONS.md (Phase 3).
EMBED_MODEL = "nomic-ai/nomic-embed-text-v1.5"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# §13 thresholds — these constants mirror CLAUDE.md and may never be lowered.
RECALL5_THRESHOLD = 0.80
MRR_THRESHOLD = 0.60
P95_WARM_MS = 500
P95_ROUTER_MS = 200


class GateHarness:
    def __init__(self, fixture_root: Path) -> None:
        self.queries = load_gold_queries(GOLD_PATH)
        self.store: InMemoryIndexStore = index_miniproject(fixture_root)
        self.engine = EmbeddingEngine(self.store, EMBED_MODEL, trust_remote_code=True)
        chunks = [
            c
            for blob in sorted(self.store.active_blobs())
            for c in self.store.chunks_for_blob(blob)
        ]
        self.engine.embed_chunks(chunks)
        self.reranker = CrossEncoderReranker(RERANKER_MODEL)
        self.hybrid_rerank = HybridRetriever(
            self.store,
            self.engine,
            config=RetrievalConfig(rerank_enabled=True, expansion_enabled=False,
                                   reranker_model=RERANKER_MODEL),
            reranker=self.reranker,
        )
        self.hybrid_norerank = HybridRetriever(
            self.store,
            self.engine,
            config=RetrievalConfig(rerank_enabled=False, expansion_enabled=False),
        )

    # ---- ranked-chunk functions for evallib
    def fn_hybrid_rerank(self, query: str) -> list:
        return [r.chunk for r in self.hybrid_rerank.search(query).results]

    def fn_hybrid_norerank(self, query: str) -> list:
        return [r.chunk for r in self.hybrid_norerank.search(query).results]

    def fn_bm25(self, query: str) -> list:
        ranked = self.store.fts_search(query, limit=100)
        return [c for c in (self.store.get_chunk(cid) for cid, _ in ranked) if c]

    def fn_vector(self, query: str) -> list:
        ranked = self.store.vector_search(self.engine.embed_query(query), limit=100)
        return [c for c in (self.store.get_chunk(cid) for cid, _ in ranked) if c]

    def reports(self) -> dict[str, EvalReport]:
        return {
            "hybrid+rerank": evaluate("hybrid+rerank", self.queries, self.fn_hybrid_rerank),
            "hybrid-norerank": evaluate("hybrid-norerank", self.queries, self.fn_hybrid_norerank),
            "bm25-only": evaluate("bm25-only", self.queries, self.fn_bm25),
            "vector-only": evaluate("vector-only", self.queries, self.fn_vector),
        }


def format_table(reports: dict[str, EvalReport]) -> str:
    lines = [
        f"{'method':<18} {'recall@5':>8} {'MRR':>7} {'p95 ms':>7}",
        "-" * 44,
    ]
    for name, rep in reports.items():
        lines.append(
            f"{name:<18} {rep.recall_at_5:>8.2f} {rep.mrr:>7.3f} "
            f"{rep.latency_p95_ms():>7.0f}"
        )
    hyb = reports["hybrid+rerank"]
    router = hyb.latency_p95_ms("symbol")
    lines.append(f"router-path (symbol queries) p95: {router:.0f} ms")
    for miss in hyb.misses():
        lines.append(f"hybrid+rerank miss: {miss.query_id} rank={miss.first_relevant_rank} top={miss.top_files[:3]}")
    return "\n".join(lines)
