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
`TODO(upgrade)` recorded (D26): revisit bge on GPU/quantized runtimes.

## 2026-07-04 — Phase 3 FINAL — integrated pipeline, hardened gold set — commit: (this commit)

Setup: real pipeline end to end (fixture clone -> gitlayer sync -> cAST
chunker -> symbol graph -> SQLite store with FTS5 + sqlite-vec; 34 active
blobs/chunks, 128 symbols, 250 edges; nothing mocked), nomic-embed-text-v1.5
+ ms-marco-MiniLM-L-6-v2 at the shipping defaults (rerank depth 20, 700-char
query-focused passages, CE+vector rank blend w=4 — D27), 35 hardened gold
queries (D21). CPU-only, Apple M-series.

### PRELIMINARY numbers during the gate deferral window (for the record)
While the original 25-query set was known-saturated (human instruction to
defer grading), the integrated pipeline measured: hybrid+rerank 1.00/0.980,
hybrid-norerank 1.00/0.980, bm25-only 1.00/0.833, vector-only 1.00/0.930
(symbol-aware relevance) — every method at the recall@5 ceiling, confirming
the deferral. The hardened set landed the same day; the gate was re-armed.

### OFFICIAL §13 gate — eval/run_eval.py --mode all (file-level hits)
| mode | recall@5 | MRR | p50 | p95 | misses |
|---|---|---|---|---|---|
| hybrid | **0.971** | **0.877** | 168 ms | 178 ms | q28 |
| bm25-only | 0.771 | 0.630 | 0.2 ms | 0.3 ms | 8 queries |
| vector-only | 0.829 | 0.738 | 18 ms | 25 ms | 6 queries |

- recall@5 0.971 ≥ 0.80 ✓; MRR 0.877 ≥ 0.60 ✓
- hybrid strictly beats bm25-only (0.971 > 0.771) and vector-only
  (0.971 > 0.829) ✓ — **GATE: PASS** (exit 0)
- hybrid recall by type: nl 1.00, symbol 1.00, stacktrace 1.00, decoy 1.00,
  nl_hard 0.88 (q28 "avoid asking the backend twice…" -> MemoCache is the
  one remaining miss: no channel ranks it top-5; honest limitation)

### Internal harness (symbol-aware relevance — stricter; D24)
hybrid+rerank 0.971 recall@5 / 0.844 MRR vs vector-only 0.943 / 0.830,
bm25-only 0.771 / 0.635 — strictly-beats holds under both relevance
definitions. Weight-grid table in D27.

### Latency (§13)
- p95 warm, reranker on: **178 ms** < 500 ms ✓ (history: 758 ms at depth
  50/1200 chars -> 444 ms at 30/1000 -> 519 ms on real whole-file chunks ->
  178 ms at depth 20 + query-focused 700-char passages)
- router path (symbol + stacktrace queries): p95 ≈ 0–2 ms < 200 ms ✓, and
  the unit gate asserts the vector path is never invoked there
- embedding cache: re-embed of unchanged index computes 0 new embeddings ✓

### Embedding model benchmark on real chunks (D28)
nomic 0.94/0.830 (winner; only runnable §6 candidate), jina 0.97/0.847
(transformers≥5 incompatible), MiniLM 0.94/0.845 (fallback; parity here,
7× faster — revisit on external repos in Phase 5).

### Graph expansion delta inside the production pipeline (Phase 4 criterion)
expansion ON:  recall@5 0.971 / MRR 0.877 / p95 179 ms
expansion OFF: recall@5 0.971 / MRR 0.877 / p95 178 ms
delta = 0.000 — non-decreasing ✓ (matches graph-mcp's SimpleRetriever
measurement; on this fixture the hybrid top-5 already contains the answers
expansion would attach). `expansion_enabled` stays on by default (§7.5.5).

Full suite: 273 passed, 0 failed, 0 skipped (incl. both eval gates, golden +
golden-embeddings, MCP stdio integration). [Correction, same day — verifier
finding: that run predated the `build_retriever` commit, at which the
Phase-4 serve probe expired (272/1 at commit 150a801). Fixed per D29; the
suite count after the fix is recorded in the verifier report.]

## 2026-07-04 — Phase 5 — external-repo init end-to-end (branch phase-5)

`repograph init` cold, CPU-only Apple M-series, shipping defaults
(nomic-embed-text-v1.5, cached model, D30 wiring: init owns the embedding
pass with progress output). Transcripts: verification/phase5/.

