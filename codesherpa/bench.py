"""Benchmarks behind ``sherpa bench`` (CLAUDE.md §10 Phase 1 / §13).

Two measurements, both on real data — nothing here fabricates a number:

* **indexing** — a genuine cold index of the target repo into a THROWAWAY
  database (never the repo's own ``.sherpa/index.db``), then a second sync of
  the same database to time the incremental no-op path. Reports LOC/s and
  blobs/s for the cold pass.
* **retrieval** — real queries through the repo's EXISTING index and the real
  hybrid pipeline, reporting p50/p95 against the §13 gates (router < 200 ms,
  warm < 500 ms). A warm-up query is excluded so model load is not counted as
  query latency.

``bench_synthetic`` is the fixed-workload throughput reference used for the
EVAL_LOG Phase 1/2 entries: a freshly generated corpus of unique Py+TS modules
so every blob is genuinely new. ``tests/bench_indexing.py`` is a thin CLI over
it — this module is the single implementation.
"""

from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

__all__ = [
    "IndexingResult",
    "RetrievalResult",
    "build_corpus",
    "bench_synthetic",
    "bench_repo_indexing",
    "sample_queries",
    "bench_retrieval",
    "render_indexing",
    "render_retrieval",
]

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Bench Bot",
    "GIT_AUTHOR_EMAIL": "bench@example.com",
    "GIT_COMMITTER_NAME": "Bench Bot",
    "GIT_COMMITTER_EMAIL": "bench@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}

_PY_TEMPLATE = '''\
"""Service module {n}: fixture-class code for throughput measurement."""

from dataclasses import dataclass


@dataclass
class Record{n}:
    """A row handled by service {n}."""

    key: str
    value: int
    tags: list[str]


def normalize_{n}(record: Record{n}) -> Record{n}:
    """Clamp the value and dedupe tags."""
    value = max(0, min(record.value, {upper}))
    tags = sorted(set(record.tags))
    return Record{n}(key=record.key.strip(), value=value, tags=tags)


def batch_normalize_{n}(records: list[Record{n}]) -> list[Record{n}]:
    out = []
    for record in records:
        if not record.key:
            continue
        out.append(normalize_{n}(record))
    return out


class Store{n}:
    """In-memory store used by handler {n}."""

    def __init__(self) -> None:
        self._rows: dict[str, Record{n}] = {{}}

    def put(self, record: Record{n}) -> None:
        self._rows[record.key] = normalize_{n}(record)

    def get(self, key: str) -> Record{n} | None:
        return self._rows.get(key)

    def evict_below(self, threshold: int) -> int:
        victims = [k for k, r in self._rows.items() if r.value < threshold]
        for key in victims:
            del self._rows[key]
        return len(victims)
'''

_TS_TEMPLATE = """\
// Client module {n}: fixture-class code for throughput measurement.

export interface Item{n} {{
  id: string;
  score: number;
  labels: string[];
}}

export function rank{n}(items: Item{n}[]): Item{n}[] {{
  return [...items].sort((a, b) => b.score - a.score);
}}

export function filterAbove{n}(items: Item{n}[], threshold: number): Item{n}[] {{
  const kept: Item{n}[] = [];
  for (const item of items) {{
    if (item.score >= threshold + {upper}) {{
      kept.push(item);
    }}
  }}
  return kept;
}}

export class Cache{n} {{
  private map = new Map<string, Item{n}>();

  put(item: Item{n}): void {{
    this.map.set(item.id, item);
  }}

  get(id: string): Item{n} | undefined {{
    return this.map.get(id);
  }}

  prune(threshold: number): number {{
    let removed = 0;
    for (const [id, item] of this.map) {{
      if (item.score < threshold) {{
        this.map.delete(id);
        removed += 1;
      }}
    }}
    return removed;
  }}
}}
"""


@dataclass
class IndexingResult:
    """Timings of one cold index plus one incremental no-op re-sync."""

    label: str
    lines: int
    blobs: int
    chunks: int
    symbols: int
    edges: int
    cold_seconds: float
    warm_seconds: float

    @property
    def loc_per_second(self) -> Optional[float]:
        return self.lines / self.cold_seconds if self.cold_seconds > 0 else None

    @property
    def blobs_per_second(self) -> Optional[float]:
        return self.blobs / self.cold_seconds if self.cold_seconds > 0 else None


@dataclass
class RetrievalResult:
    """Warm query latencies over the repo's existing index."""

    queries: int
    source: str
    latencies_ms: list[float] = field(default_factory=list)
    by_path_ms: dict[str, list[float]] = field(default_factory=dict)
    empty_results: int = 0

    @staticmethod
    def _pct(values: Sequence[float], q: float) -> float:
        ordered = sorted(values)
        # nearest-rank percentile: honest for the small samples a CLI run takes
        rank = max(1, min(len(ordered), int(round(q * len(ordered) + 0.5))))
        return ordered[rank - 1]

    def p50(self) -> Optional[float]:
        return statistics.median(self.latencies_ms) if self.latencies_ms else None

    def p95(self) -> Optional[float]:
        return self._pct(self.latencies_ms, 0.95) if self.latencies_ms else None


# ------------------------------------------------------------ synthetic


def build_corpus(root: Path, n_modules: int) -> int:
    """Write ``n_modules`` unique Py/TS modules under ``root``; returns line count."""
    total_lines = 0
    for i in range(n_modules):
        if i % 2 == 0:
            rel = root / "pyserver" / f"service_{i}.py"
            body = _PY_TEMPLATE.format(n=i, upper=1000 + i)
        else:
            rel = root / "webapp" / "src" / f"client_{i}.ts"
            body = _TS_TEMPLATE.format(n=i, upper=i)
        rel.parent.mkdir(parents=True, exist_ok=True)
        rel.write_text(body, encoding="utf-8")
        total_lines += body.count("\n")
    return total_lines


