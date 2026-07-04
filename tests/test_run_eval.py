"""Phase 4: eval harness unit tests (metric math, gate, CLI plumbing),
plus the §10/§13 graph-expansion delta on the real store.

The recall/MRR thresholds gate Phase 3 (retrieval pipeline); here we prove
the harness math and exit behavior with controlled fake retrievers, and run
the expansion-on vs expansion-off comparison over the real SQLite index.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from repograph.contracts.retrieval_contract import Retriever
from repograph.contracts.types import Chunk, PackedContext, RetrievalSource, SearchResult
from repograph.graph.view import SymbolGraph
from repograph.store.sqlite_store import SQLiteIndexStore
from simple_retriever import SimpleRetriever

ROOT = Path(__file__).parent.parent
GOLD_PATH = ROOT / "eval" / "gold_queries.jsonl"

_spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
sys.modules["run_eval"] = run_eval  # dataclasses resolve annotations via sys.modules
_spec.loader.exec_module(run_eval)


def _result(path: str) -> SearchResult:
    chunk = Chunk(
        blob_hash="f" * 40,
        byte_start=0,
        byte_end=10,
        file_path=path,
        language="python",
        code="x" * 10,
        breadcrumb=f"# {path}",
    )
    return SearchResult(
        chunk=chunk,
        score=1.0,
        source=RetrievalSource.BM25,
        expand_id=chunk.chunk_id,
        token_count=5,
    )


class _CannedRetriever(Retriever):
    """Answers every query with a canned list of file paths."""

    def __init__(self, paths_for_query) -> None:
        self._paths_for_query = paths_for_query

    def search(self, query: str, budget_tokens: int = 4000) -> PackedContext:
        results = tuple(_result(p) for p in self._paths_for_query(query))
        return PackedContext(query, budget_tokens, sum(r.token_count for r in results), results)

    def get_definition(self, symbol):  # pragma: no cover - unused in eval
        return []

    def get_callers(self, symbol, limit=10):  # pragma: no cover
        return []

    def get_references(self, symbol, limit=20):  # pragma: no cover
        return []

    def expand(self, expand_id):  # pragma: no cover
        return None


def _gold_map() -> dict[str, list[str]]:
    with open(GOLD_PATH, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return {row["query"]: row["expected_files"] for row in rows}


def _perfect(query: str) -> list[str]:
    return _gold_map()[query][:1]


def _rank3(query: str) -> list[str]:
    return ["wrong/a.py", "wrong/b.py"] + _gold_map()[query][:1]


def _empty(query: str) -> list[str]:
    return []


def build_fake(repo: str, mode: str) -> Retriever:
    """Factory used by the CLI test: hybrid perfect, baselines empty."""
    return _CannedRetriever(_perfect if mode == "hybrid" else _empty)


def build_all_empty(repo: str, mode: str) -> Retriever:
    return _CannedRetriever(_empty)


def test_thresholds_are_frozen_values():
    # §13 ratchet: these constants may never go down
    assert run_eval.RECALL_AT_5_MIN == 0.80
    assert run_eval.MRR_MIN == 0.60


def test_gold_set_loads():
    gold = run_eval.load_gold(GOLD_PATH)
    assert len(gold) >= 20
    types = {g.type for g in gold}
    assert {"nl", "symbol", "stacktrace"} <= types


def test_perfect_retriever_scores_one():
    gold = run_eval.load_gold(GOLD_PATH)
    report = run_eval.evaluate(_CannedRetriever(_perfect), gold)
    assert report.recall_at_k == 1.0
    assert report.mrr == 1.0
    assert report.misses == []


def test_rank3_mrr_is_one_third():
    gold = run_eval.load_gold(GOLD_PATH)
    report = run_eval.evaluate(_CannedRetriever(_rank3), gold)
    assert report.recall_at_k == 1.0
    assert report.mrr == pytest.approx(1 / 3)


def test_empty_retriever_scores_zero():
    gold = run_eval.load_gold(GOLD_PATH)
    report = run_eval.evaluate(_CannedRetriever(_empty), gold)
    assert report.recall_at_k == 0.0
    assert report.mrr == 0.0
    assert len(report.misses) == len(gold)


def test_gate_requires_hybrid_to_beat_baselines():
    gold = run_eval.load_gold(GOLD_PATH)
    hybrid = run_eval.evaluate(_CannedRetriever(_perfect), gold, mode="hybrid")
    bm25 = run_eval.evaluate(_CannedRetriever(_empty), gold, mode="bm25")
    tie = run_eval.evaluate(_CannedRetriever(_perfect), gold, mode="bm25")

    passed, _ = run_eval.gate({"hybrid": hybrid, "bm25": bm25})
    assert passed
    passed, reasons = run_eval.gate({"hybrid": hybrid, "bm25": tie})
    assert not passed and any("does not beat" in r for r in reasons)
    passed, reasons = run_eval.gate({"bm25": bm25})
    assert not passed


def test_cli_pass_and_fail_paths(miniproject: Path):
    argv = ["--repo", str(miniproject), "--retriever", "test_run_eval:build_fake", "--mode", "all"]
    assert run_eval.main(argv) == 0
    argv = ["--repo", str(miniproject), "--retriever", "test_run_eval:build_all_empty"]
    assert run_eval.main(argv) == 1


def test_smoke_simple_retriever_on_real_store(synced_miniproject: tuple[Path, Path]):
    """Informational: the naive test retriever over the real index produces
    sane metrics."""
    _repo, db = synced_miniproject
    store = SQLiteIndexStore(db)
    try:
        retriever = SimpleRetriever(store, SymbolGraph(store))
        gold = run_eval.load_gold(GOLD_PATH)
        report = run_eval.evaluate(retriever, gold)
        assert 0.0 <= report.recall_at_k <= 1.0
        assert 0.0 <= report.mrr <= report.recall_at_k
        assert report.p50_ms <= report.p95_ms
    finally:
        store.close()


def test_graph_expansion_does_not_reduce_recall(synced_miniproject: tuple[Path, Path]):
    """§10 Phase 4 / §13: graph expansion (config flag) must not reduce
    recall@5. Runs on the harness stand-in retriever over the real store;
    Phase 3 re-runs this comparison inside the production pipeline."""
    _repo, db = synced_miniproject
    store = SQLiteIndexStore(db)
    try:
        graph = SymbolGraph(store)
        gold = run_eval.load_gold(GOLD_PATH)
        base = run_eval.evaluate(SimpleRetriever(store, graph, expansion=False), gold)
        expanded = run_eval.evaluate(SimpleRetriever(store, graph, expansion=True), gold)
        assert expanded.recall_at_k >= base.recall_at_k, (
            f"expansion reduced recall@5: {base.recall_at_k:.3f} -> "
            f"{expanded.recall_at_k:.3f}"
        )
    finally:
        store.close()
