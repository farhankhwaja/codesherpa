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

## 2026-07-04 — Phase 4 (graph-mcp worktree, pre-rebase) — informational retrieval baseline
Naive keyword retriever (tests/simple_retriever.py: router + term-count FTS,
no embeddings/reranker) on eval/gold_queries.jsonl over the miniproject
fixture, via eval/run_eval.py `evaluate()`:

| metric | value |
|---|---|
| recall@5 | 0.680 |
| MRR | 0.620 |
| p50 warm | 0.3 ms |
| p95 warm | 0.4 ms |
| recall by type | nl 0.57 · stacktrace 0.50 · symbol 1.00 |

NOT a gate run (thresholds apply to the Phase 3 hybrid pipeline). Recorded
as the floor the real pipeline must clearly beat; misses were q03 q04 q05
q07 q10 q14 q22 q24 (all natural-language/stack-trace queries — semantic
search is exactly what's missing).

## 2026-07-04 — Phase 4 — graph integration + hardened gold set (worktree graph-mcp, pre-merge)

Gold set hardened to 35 queries (+8 nl_hard vocabulary-mismatch, +2 decoy;
merged to main separately as bb9e0d6). Stand-in retriever = tests-only
SimpleRetriever (router + FTS5 bm25, no embeddings/reranker) over the REAL
SQLite index built by real sync; via eval/run_eval.py `evaluate()`:

| metric | expansion OFF | expansion ON |
|---|---|---|
| recall@5 | 0.686 | 0.686 |
| MRR | 0.649 | 0.649 |
| p50 / p95 warm | 0.1 / 0.2 ms | 0.4 / 0.6 ms |
| recall by type | nl 0.93 · nl_hard 0.12 · decoy 0.50 · symbol 1.00 · stacktrace 0.50 | identical |

Phase 4 §13 gate — graph expansion must not reduce recall@5: **PASS**
(delta 0.000; also asserted permanently by
tests/test_run_eval.py::test_graph_expansion_does_not_reduce_recall).
NOT a Phase 3 gate run: recall/MRR thresholds bind the hybrid pipeline.
nl_hard at 0.12 for a lexical retriever is by design — it is the headroom
embeddings must close.

Golden Test with symbols+edges projections: default run green; GOLDEN_DEEP=1
soak green (25/25 randomized examples, this workstation).