| repo | tracked files | LOC | blobs | chunks | sync (parse+store+graph) | embed | total cold init | index size | repo .git |
|---|---|---|---|---|---|---|---|---|---|
| pallets/flask @HEAD | 236 | 38,330 | 224 | 616 | 0.32 s | ~228 s | **231.5 s** | 13.0 MB | 13 MB |
| sizly @1c01da6 | 104 | 29,193 | 95 | 216 | 0.18 s | ~71 s | **73.7 s** | 5.9 MB | 4.5 MB |

- No crashes on either repo (incl. .jsx via the javascript grammar, rst/md
  via line-window fallback).
- 5 sample queries per repo: flask 5/5 correct file at rank 1;
  sizly 5/5 correct file in top-5 (3/5 at rank 1). Router-path queries
  0–70 ms with no model load.
- MCP cold handshake with built index: regression-tested < 5 s
  (tests/test_serve_startup.py, offline env).

## 2026-07-04 — Phase 5 — external embedder re-benchmark + expansion delta (branch phase-5)

eval/external/bench_external.py, file-level hits, CPU (full tables + decision
reasoning in DECISIONS.md D33/D34):

| repo (queries) | model | vector-only r@5/MRR | hybrid r@5/MRR | hybrid p95 | embed |
|---|---|---|---|---|---|
| flask (14) | nomic (ship) | 0.357 / 0.310 | **0.857 / 0.768** | 261 ms | 237.7 s |
| flask (14) | MiniLM | 0.786 / 0.583 | 0.786 / 0.649 | 223 ms | 6.4 s |
| sizly (12) | nomic (ship) | 0.417 / 0.361 | **0.833 / 0.674** | 207 ms | 75.4 s |
| sizly (12) | MiniLM | 0.833 / 0.688 | 0.833 / 0.632 | 187 ms | 1.7 s |

- Decision: nomic stays the shipping default (hybrid strictly ≥ on both
  repos); MiniLM documented as the fast fallback (D33). Honest note: nomic's
  isolated dense channel is much weaker than MiniLM's on real repos — the
  hybrid union + CE blend is what carries it.
- Graph expansion delta, shipping pipeline (§13 gate: recall non-decreasing):
  flask recall 0.857→0.857 (Δ 0.000 ✓), MRR 0.821→0.768 (−0.054);
  sizly recall 0.833→0.833 (Δ 0.000 ✓), MRR 0.660→0.674 (+0.014). Kept ON (D34).
- p95 warm hybrid stays under the 500 ms gate on both external repos (207–261 ms).

## 2026-07-04 — Phase 5 — Golden Test replay on real history (flask, 30 commits)

eval/golden_replay.py: last 30 first-parent commits of pallets/flask checked
out oldest→newest with incremental sync after each; final state vs
from-scratch rebuild at the same HEAD. **PASS — all 7 projections identical**
(active blobs, files@HEAD, chunks, FTS, symbols, edges, embeddings).
Incremental replay 5.8 s total (~0.18 s/commit); rebuild 0.28 s.

## 2026-07-04 — Phase 5 — A/B token benchmark (sizly primary + fixture) — TARGET MISSED, recorded as-is

Full report + methodology + judgment calls: verification/ab/ab-results.md.
21 tasks (11 sizly from eval/ab_tasks_sizly.md, 10 fixture from
eval/ab_tasks.md, frozen before arm A), fresh `claude -p` (sonnet) session
per task per arm, ground truth never shown to agents.

| | solve rate | mean tokens_total (solved) | mean cost | tool calls | file reads |
|---|---|---|---|---|---|
| fixture A | 10/10 | 300,849 | $0.506 | 28.9 | 15.1 |
| fixture B (repograph) | 10/10 | 510,731 (−69.8 %) | $0.383 (+24.4 %) | 14.9 (+48 %) | 4.7 (+69 %) |
| sizly A | 9/11 | 608,948 | $0.910 | 33.6 | 14.6 |
| sizly B (repograph) | **11/11** | 595,789 (+2.2 %) | $0.985 (−8.3 %) | 29.5 (+12 %) | 8.8 (+39 %) |

- §13 target ≥50 % token reduction on solved tasks: **NOT MET** (fixture
  −69.8 %, sizly +2.2 %). Filed in BLOCKED.md per §13; no reruns after
  seeing results.
- Solve-rate guardrail B ≥ A: PASS — B solved both tasks A failed (sizly D2
  timed out in A at 20 min/107 tool calls; A's D5 stalled asking for shell
  permission). MCP adoption: sizly 11/11 tasks, fixture 7/10.
