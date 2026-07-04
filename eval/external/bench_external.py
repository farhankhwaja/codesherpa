#!/usr/bin/env python3
"""External-repo retrieval benchmark (Phase 5 §3a/§3b).

Given a repo and a gold-query jsonl, builds one index DB per embedding model
(in a temp dir — the repo's own .repograph is untouched) and reports, per
model: vector-only and full-hybrid recall@5 / MRR (file-level hits, same
definition as eval/run_eval.py), embed time, and warm-query latency. Also
measures the graph-expansion ON/OFF delta for the shipping pipeline.

Usage:
    python eval/external/bench_external.py <repo> <gold.jsonl> \
        [--models nomic-ai/nomic-embed-text-v1.5 sentence-transformers/all-MiniLM-L6-v2]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from repograph.embed.engine import EmbeddingEngine  # noqa: E402
from repograph.gitlayer.sync import sync  # noqa: E402
from repograph.retrieve import HybridRetriever, RetrievalConfig  # noqa: E402
from repograph.retrieve.evalfactory import SingleChannelRetriever  # noqa: E402
from repograph.retrieve.warm import embed_index  # noqa: E402
from repograph.store.sqlite_store import SQLiteIndexStore  # noqa: E402

TOP_K = 5


def _load_gold(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _evaluate(retriever, gold: list[dict]) -> dict:
    hits = 0
    mrr = 0.0
    latencies = []
    misses = []
    for entry in gold:
        started = time.perf_counter()
        packed = retriever.search(entry["query"], budget_tokens=4000)
        latencies.append((time.perf_counter() - started) * 1000)
        rank = None
        for i, result in enumerate(packed.results[:TOP_K]):
            if result.chunk.file_path in entry["expected_files"]:
                rank = i
                break
        if rank is not None:
            hits += 1
            mrr += 1.0 / (rank + 1)
        else:
            misses.append(entry["id"])
    n = len(gold)
    latencies.sort()
    return {
        "recall@5": hits / n,
        "mrr": mrr / n,
        "p50_ms": statistics.median(latencies),
        "p95_ms": latencies[min(n - 1, int(0.95 * n))],
        "misses": misses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("gold")
    parser.add_argument(
        "--models",
        nargs="+",
        default=[
            "nomic-ai/nomic-embed-text-v1.5",
            "sentence-transformers/all-MiniLM-L6-v2",
        ],
    )
    parser.add_argument("--workdir", default=None, help="Where to keep the DBs (default: temp).")
    args = parser.parse_args()

    import tempfile

    gold = _load_gold(Path(args.gold))
    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="bench-ext-"))
    workdir.mkdir(parents=True, exist_ok=True)
    repo = Path(args.repo).resolve()
    print(f"repo={repo} gold={len(gold)} queries workdir={workdir}")

    for model in args.models:
        db = workdir / f"{model.replace('/', '__')}.db"
        sync(repo, db)
        store = SQLiteIndexStore(db)
        config = RetrievalConfig()
        config.embed_model = model
        config.embed_trust_remote_code = model.startswith("nomic-ai/")
        engine = EmbeddingEngine(
            store,
            model,
            batch_size=config.embed_batch_size,
            cache_dir=config.model_cache_dir,
            trust_remote_code=config.embed_trust_remote_code,
        )
        started = time.perf_counter()
        computed = embed_index(store, config=config, engine=engine)
        embed_seconds = time.perf_counter() - started
        print(f"\n== {model}: embedded {computed} chunks in {embed_seconds:.1f}s")

        vector = SingleChannelRetriever(store, engine, "vector", config=RetrievalConfig())
        result = _evaluate(vector, gold)
        print(f"   vector-only : {json.dumps(result)}")

        # warm up hybrid (reranker load) once before timing
        hybrid = HybridRetriever(store, engine, config=config)
        hybrid.search("warmup query for latency", budget_tokens=1000)
        result = _evaluate(hybrid, gold)
        print(f"   hybrid      : {json.dumps(result)}")

        if model == args.models[0]:
            # expansion delta on the shipping pipeline (§3b)
            for flag in (True, False):
                cfg = RetrievalConfig()
                cfg.embed_model = model
                cfg.embed_trust_remote_code = config.embed_trust_remote_code
                cfg.expansion_enabled = flag
                r = HybridRetriever(store, engine, config=cfg)
                r.search("warmup query for latency", budget_tokens=1000)
                res = _evaluate(r, gold)
                print(f"   hybrid expansion={'ON ' if flag else 'OFF'}: {json.dumps(res)}")
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
