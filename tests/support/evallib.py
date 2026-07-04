"""Eval metrics for the gold query set: recall@5, MRR, latency percentiles.

Used by the Phase 3 eval-gate test and the embedding-model benchmark. The
graph-mcp worktree owns eval/run_eval.py (CLAUDE.md §8); this module is
importable from there once worktrees merge — proposed in PROGRESS.md.

Relevance is **symbol-aware**: a result is relevant when its chunk comes from
one of the query's expected_files AND mentions one of the expected_symbols
(in breadcrumb or code). File-only relevance saturates on the fixture
(vector-only reaches recall@5 = 1.00), which would make the "hybrid strictly
beats single methods" gate meaningless; symbol-aware relevance measures what
repograph is actually for — returning the right *function*, not just the
right file. See DECISIONS.md.

Ranks are 1-based positions in the returned result order (what a calling
agent actually sees).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

RECALL_AT = 5


class ChunkLike(Protocol):
    file_path: str
    breadcrumb: str
    code: str


RankedChunks = Callable[[str], list["ChunkLike"]]
"""query -> ordered chunks of returned results (duplicates allowed)."""


def is_relevant(chunk: ChunkLike, gold: dict) -> bool:
    if chunk.file_path not in set(gold["expected_files"]):
        return False
    symbols = gold.get("expected_symbols") or []
    if not symbols:
        return True
    return any(s in chunk.breadcrumb or s in chunk.code for s in symbols)


@dataclass
class QueryOutcome:
    query_id: str
    query_type: str
    first_relevant_rank: int | None  # 1-based; None = not found
    latency_s: float
    top_files: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    name: str
    outcomes: list[QueryOutcome]

    @property
    def recall_at_5(self) -> float:
        hits = sum(
            1 for o in self.outcomes
            if o.first_relevant_rank is not None and o.first_relevant_rank <= RECALL_AT
        )
        return hits / len(self.outcomes) if self.outcomes else 0.0

    @property
    def mrr(self) -> float:
        total = sum(
            1.0 / o.first_relevant_rank
            for o in self.outcomes
            if o.first_relevant_rank is not None
        )
        return total / len(self.outcomes) if self.outcomes else 0.0

    def latency_p95_ms(self, query_type: str | None = None) -> float:
        lats = sorted(
            o.latency_s for o in self.outcomes
            if query_type is None or o.query_type == query_type
        )
        if not lats:
            return 0.0
        return lats[min(len(lats) - 1, int(0.95 * (len(lats) - 1) + 0.999))] * 1000

    def misses(self) -> list[QueryOutcome]:
        return [
            o for o in self.outcomes
            if o.first_relevant_rank is None or o.first_relevant_rank > RECALL_AT
        ]

    def row(self) -> str:
        return (
            f"{self.name:<24} recall@5={self.recall_at_5:.2f} "
            f"MRR={self.mrr:.3f} p95={self.latency_p95_ms():.0f}ms"
        )


def load_gold_queries(path: Path) -> list[dict]:
    queries = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def evaluate(
    name: str,
    queries: list[dict],
    ranked_chunks_fn: RankedChunks,
    *,
    warmup: str | None = "warmup query",
) -> EvalReport:
    """Run every gold query through ``ranked_chunks_fn`` and score it."""
    if warmup is not None:
        ranked_chunks_fn(warmup)  # exclude model warm-up from latency
    outcomes: list[QueryOutcome] = []
    for q in queries:
        start = time.perf_counter()
        chunks = ranked_chunks_fn(q["query"])
        elapsed = time.perf_counter() - start
        rank = next(
            (i for i, c in enumerate(chunks, start=1) if is_relevant(c, q)),
            None,
        )
        outcomes.append(
            QueryOutcome(
                query_id=q["id"],
                query_type=q.get("type", "?"),
                first_relevant_rank=rank,
                latency_s=elapsed,
                top_files=[c.file_path for c in chunks[:RECALL_AT]],
            )
        )
    return EvalReport(name=name, outcomes=outcomes)