- Honest mechanism note: repograph replies are token-dense packed chunks and
  every headless turn re-reads the growing context (cache reads dominate
  tokens_total); B takes fewer turns but each is fatter. Billing-weighted
  cost lands within ±25 % of arm A.

## 2026-07-04 — Phase 5 — pre-merge obligations

- GOLDEN_DEEP=1 soak (randomized, max_examples 25): **PASS** on branch
  phase-5 (post-D30 code), this workstation.
- CI workflow added (.github/workflows/ci.yml): venv is ACTIVE for the
  suite (console-script requirement), model caches cached, golden test run
  explicitly.

## 2026-07-04 — Phase 6 — A/B token benchmark v2 (after compact-first search_code, D39)

Human's B3 resolution executed: `search_code` now compact-first (1500-token
default, signature+expand_id rows); SAME 21 frozen tasks, same runner/model/
grading as v1 (entry above, untouched). Full report:
verification/ab/ab-results-v2.md.

| | solve | mean tokens_total (solved) | mean cost | tools | reads |
|---|---|---|---|---|---|
| fixture A v2 | 10/10 | 372,012 | $0.660 | 40.0 | 20.8 |
| fixture B v2 | 10/10 | 431,544 (**−16.0 %**, was −69.8 %) | $0.558 (+15.5 %) | 25.3 (+37 %) | 9.4 (+55 %) |
| sizly A v2 | 9/11 | 590,570 | $1.703 | 62.0 | 30.3 |
| sizly B v2 | 10/11 | 583,342 (+1.2 %) | $0.805 (**+52.7 %**) | 32.1 (+48 %) | 11.9 (+61 %) |

- §13 raw-token ≥50 % target: **still not met** (−16.0 % / +1.2 %); recorded
  as-is, threshold untouched, B3 updated with the v2 outcome.
- Compact-first effect: fixture raw-token regression −69.8 → −16.0; fresh
  tokens now −4.2 % / **+13.2 %** (was −159 % / −37 %); sizly cost −52.7 %.
- Guardrail B ≥ A holds (20/21 vs 19/21). Variance note: v1↔v2 flipped two
  task outcomes (sizly D2, D5) — single-run-per-task remains the harness's
  main limitation.

## 2026-07-05 — Phase A (feature/go-support) — official gate on the extended gold set

Gold set 35 -> 39 queries (4 Go: nl, symbol, nl_hard, stack-trace — additive
only). Fixture v3 (append-only commit 8: goexport/gorunner Go package).
`eval/run_eval.py --mode all`, thresholds untouched:

| mode | recall@5 | MRR | p50 | p95 | misses |
|---|---|---|---|---|---|
| hybrid | **0.974** | **0.869** | 168 ms | 177 ms | q28 |
| bm25-only | 0.744 | 0.611 | 0.3 ms | 0.3 ms | 10 queries |
| vector-only | 0.795 | 0.714 | 18 ms | 26 ms | 8 queries |

- recall@5 0.974 >= 0.80 ✓; MRR 0.869 >= 0.60 ✓; hybrid strictly beats both
  single channels ✓ — **GATE: PASS**
- All 4 Go queries hit, including the vocabulary-mismatch nl_hard (q38) and
  the Go stack trace (q39 — via the router fast path after the code-context
  morphology fix, D43d; router stacktrace p95 back under the 200 ms gate).
- hybrid recall by type: nl 1.00 · symbol 1.00 · stacktrace 1.00 ·
  decoy 1.00 · nl_hard 0.89 (q28 remains the sole documented miss).
- Full suite: 305 passed, 0 failed, 0 skipped.

Correction (2026-07-05, verifier finding 4 — appended, never edited): the
Phase A entry above says "305 passed"; the correct clean-checkout collection
at the verified tip is **323 tests** (294 on main + Phase A additions; the
gate metrics in that entry were reproduced exactly and are unaffected).
GOLDEN_DEEP=1 soak on fixture v3: PASS (also re-run independently by the
verifier). Post-verification delta: generic-receiver methods now extracted
(verifier finding 1 fixed on-branch with a pinned test), suite 324.

## 2026-07-05 — fix/go-symbol-repetition pre-merge gate (b422865, clean checkout)
Branch: feature/go-support + proto support (D44) + Go name-repetition fixes
(D45: router anti-hijack, size-aware CE/vector blend, package-qualified Go
receiver breadcrumbs, EMBED_TEXT_VERSION=2). Fresh py3.12 venv, fixture
rebuilt from build_miniproject.py (v3, HEAD 6e1a7a1d0fee), 39-query gold set.

