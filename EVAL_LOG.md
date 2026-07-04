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

## 2026-07-04 — Phase 3 (retrieval worktree, pre-integration) — commit: (this commit)

Setup: miniproject fixture indexed by the test-support indexer (93 chunks, 31
blobs, 114 symbols, 213 edges) into the in-memory contract store; real models,
CPU-only, Apple M-series. Relevance is symbol-aware (DECISIONS D24). 25 gold
queries. Integration re-run against the real store is required before merge.

### Embedding model benchmark (vector-only channel, DECISIONS D25)
| model | recall@5 | MRR | embed 93 chunks |
|---|---|---|---|
| nomic-embed-text-v1.5 (winner) | 1.00 | 0.867 | 38.7 s |
| jina-embeddings-v2-base-code (disqualified: transformers≥5 incompat) | 1.00 | 0.890 | 51.6 s |
| all-MiniLM-L6-v2 (fallback) | 0.92 | 0.831 | 5.3 s |

### Phase 3 eval gate (embed=nomic, reranker=ms-marco-MiniLM-L-6-v2, rerank_top=30, 1000-char passages)
| method | recall@5 | MRR | p95 warm |
|---|---|---|---|
| hybrid+rerank | 1.00 | 0.873 | 444 ms |
| hybrid-norerank | 0.96 | 0.905 | 29 ms |
| bm25-only | 0.96 | 0.745 | 3 ms |
| vector-only | 1.00 | 0.867 | 29 ms |

- recall@5 = 1.00 ≥ 0.80 ✓; MRR = 0.873 ≥ 0.60 ✓
- hybrid+rerank > bm25-only on recall@5 (1.00 > 0.96) ✓
- hybrid+rerank vs vector-only: 1.00 = 1.00 — **tie at ceiling; strict > is
  structurally impossible on this gold set** (see BLOCKED.md; needs harder
  gold queries, eval/ is graph-mcp-owned)
- p95 warm (reranker on) 444 ms < 500 ms ✓ (was 758 ms at depth 50/1200 chars)
- router path (symbol + stacktrace queries) p95 ≈ 0–1 ms < 200 ms ✓
- embedding cache: re-embed of unchanged fixture computes 0 new embeddings ✓

### Reranker comparison (same pipeline, gold set)
| reranker | recall@5 | MRR | p95 warm |
|---|---|---|---|
| ms-marco-MiniLM-L-6-v2 (chosen) | 1.00 | 0.873 | 444 ms |
| bge-reranker-v2-m3 (§6 primary) | 1.00 | 0.907 | 6696 ms |

bge-reranker-v2-m3 wins on MRR (+0.034) but is 13× over the §13 500 ms warm
p95 gate on CPU (568M params) — §9 fallback to the MiniLM cross-encoder taken,
`TODO(upgrade)` recorded (D9): revisit bge on GPU/quantized runtimes.
