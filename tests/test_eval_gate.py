"""Phase 3 eval gate (CLAUDE.md §10/§13) on the REAL index (gitlayer -> cAST
-> SQLite store -> symbol graph) with the real embedding model and
cross-encoder (downloads on first run, cached under ~/.cache/sherpa/).

GATE STATUS: ARMED. Grading was briefly deferred (human instruction
2026-07-04) while the original 25-query gold set saturated every baseline
(BM25-only reached recall@5 = 1.00 — query/code vocabulary overlap). The
hardened set (+8 vocabulary-mismatch NL queries, +2 lexical decoys, 35
total) landed on main the same day, so the gate is asserted twice below,
thresholds unmodified:

1. The OFFICIAL gate: ``eval/run_eval.py --mode all`` (Phase 4's harness,
   D17 factory contract, file-level hits) must exit 0.
2. This module's internal harness: same §13 thresholds under the STRICTER
   symbol-aware relevance (a hit must come from an expected file AND mention
   an expected symbol), plus the latency gates.

History: DECISIONS D21 (gold-set hardening), D22-D26, EVAL_LOG.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.gatelib import (
    MRR_THRESHOLD,
    P95_ROUTER_MS,
    P95_WARM_MS,
    RECALL5_THRESHOLD,
    GateHarness,
    format_table,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def gate(miniproject, tmp_path_factory) -> GateHarness:
    harness = GateHarness(miniproject, tmp_path_factory.mktemp("evalgate"))
    yield harness
    harness.store.close()


@pytest.fixture(scope="session")
def reports(gate):
    reps = gate.reports()
    print("\n" + format_table(reps))  # the EVAL_LOG source table
    return reps


# -------------------------------------------------------- official §13 gate


def test_official_eval_gate_passes(miniproject, tmp_path_factory):
    """`python eval/run_eval.py --repo <fixture clone> --mode all` exits 0.

    This is THE Phase 3 gate as written in §10: recall@5 >= 0.80, MRR >=
    0.60, hybrid strictly beats bm25-only and vector-only. Thresholds are
    frozen constants inside run_eval.py (Phase 4's harness, D17)."""
    work = tmp_path_factory.mktemp("officialgate")
    repo = work / "repo"
    shutil.copytree(miniproject, repo)
    shutil.rmtree(repo / ".sherpa", ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run_eval.py"),
         "--repo", str(repo), "--mode", "all"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=1200,
    )
    assert proc.returncode == 0, f"gate failed:\n{proc.stdout}\n{proc.stderr[-2000:]}"
    assert "GATE: PASS" in proc.stdout
    print("\n" + proc.stdout.strip())  # the EVAL_LOG source table


# ------------------------------------- internal harness: §13 quality (strict
# symbol-aware relevance — stricter than the official file-level hits)


def test_recall_at_5_threshold(reports):
    assert reports["hybrid+rerank"].recall_at_5 >= RECALL5_THRESHOLD


def test_mrr_threshold(reports):
    assert reports["hybrid+rerank"].mrr >= MRR_THRESHOLD


def test_hybrid_strictly_beats_bm25_only(reports):
    assert reports["hybrid+rerank"].recall_at_5 > reports["bm25-only"].recall_at_5


def test_hybrid_strictly_beats_vector_only(reports):
    assert reports["hybrid+rerank"].recall_at_5 > reports["vector-only"].recall_at_5


# ---------------------------------------------------------------- §13 latency

_LATENCY_BUDGET_SCALE = float(os.environ.get("SHERPA_LATENCY_BUDGET_SCALE", "1.0"))
"""§13 latency thresholds are defined on reference hardware — the EVAL_LOG
numbers (p95 178 ms) were measured on an Apple M-series CPU, where the
unscaled gates bind (every local/verifier run). CI's shared runner measured
1,764 ms for the identical suite, so ci.yml sets
SHERPA_LATENCY_BUDGET_SCALE=4: hardware calibration, NOT a threshold
reduction (D41). Applied ONLY to the latency assertions below — every
recall/MRR/memory/golden assertion is unconditional and unscaled. The
measured p95 and effective budget are printed either way so CI logs surface
latency drift on the runner."""


def test_p95_warm_latency_reranker_on(reports):
    p95 = reports["hybrid+rerank"].latency_p95_ms()
    budget = P95_WARM_MS * _LATENCY_BUDGET_SCALE
    print(
        f"\n[latency] warm p95 = {p95:.1f} ms; budget = {budget:.0f} ms "
        f"({P95_WARM_MS} ms x scale {_LATENCY_BUDGET_SCALE})"
    )
    assert p95 < budget, (
        f"warm p95 {p95:.0f} ms >= budget {budget:.0f} ms "
        f"({P95_WARM_MS} ms x hardware scale {_LATENCY_BUDGET_SCALE} — D41)"
    )


def test_router_path_p95(reports):
    # symbol + stacktrace gold queries resolve through the router fast path
    budget = P95_ROUTER_MS * _LATENCY_BUDGET_SCALE
    p95_symbol = reports["hybrid+rerank"].latency_p95_ms("symbol")
    p95_stack = reports["hybrid+rerank"].latency_p95_ms("stacktrace")
    print(
        f"\n[latency] router p95: symbol = {p95_symbol:.1f} ms, "
        f"stacktrace = {p95_stack:.1f} ms; budget = {budget:.0f} ms "
        f"({P95_ROUTER_MS} ms x scale {_LATENCY_BUDGET_SCALE})"
    )
    assert p95_symbol < budget
    assert p95_stack < budget


# ------------------------------------------------------------------- sanity


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
    from codesherpa.embed.engine import EmbeddingEngine

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
