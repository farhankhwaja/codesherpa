#!/usr/bin/env python3
"""Retrieval eval harness: recall@5, MRR, latency against the gold set.

Usage (Phase 3 gate, CLAUDE.md §10/§13)::

    python eval/run_eval.py --repo tests/fixtures/miniproject \\
        --retriever codesherpa.retrieve:build_eval_retriever [--mode all]

The ``--retriever`` factory is ``module:attr`` resolving to
``factory(repo_path: str, mode: str) -> Retriever`` where mode is one of
``hybrid | bm25 | vector`` (the Phase 3 pipeline must expose all three so
the comparison gate can run).

Exit status: 0 only if the gate passes —
  * hybrid recall@5 >= 0.80 and MRR >= 0.60, and
  * with ``--mode all``: hybrid recall@5 strictly beats bm25-only and
    vector-only.

THRESHOLDS ARE FROZEN (§13: "may never be edited downward").
"""

from __future__ import annotations

import argparse
import importlib
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# §13 — frozen. Never lower these.
RECALL_AT_5_MIN = 0.80
MRR_MIN = 0.60
DEFAULT_K = 5

_MODES = ("hybrid", "bm25", "vector")


@dataclass(frozen=True)
class GoldQuery:
    id: str
    type: str  # nl | symbol | stacktrace
    query: str
    expected_files: tuple[str, ...]
    expected_symbols: tuple[str, ...]


@dataclass
class EvalReport:
    mode: str
    recall_at_k: float
    mrr: float
    k: int
    p50_ms: float
    p95_ms: float
    per_type_recall: dict[str, float] = field(default_factory=dict)
    misses: list[str] = field(default_factory=list)


def load_gold(path: Path) -> list[GoldQuery]:
    gold = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gold.append(
                GoldQuery(
                    id=row["id"],
                    type=row["type"],
                    query=row["query"],
                    expected_files=tuple(row["expected_files"]),
                    expected_symbols=tuple(row.get("expected_symbols", ())),
                )
            )
    if len(gold) < 20:
        raise SystemExit(f"gold set has only {len(gold)} entries; need >= 20")
    return gold


def _first_hit_rank(result_paths: Iterable[str], expected_files: tuple[str, ...]) -> int:
    """1-based rank of the first correct result, 0 if absent."""
    for rank, path in enumerate(result_paths, start=1):
        if path in expected_files:
            return rank
    return 0


def evaluate(retriever, gold: list[GoldQuery], mode: str = "hybrid", k: int = DEFAULT_K) -> EvalReport:
    """Run every gold query through ``retriever.search`` and score it.

    Latency is measured warm: each query runs once unmeasured, then once
    measured.
    """
    ranks: list[int] = []
    latencies: list[float] = []
    hits_by_type: dict[str, list[bool]] = {}
    misses: list[str] = []
    for entry in gold:
        retriever.search(entry.query)  # warmup
        start = time.perf_counter()
        packed = retriever.search(entry.query)
        latencies.append((time.perf_counter() - start) * 1000.0)
        paths = [r.chunk.file_path for r in packed.results[:k]]
        rank = _first_hit_rank(paths, entry.expected_files)
        ranks.append(rank)
        hits_by_type.setdefault(entry.type, []).append(rank > 0)
        if rank == 0:
            misses.append(entry.id)
    total = len(gold)
    return EvalReport(
        mode=mode,
        recall_at_k=sum(1 for r in ranks if r > 0) / total,
        mrr=sum(1.0 / r for r in ranks if r > 0) / total,
        k=k,
        p50_ms=statistics.median(latencies),
        p95_ms=sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)],
        per_type_recall={
            t: sum(hits) / len(hits) for t, hits in sorted(hits_by_type.items())
        },
        misses=misses,
    )


def gate(reports: dict[str, EvalReport]) -> tuple[bool, list[str]]:
    """Apply the §13 thresholds. Returns (passed, reasons_for_failure)."""
    reasons = []
    hybrid = reports.get("hybrid")
    if hybrid is None:
        reasons.append("no hybrid run to gate on")
        return False, reasons
    if hybrid.recall_at_k < RECALL_AT_5_MIN:
        reasons.append(f"hybrid recall@{hybrid.k} {hybrid.recall_at_k:.3f} < {RECALL_AT_5_MIN}")
    if hybrid.mrr < MRR_MIN:
        reasons.append(f"hybrid MRR {hybrid.mrr:.3f} < {MRR_MIN}")
    for baseline in ("bm25", "vector"):
        if baseline in reports and hybrid.recall_at_k <= reports[baseline].recall_at_k:
            reasons.append(
                f"hybrid recall@{hybrid.k} {hybrid.recall_at_k:.3f} does not beat "
                f"{baseline} ({reports[baseline].recall_at_k:.3f})"
            )
    return not reasons, reasons


def format_table(reports: dict[str, EvalReport]) -> str:
    lines = [
        f"{'mode':<8} {'recall@5':>9} {'MRR':>7} {'p50 ms':>8} {'p95 ms':>8}  misses",
        "-" * 60,
    ]
    for mode in _MODES:
        report = reports.get(mode)
        if report is None:
            continue
        lines.append(
            f"{report.mode:<8} {report.recall_at_k:>9.3f} {report.mrr:>7.3f} "
            f"{report.p50_ms:>8.1f} {report.p95_ms:>8.1f}  {','.join(report.misses) or '-'}"
        )
    for mode, report in reports.items():
        if mode == "hybrid":
            per_type = "  ".join(f"{t}={v:.2f}" for t, v in report.per_type_recall.items())
            lines.append(f"hybrid recall by query type: {per_type}")
    return "\n".join(lines)


def _load_factory(spec: str) -> Callable:
    module_name, _sep, attr = spec.partition(":")
    if not attr:
        raise SystemExit(f"--retriever must look like module:attr, got {spec!r}")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="Path of the indexed repo to query.")
    parser.add_argument(
        "--retriever",
        default="codesherpa.retrieve:build_eval_retriever",
        help="Factory 'module:attr' with signature (repo_path, mode) -> Retriever.",
    )
    parser.add_argument("--mode", choices=[*_MODES, "all"], default="all")
    parser.add_argument(
        "--gold", default=str(Path(__file__).parent / "gold_queries.jsonl")
    )
    args = parser.parse_args(argv)

    gold = load_gold(Path(args.gold))
    factory = _load_factory(args.retriever)
    modes = list(_MODES) if args.mode == "all" else [args.mode]
    reports = {mode: evaluate(factory(args.repo, mode), gold, mode=mode) for mode in modes}

    print(format_table(reports))
    passed, reasons = gate(reports)
    if passed:
        print("GATE: PASS")
        return 0
    print("GATE: FAIL")
    for reason in reasons:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
