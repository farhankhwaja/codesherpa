#!/usr/bin/env python3
"""Indexing throughput benchmark (CLAUDE.md §10 Phase 1: >=2000 LOC/s).

Builds a synthetic fixture-class repo (unique Python + TypeScript modules so
every blob is genuinely new), commits it, then times a cold ``sync``:
parse + chunk + store, CPU-only. Results are appended to EVAL_LOG.md by hand.

Usage::

    python tests/bench_indexing.py [n_modules] [--keep]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from repograph.gitlayer.sync import sync

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


def build_corpus(root: Path, n_modules: int) -> int:
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


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n_modules = int(args[0]) if args else 400
    keep = "--keep" in sys.argv

    tmp = Path(tempfile.mkdtemp(prefix="repograph-bench-"))
    repo = tmp / "corpus"
    repo.mkdir()
    try:
        loc = build_corpus(repo, n_modules)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env={**os.environ, **_GIT_ENV})
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env={**os.environ, **_GIT_ENV})
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "corpus"],
            cwd=repo,
            check=True,
            env={**os.environ, **_GIT_ENV},
        )

        db = tmp / "bench.db"
        started = time.perf_counter()
        stats = sync(repo, db)
        elapsed = time.perf_counter() - started

        loc_per_s = loc / elapsed
        print(f"modules:      {n_modules}")
        print(f"lines:        {loc}")
        print(f"blobs:        {stats.blobs_indexed}")
        print(f"chunks:       {stats.chunks_added}")
        print(f"cold sync:    {elapsed:.3f}s")
        print(f"throughput:   {loc_per_s:,.0f} LOC/s (target >= 2,000)")

        started = time.perf_counter()
        sync(repo, db)
        print(f"warm sync:    {time.perf_counter() - started:.3f}s (no new blobs)")
        return 0 if loc_per_s >= 2000 else 1
    finally:
        if keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