def bench_synthetic(n_modules: int = 400, keep: bool = False) -> IndexingResult:
    """Cold-index a freshly generated corpus: the fixed-workload throughput
    reference (every blob genuinely new, so nothing is served from cache)."""
    from codesherpa.gitlayer.sync import sync

    tmp = Path(tempfile.mkdtemp(prefix="sherpa-bench-"))
    repo = tmp / "corpus"
    repo.mkdir()
    try:
        lines = build_corpus(repo, n_modules)
        env = {**os.environ, **_GIT_ENV}
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "corpus"],
            cwd=repo,
            check=True,
            env=env,
        )

        db = tmp / "bench.db"
        started = time.perf_counter()
        stats = sync(repo, db)
        cold = time.perf_counter() - started

        started = time.perf_counter()
        sync(repo, db)
        warm = time.perf_counter() - started

        return IndexingResult(
            label=f"synthetic corpus ({n_modules} modules)",
            lines=lines,
            blobs=stats.blobs_indexed,
            chunks=stats.chunks_added,
            symbols=stats.symbols_indexed,
            edges=stats.edges_indexed,
            cold_seconds=cold,
            warm_seconds=warm,
        )
    finally:
        if keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------- this repo


def bench_repo_indexing(repo_root: Path) -> IndexingResult:
    """Cold-index ``repo_root`` into a throwaway DB, then time a no-op re-sync.

    The repo's own ``.sherpa/index.db`` is never opened or written: the whole
    point is to measure a real cold build without disturbing the live index.
    """
    from codesherpa.gitlayer.sync import sync

    tmp = Path(tempfile.mkdtemp(prefix="sherpa-bench-repo-"))
    try:
        db = tmp / "bench.db"
        started = time.perf_counter()
        stats = sync(repo_root, db)
        cold = time.perf_counter() - started

        started = time.perf_counter()
        sync(repo_root, db)
        warm = time.perf_counter() - started

        return IndexingResult(
            label=str(repo_root),
            lines=stats.lines_indexed,
            blobs=stats.blobs_indexed,
            chunks=stats.chunks_added,
            symbols=stats.symbols_indexed,
            edges=stats.edges_indexed,
            cold_seconds=cold,
            warm_seconds=warm,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sample_queries(store, limit: int) -> list[str]:
    """Deterministic symbol-name queries drawn from the index itself.

    Real strings from the indexed repo (not invented): the most-referenced
    definitions, which is what an agent actually looks up. Ordering is by
    (incoming edge count desc, symbol) so repeated runs are comparable.
    """
    rows = store.conn.execute(
        """
        SELECT s.symbol, COUNT(e.dst) AS refs
        FROM symbols s
        JOIN blobs b ON b.blob_hash = s.blob_hash AND b.active = 1
        LEFT JOIN edges e ON e.dst = s.node_id
        WHERE s.kind IN ('function', 'class', 'method')
          AND LENGTH(s.symbol) >= 3
        GROUP BY s.symbol
        ORDER BY refs DESC, s.symbol ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [row[0] for row in rows]


def bench_retrieval(retriever, queries: Sequence[str], budget_tokens: int = 4000,
                    source: str = "index symbols") -> RetrievalResult:
    """Time ``queries`` through the real pipeline; first query is a warm-up."""
    result = RetrievalResult(queries=len(queries), source=source)
    if not queries:
        return result
    retriever.search(queries[0], budget_tokens=budget_tokens)  # warm-up, not timed
    for query in queries:
        started = time.perf_counter()
        packed = retriever.search(query, budget_tokens=budget_tokens)
        elapsed_ms = (time.perf_counter() - started) * 1000
        result.latencies_ms.append(elapsed_ms)
        path = getattr(retriever, "last_search_path", None) or "unknown"
        result.by_path_ms.setdefault(path, []).append(elapsed_ms)
        if not packed.results:
            result.empty_results += 1
    return result


# ---------------------------------------------------------------- render


def render_indexing(result: IndexingResult) -> str:
    loc = result.loc_per_second
    blobs = result.blobs_per_second
    lines = [
        f"indexing  {result.label}",
        f"  cold index    {result.cold_seconds:8.2f}s  "
        f"{result.blobs} blobs, {result.chunks} chunks, {result.lines} lines",
        f"  re-sync       {result.warm_seconds:8.2f}s  (no new blobs)",
    ]
    if loc is not None and blobs is not None:
        lines.append(
            f"  throughput    {loc:>8,.0f} LOC/s   {blobs:,.0f} blobs/s  (target >= 2,000 LOC/s)"
        )
    lines.append(f"  graph         {result.symbols} symbols, {result.edges} edges")
    return "\n".join(lines)


def render_retrieval(result: RetrievalResult) -> str:
    if not result.latencies_ms:
        return "retrieval  no queries to run (index has no symbols yet)"
    lines = [
        f"retrieval  {result.queries} queries ({result.source}), warm, warm-up excluded",
        f"  p50           {result.p50():8.1f} ms",
        f"  p95           {result.p95():8.1f} ms  (gate: < 500 ms)",
    ]
    for path in sorted(result.by_path_ms):
        values = result.by_path_ms[path]
        gate = "  (gate: < 200 ms)" if path == "router" else ""
        lines.append(
            f"  {path:<10}    {statistics.median(values):8.1f} ms p50, "
            f"{RetrievalResult._pct(values, 0.95):.1f} ms p95, n={len(values)}{gate}"
        )
    if result.empty_results:
        lines.append(f"  empty         {result.empty_results} queries returned no chunks")
    return "\n".join(lines)
