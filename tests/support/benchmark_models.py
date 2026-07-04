"""Benchmark candidate embedding models on the fixture gold set (§7.4).

Run manually:  .venv/bin/python tests/support/benchmark_models.py [model ...]

For each model: index the fixture into a fresh in-memory store, embed all
chunks (fresh store per model so caches never mix models), then score
vector-only retrieval and hybrid (RRF, no rerank) on the gold queries.
Winner selection = vector-only recall@5, then MRR (isolates the embedder).
Results are recorded in DECISIONS.md.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from repograph.embed.engine import EmbeddingEngine  # noqa: E402
from repograph.retrieve.config import RetrievalConfig  # noqa: E402
from repograph.retrieve.retriever import HybridRetriever  # noqa: E402
from tests.support.evallib import evaluate, load_gold_queries  # noqa: E402
from tests.support.indexer import index_miniproject  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "miniproject"
GOLD = ROOT / "eval" / "gold_queries.jsonl"

CANDIDATES = [
    "nomic-ai/nomic-embed-text-v1.5",
    "jinaai/jina-embeddings-v2-base-code",
    "sentence-transformers/all-MiniLM-L6-v2",  # approved fallback baseline
]


def ensure_fixture() -> None:
    if not (FIXTURE / ".git").is_dir():
        sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
        import build_miniproject

        build_miniproject.build(FIXTURE)


def bench_model(model_name: str, queries: list[dict]) -> dict:
    store = index_miniproject(FIXTURE)
    engine = EmbeddingEngine(store, model_name, trust_remote_code=True)
    chunks = [c for blob in sorted(store.active_blobs()) for c in store.chunks_for_blob(blob)]

    t0 = time.perf_counter()
    engine.embed_chunks(chunks)
    embed_s = time.perf_counter() - t0

    def vector_only(query: str) -> list:
        ranked = store.vector_search(engine.embed_query(query), limit=100)
        return [c for c in (store.get_chunk(cid) for cid, _ in ranked) if c]

    config = RetrievalConfig(rerank_enabled=False, expansion_enabled=False)
    retriever = HybridRetriever(store, engine, config=config)

    def hybrid(query: str) -> list:
        return [r.chunk for r in retriever.search(query).results]

    vec_report = evaluate(f"{model_name.split('/')[-1]} vec", queries, vector_only)
    hyb_report = evaluate(f"{model_name.split('/')[-1]} hyb", queries, hybrid)
    return {
        "model": model_name,
        "embed_s": embed_s,
        "n_chunks": len(chunks),
        "vector": vec_report,
        "hybrid": hyb_report,
    }


def main() -> None:
    ensure_fixture()
    queries = load_gold_queries(GOLD)
    models = sys.argv[1:] or CANDIDATES
    rows = []
    for model in models:
        print(f"=== {model}", flush=True)
        try:
            rows.append(bench_model(model, queries))
        except Exception as exc:  # keep benchmarking the rest
            print(f"    FAILED: {type(exc).__name__}: {exc}", flush=True)
            continue
        r = rows[-1]
        print(f"    embed {r['n_chunks']} chunks in {r['embed_s']:.1f}s", flush=True)
        print("    " + r["vector"].row(), flush=True)
        print("    " + r["hybrid"].row(), flush=True)

    print("\n=== summary (winner = vector-only recall@5, then MRR) ===")
    for r in sorted(rows, key=lambda r: (-r["vector"].recall_at_5, -r["vector"].mrr)):
        v, h = r["vector"], r["hybrid"]
        print(
            f"{r['model']:<44} vec r@5={v.recall_at_5:.2f} MRR={v.mrr:.3f} | "
            f"hyb r@5={h.recall_at_5:.2f} MRR={h.mrr:.3f} | embed={r['embed_s']:.1f}s"
        )
        for miss in v.misses():
            print(f"    vec miss {miss.query_id} ({miss.query_type}): top={miss.top_files[:3]}")


if __name__ == "__main__":
    main()
