# Phase 3 Verification Report

Verdict: FAIL — blocked, not defective. Every criterion implementable inside
this worktree passes from a clean checkout with no cheating found; two §10
criteria (B1: "strictly beats vector-only on recall@5", B2: "rebase on main,
integrate real store, merge") remain OPEN and honestly documented in
BLOCKED.md. The branch must NOT merge until both are resolved. A PASS must
mean merge-ready per §3.3; this branch is not, so the verdict is FAIL by the
conservative rule.

Date / commit verified: 2026-07-04 / `8b5ec21ed06bf6210c8eae9f341b789156d5ccf9`
(branch `worktree-retrieval`, `chore: bge-reranker comparison numbers
(rejected: 6.7s p95 vs 500ms gate); TODO(upgrade) markers`)

*Implementing-session addendum: two commits landed after the verified HEAD —
package `__init__` API exports and a fix for the circular import they
introduced. The full suite (105 tests incl. real-model eval gate) was re-run
green at the final HEAD before this report was committed.*

Environment: fresh `git clone --branch worktree-retrieval` into a scratch
directory (the sandbox blocks writes inside the assigned worktree, so a clean
clone was used — this matches the "fresh clean checkout" procedure).
`uv venv --python 3.12 .venv` (CPython 3.12), `uv pip install -e ".[dev]"` —
clean install; runtime deps are `sentence-transformers>=3.0` + `einops>=0.7`,
both from/justified against §6 (einops justified in DECISIONS D8 per §2.6).

Full test suite: `PATH=.venv/bin:$PATH .venv/bin/python -m pytest tests/` →
**105 passed, 0 failed, 0 skipped** (includes the real-model eval-gate tests;
models served from `~/.cache/repograph/models`). Note: `pytest -x -q`
produces no count line because `pyproject.toml` `addopts = "-q"` stacks to
`-qq`; suite re-run without extra `-q` to capture the count.
`tests/test_golden.py` does **not** exist on this branch — it is owned by
core-index (§8) and Phases 1–2 have not started; §2.3 ("must exist before the
indexer is written") is vacuously satisfied since no production indexer exists
(only the test-support fixture indexer in `tests/support/indexer.py`, which is
the §8-sanctioned mocked-store scaffold). This absence is part of why B2
blocks merge.

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 1 | Embedding cache: re-index unchanged fixture → 0 new embeddings (counter) | PASS | `tests/test_embed_cache.py::test_reindex_unchanged_chunks_computes_zero_new_embeddings` (stub encoder, asserts `computed_count` stays flat and a fresh engine over the same store computes 0) AND `tests/test_eval_gate.py::test_embedding_cache_reused_across_runs` with the real nomic model (`computed_count == 0`). Both green. Cache is keyed by `chunk_id` (blob-hash-derived) in the store — permanent, per §7.4. |
| 2 | Both candidate models benchmarked; winner chosen; numbers in DECISIONS.md | PASS | DECISIONS D8 table: nomic 1.00/0.867, jina 1.00/0.890 (disqualified: remote code incompatible with transformers ≥5; benchmarked in a throwaway pinned venv), MiniLM fallback 0.92/0.831. Winner nomic-embed-text-v1.5 is the shipping default in `repograph/retrieve/config.py`. Benchmark harness committed (`tests/support/benchmark_models.py`). Jina numbers accepted on documentation (not independently re-run — requires a transformers<5 venv); the disqualification reasoning is sound and the choice does not depend on the jina numbers. |
| 3 | RRF fusion with tests on hand-built rank lists | PASS | `repograph/retrieve/fusion.py` implements `Σ 1/(60+rank)` (1-based, k configurable, deterministic ties). `tests/test_rrf.py`: 8 tests incl. exact hand-computed scores (`1/61 + 1/63` etc.), multi-list boost, duplicates, empty input, invalid k. Green. |
| 4 | Reranker wired; toggleable via config | PASS | `CrossEncoderReranker` (sigmoid-normalized, truncation, lazy load) wired in `HybridRetriever`; `RetrievalConfig.rerank_enabled` toggles it. `test_rerank_disabled_does_not_call_scorer` proves the toggle; `test_rerank_enabled_reorders` proves effect; `tests/test_rerank.py` covers the wrapper. Real CE used in the eval gate. |
| 5 | Router: exact-symbol queries < 50 ms without touching vector search (test asserts vector path not called) | PASS | `test_exact_symbol_skips_vector_search` asserts `store.vector_calls == 0` AND `encoder.calls == 0` (query never embedded) via a spy store; `test_router_path_under_50ms` asserts < 50 ms; real-model gate reports router p95 = 0–1 ms for symbol and stacktrace queries. |
| 6 | Budget packer: never exceeds budget; dedups overlapping ranges | PASS | `tests/test_pack.py`: exact-budget test, zero budget, overlapping-range dedup (same blob), same-symbol dedup, negative-budget ValueError, plus a hypothesis property test (`total_tokens <= budget` over random candidate sets). Green. |
| 7a | Eval gate: recall@5 ≥ 0.80 | PASS | Reproduced from clean checkout, real models: hybrid+rerank recall@5 = **1.00**. Table matches EVAL_LOG.md exactly. |
| 7b | Eval gate: MRR ≥ 0.60 | PASS | hybrid+rerank MRR = **0.873**. |
| 7c | Beats BM25-only on recall@5 (strict) | PASS | 1.00 > 0.96, asserted by `test_hybrid_strictly_beats_bm25_only`. |
| 7d | Beats vector-only on recall@5 (strict) | **OPEN (B1)** | Tie at 1.00 = 1.00 — both at metric ceiling on the 25-query gold set under the *stricter* symbol-aware relevance (D7; file-level relevance also saturates vector-only). Strict > is structurally impossible on this gold set; the §10 remedies (breadcrumbs, query preprocessing) improve hybrid, not the saturated baseline. The gate test asserts `>=` with the saturation flagged in its docstring, BLOCKED.md, and EVAL_LOG.md — the §13 threshold and gold set are untouched, and hybrid does strictly beat vector-only on MRR (0.873 vs 0.867). This is the §13 "threshold unreachable → BLOCKED.md + stop" path, followed correctly. Needs harder gold queries (eval/ is graph-mcp-owned) or human sign-off. |
| 8 | p95 warm < 500 ms (reranker on); < 200 ms router path | PASS | Measured this run: hybrid+rerank p95 = **443 ms**; router path p95 = **0 ms**. (Depth-30 rerank vs §7.5's "top 50" is a documented deviation, D9, taken to meet the §13 latency gate per §15 priority; quality identical at both depths on the gold set; `rerank_top` remains configurable; bge-reranker §9 fallback recorded with TODO(upgrade).) |
| 9 | Rebase on main, integrate real store, all green → merge | **OPEN (B2)** | `main` is at the Phase 0 tip — no `store/`, `chunker/`, or `gitlayer/` implementation exists anywhere (core-index Phases 1–2 not started). Integration is impossible; §3.3 merge order (core-index → graph-mcp → retrieval) makes retrieval merge last regardless. Correctly not merged; BLOCKED.md written as §3.3 requires. All retrieval code consumes only the frozen `IndexStore` ABC, so integration is plausible by construction. |

## Cheating hunt

1. `git diff origin/main -- tests/`: **purely additive** — 15 new files, 1806
   insertions, **zero modifications or deletions** to the four pre-existing
   Phase 0 test files. No `skip`/`xfail` anywhere in `tests/` (the two grep
   hits are a comment and a test method name).
2. `git diff origin/main -- repograph/contracts/ eval/`: **empty**. Contracts
   untouched; `eval/gold_queries.jsonl` byte-identical to main. `CLAUDE.md`
   and `.claude/` untouched.
3. Mocks in production code: `grep -rn "mock\|Mock\|monkeypatch" repograph/` →
   no matches (one benign docstring in `rerank.py` noting the scorer is
   injectable in tests — dependency injection, not a mock in a production
   path).
4. Hardcoded fixture paths: `grep -rn "miniproject\|fixtures" repograph/` →
   no matches. `grep -rn "tests\." repograph/` → no matches (in-memory store,
   fixture indexer, eval harness all live in `tests/support/`, as §8
   sanctions pre-merge).
5. Thresholds: `tests/support/gatelib.py` constants (`RECALL5_THRESHOLD =
   0.80`, `MRR_THRESHOLD = 0.60`, `P95_WARM_MS = 500`, `P95_ROUTER_MS = 200`)
   exactly match §13; not lowered. EVAL_LOG.md is append-only-consistent and
   its numbers **reproduce exactly** on my machine (1.00/0.873/443 ms vs
   logged 444 ms).
6. The one softened assertion — `test_hybrid_not_beaten_by_vector_only`
   asserts `>=` instead of §13's strict `>` — is a **new** test, not a
   weakened pre-existing one, and the softening is loudly documented in the
   test docstring, the module docstring, BLOCKED.md B1, and EVAL_LOG.md. I
   judge this honest disclosure, not concealment; the criterion is
   nonetheless reported OPEN above and blocks merge.

No cheating found.

## Exploratory attack

Hostile inputs against `HybridRetriever` over an in-memory store containing a
chunk with unicode/emoji identifiers (`naïve_café_handler(данные)`, emoji in
code) and a 5 MB generated-JS chunk (stub encoder, rerank off): empty query,
whitespace-only query, emoji-only query, unicode-identifier query, weird-cased
symbol, NL query over the 5 MB chunk, `budget_tokens` of 1 and 0,
`expand("💣:not:an:id")`, `get_definition("🎉")`, query containing a null
byte, and a 1 MB query string. **No crashes**; empty/None returns where
appropriate; budget 1/0 packs nothing and respects the budget; negative
budget raises `ValueError` as designed. One quality wart (informational): the
router token regex is ASCII-only, so non-ASCII identifiers (e.g.
`naïve_café_handler`) can never take the <50 ms symbol fast path — they
degrade gracefully to the dense path, which did return the correct file.

## Findings

1. **[OPEN — blocks merge] B1: §13 "hybrid strictly beats vector-only on
   recall@5" is unmet** — tie at 1.00/1.00, a metric ceiling on the 25-query
   gold set. The documentation (BLOCKED.md, EVAL_LOG.md, test docstrings) is
   honest and the prescribed §13 escalation path was followed; thresholds and
   gold set are untouched. Resolution requires harder gold queries (eval/ is
   graph-mcp-owned) or explicit human sign-off. Until then this criterion is
   not passed.
2. **[OPEN — blocks merge] B2: "rebase on main, integrate real store, merge"
   is impossible** — main has no store (core-index Phases 1–2 not started).
   Correctly documented in BLOCKED.md; merge order §3.3 puts retrieval last
   anyway. Phase 3 cannot be declared COMPLETE and this branch must not merge
   until core-index lands and the eval gate is re-run against the real SQLite
   store (integration numbers appended to EVAL_LOG.md, as PROGRESS.md already
   plans).
3. **[Informational] Golden Test absent on this branch** —
   `tests/test_golden.py` does not exist; it is core-index-owned and no
   production indexer exists yet, so §2.3 is vacuously satisfied. It MUST
   exist and pass before this branch's eventual merge (it will arrive via the
   rebase in B2).
4. **[Informational] Router fast path is ASCII-identifier-only** — non-ASCII
   symbol names bypass the router and fall to the dense path (no crash,
   correct results in my test). Consider widening the token regex when
   real-world non-ASCII codebases matter.
5. **[Informational, judged acceptable] Documented deviations** — rerank
   depth 30 vs §7.5 "top 50" (D9, latency gate per §15; configurable), packer
   presentation order by score vs selection by density (D6, within the
   contract's "descending usefulness"), symbol-aware eval relevance (D7 —
   *stricter* than file-level, so not gate-gaming), bge-reranker §9 fallback
   with TODO(upgrade) and for-the-record numbers (6696 ms p95), einops
   runtime dep (D8, §2.6 justification present).

Bottom line: the implemented scope is solid, reproducible, and clean of
cheating; the FAIL verdict exists solely because criteria 7d (B1) and 9 (B2)
remain open, so the phase is not complete and the branch is not mergeable per
§3.3. B1 needs a human/graph-mcp decision; B2 needs core-index Phases 1–2 on
main.
