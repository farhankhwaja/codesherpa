"""Phase 3 eval harness on the REAL index (gitlayer -> cAST -> SQLite store)
with the real embedding model and cross-encoder (downloads on first run,
cached under ~/.cache/repograph/).

GRADING STATUS (DECISIONS D21, BLOCKED.md): the §13 QUALITY gate — recall@5
>= 0.80, MRR >= 0.60, hybrid strictly beats BM25-only and vector-only — is
DEFERRED by human instruction (2026-07-04) until the hardened gold set from
the graph-mcp session lands on main: the current 25-query set has heavy
query/code vocabulary overlap, so single-method baselines sit at or near the
recall@5 ceiling and the strictly-beats comparison is not meaningful yet.
Numbers are still computed on every run, printed here, and logged to
EVAL_LOG.md marked PRELIMINARY. The thresholds in CLAUDE.md §13 and
tests/support/gatelib.py are UNCHANGED.

What IS asserted here (not gold-set-difficulty-dependent):
- p95 warm latency (reranker on) < 500 ms; router-path p95 < 200 ms (§13)
- the permanent embedding cache computes 0 new embeddings on re-index (§7.4)
- every gold query returns a non-empty packed response (pipeline sanity)
"""

from __future__ import annotations

import pytest

from tests.support.gatelib import (
    P95_ROUTER_MS,
    P95_WARM_MS,
    GateHarness,
    format_table,
)


@pytest.fixture(scope="session")
def gate(miniproject, tmp_path_factory) -> GateHarness:
    harness = GateHarness(miniproject, tmp_path_factory.mktemp("evalgate"))
    yield harness
    harness.store.close()


@pytest.fixture(scope="session")
def reports(gate):
    reps = gate.reports()
    print("\nPRELIMINARY (gate deferred, D21):\n" + format_table(reps))
    return reps


def test_p95_warm_latency_reranker_on(reports):
    assert reports["hybrid+rerank"].latency_p95_ms() < P95_WARM_MS


def test_router_path_p95(reports):
    # symbol + stacktrace gold queries resolve through the router fast path
    assert reports["hybrid+rerank"].latency_p95_ms("symbol") < P95_ROUTER_MS
    assert reports["hybrid+rerank"].latency_p95_ms("stacktrace") < P95_ROUTER_MS


def test_every_gold_query_returns_results(gate):
    """Pipeline sanity: no gold query may come back empty on the real index."""
    empty = [
        q["id"]
        for q in gate.queries
        if not gate.hybrid_rerank.search(q["query"]).results
    ]
    assert empty == [], f"queries with empty responses: {empty}"


def test_embedding_cache_reused_across_runs(gate):
    """Re-embedding the unchanged real index computes zero new embeddings."""
    from repograph.embed.engine import EmbeddingEngine

    engine = EmbeddingEngine(
        gate.store, gate.engine.model_name, trust_remote_code=True
    )
    chunks = [
        c
        for blob in sorted(gate.store.active_blobs())
        for c in gate.store.chunks_for_blob(blob)
    ]
    engine.embed_chunks(chunks)
    assert engine.computed_count == 0