| mode   | recall@5 | MRR   | p50 ms | p95 ms | misses |
|--------|----------|-------|--------|--------|--------|
| hybrid | 0.974    | 0.869 | 165.3  | 181.7  | q28    |
| bm25   | 0.744    | 0.611 | 0.3    | 0.3    | 10 queries |
| vector | 0.795    | 0.714 | 18.6   | 27.3   | 8 queries  |

Hybrid recall by type: decoy=1.00 nl=1.00 nl_hard=0.89 stacktrace=1.00
symbol=1.00. GATE: PASS — thresholds untouched; auto-blend resolves to
w=4 on the fixture (small regime), so D45b does not perturb the gate.
Full suite green (clean checkout), GOLDEN_DEEP green. Large-regime blend
weight ships as TODO(upgrade): revalidate on a public large repo with a
tuning/held-out split (prior measurement venue retracted from records).

## 2026-07-05 — feature/gain pre-merge gate (910e43d, clean checkout)
`sherpa gain` local usage analytics (D46). No retrieval-path changes; gate
re-run to prove no regression: hybrid 0.974 / 0.869 (p50 179 ms, p95 211 ms,
sole miss q28), bm25 0.744/0.611, vector 0.795/0.714 — GATE: PASS,
thresholds untouched. Full suite 350/350 + GOLDEN_DEEP green from a fresh
py3.12 venv. Verifier PASS (verification/phase-gain-report.md) incl. the
privacy attack: planted secrets (paths, symbols, string constants) queried
through a real MCP session; zero hits across every usage row/column, the
sqlite dump, and the HTML report; memory standing attack 3.80 GiB < 6 GB.

## Sync performance — per-blob graph cache (D47) + Go import fix (D49)

Branch `feat/bench-and-graph-cache`. Machine: darwin arm64, 32 GB, CPU-only,
Python 3.12. Corpus: a local clone of grafana; `sync()` called directly (no
embedding pass) so the numbers isolate parse + graph + store.

**Repo A — grafana `pkg/`, 7,032 files, 6,322 blobs, 29,225 chunks,
53,200 symbols, 286,774 edges, 1,471,677 lines.**

| build | cold sync | no-op re-sync | peak RSS |
|---|---|---|---|
| main (neither change) | 187.85 s | 164.93 s | 842 MB |
| D47 + D49 | 20.17 s | 7.52 s | 865 MB |
| speedup | **9.3x** | **21.9x** | — |

**Repo B — 2,000-file subset of the same tree (isolating each change).**
1,788 blobs, 18,935 symbols, 94,659 edges, 399,842 lines. Median of 3 no-op
syncs, back-to-back on an otherwise idle machine.

| build | cold sync | no-op re-sync | vs main |
|---|---|---|---|
| main | 33.13 s | 30.90 s | 1.00x |
| + D47 (graph cache) only | 35.93 s | 29.50 s | 1.05x |
| + D49 (Go import fix) only | 6.20 s | 4.65 s | 6.6x |
| + both | 6.17 s | 1.90 s | **16.3x** |

Read honestly: the graph cache on its own is worth ~5% here, because a
quadratic import-resolution scan (D49) accounted for ~98% of sync time on Go
code and hid it. Once that is removed the cache is worth 2.4x on a no-op sync
(4.65 s -> 1.90 s) — that is the cache's real contribution, and it is the
number to quote for it. The headline 21.9x is the two changes together.

Cold sync with the cache alone is slightly SLOWER (33.13 -> 35.93 s): a cold
index writes every payload and gets no reuse. That cost is paid once per blob,
ever, and is the intended trade.

Scale note: before D49, full grafana (22,062 tracked files, 15,088 in
graph-supported languages) did not complete a single sync in this environment.
Not re-measured after; repo A is the largest tree with a verified before/after
pair.

Gates re-run on this branch, thresholds unchanged:

    mode      recall@5     MRR   p50 ms   p95 ms  misses
    ------------------------------------------------------------
    hybrid       0.974   0.869    166.1    175.2  q28
    bm25         0.744   0.611      0.2      0.3  q26,q27,q28,q29,q30,q31,q32,q33,q34,q38
    vector       0.795   0.714     19.2     28.4  q01,q04,q15,q19,q22,q28,q32,q38
    hybrid recall by query type: decoy=1.00  nl=1.00  nl_hard=0.89  stacktrace=1.00  symbol=1.00
    GATE: PASS

Identical to main (0.974 / 0.869) — retrieval quality unchanged, as expected
for a pure indexing-path change. Full suite 363 passed (was 351; +12 added,
none removed). Golden Test green, including `GOLDEN_DEEP=1`.
