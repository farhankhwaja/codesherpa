# Eval Log

Append-only. Every entry: date, commit, phase, metric, value. Never edit or
remove past entries. Thresholds live in CLAUDE.md §13 and may never be lowered.

## 2026-07-04 — Phase 1 — indexing throughput (worktree core-index, pre-merge)

Benchmark: `python tests/bench_indexing.py` (synthetic fixture-class Py+TS
corpus, cold sync = parse + chunk + store, CPU-only, Apple Silicon; line-window
chunker — Phase 2 re-measures with tree-sitter cAST).

| corpus | LOC | cold sync | throughput | warm sync (no new blobs) |
|---|---|---|---|---|
| 400 modules | 18,200 | 0.096 s | 189,338 LOC/s | 0.018 s |
| 1,000 modules | 45,500 | 0.227 s | 200,836 LOC/s | 0.041 s |

Target ≥ 2,000 LOC/s: **PASS** (~100×).

## 2026-07-04 — Phase 2 — indexing throughput with cAST (worktree core-index, pre-merge)

Same benchmark as Phase 1 (`tests/bench_indexing.py`), now with tree-sitter
parsing + cAST split-then-merge on the hot path for Py/TS:

| corpus | LOC | cold sync | throughput | warm sync |
|---|---|---|---|---|
| 400 modules | 18,200 | 0.120 s | 151,880 LOC/s | 0.018 s |
| 1,000 modules | 45,500 | 0.297 s | 153,362 LOC/s | 0.044 s |

Target ≥ 2,000 LOC/s: **PASS** (~75×). Parsing costs ~25% vs the line-window
chunker; full suite (88 tests incl. golden) green.
