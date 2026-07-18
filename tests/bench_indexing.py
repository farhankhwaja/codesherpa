#!/usr/bin/env python3
"""Indexing throughput benchmark (CLAUDE.md §10 Phase 1: >=2000 LOC/s).

Thin CLI over :func:`codesherpa.bench.bench_synthetic` — the implementation
lives in ``codesherpa/bench.py`` so ``sherpa bench`` and this script measure
exactly the same thing. Results are appended to EVAL_LOG.md by hand.

Usage::

    python tests/bench_indexing.py [n_modules] [--keep]
"""

from __future__ import annotations

import sys

from codesherpa.bench import bench_synthetic


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n_modules = int(args[0]) if args else 400
    result = bench_synthetic(n_modules, keep="--keep" in sys.argv)

    print(f"modules:      {n_modules}")
    print(f"lines:        {result.lines}")
    print(f"blobs:        {result.blobs}")
    print(f"chunks:       {result.chunks}")
    print(f"cold sync:    {result.cold_seconds:.3f}s")
    print(f"throughput:   {result.loc_per_second:,.0f} LOC/s (target >= 2,000)")
    print(f"warm sync:    {result.warm_seconds:.3f}s (no new blobs)")
    return 0 if (result.loc_per_second or 0) >= 2000 else 1


if __name__ == "__main__":
    sys.exit(main())
