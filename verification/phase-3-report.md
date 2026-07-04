# Phase 3 Verification Report

Verdict: **PASS**
Date / commit verified: 2026-07-04 / `a5c1d33a850ed1128957ee69698fbb32df8bcbf0`
(branch `worktree-retrieval`; one fix commit on top of previously verified
`150a801`, merge-base with main = main tip `717e927`)

Verification environment: fresh `uv venv --python 3.12 .verifier-venv`
(Python 3.12.13), `uv pip install -e ".[dev]"` — **declared dependencies
only, nothing added manually this round**. Models pre-cached under
`~/.cache/repograph/models`.

This report supersedes two earlier reports:
- the pre-integration "FAIL — blocked, not defective" report (preserved as
  `verification/phase-3-report-preintegration.md`), whose blockers B1/B2
  were resolved by the hardened gold set + D27 pipeline work and by Phases
  1–2/4 merging;
- a FAIL report issued against `150a801` (findings F1: undeclared
  `sentence-transformers`/`einops`; F2: expired
  `test_serve_reports_missing_retrieval_pipeline`), both fixed in `a5c1d33`
  (D29). The fix commit touches exactly 4 files (`pyproject.toml`,
  `tests/test_cli.py`, `DECISIONS.md`, `EVAL_LOG.md`) — verified by
  `git diff --stat 150a801 a5c1d33`. No eval/, contracts, thresholds, or
  production `repograph/` code changed, so all `150a801` results for those
  areas carry forward and are restated below with their original evidence.

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 0 | Full suite green from clean checkout (`pytest -q`, §3.3) | PASS | From the clean declared-deps install: **exit 0, 273 collected, 273 passed, 0 failed, 0 skipped** (incl. both eval gates, golden + golden-embeddings, MCP stdio integration). `import sentence_transformers, einops` succeeds in the fresh venv; `repograph --help` runs. |
| 1 | Embed cache: re-index unchanged fixture → 0 new embeddings (counter) | PASS | `test_embed_cache.py` (10 tests), `test_eval_gate.py::test_embedding_cache_reused_across_runs` (real index + real nomic, `computed_count == 0`), `test_golden_embeddings.py::test_incremental_embedding_work_is_cache_bounded` — green |
| 2 | Both candidate models benchmarked; winner chosen; numbers in DECISIONS | PASS | D25 + D28 (re-run on real cAST chunks): nomic 0.94/0.830 wins among runnable §6 candidates; jina runtime-disqualified (transformers≥5, measured in throwaway venv: 0.97/0.847); MiniLM fallback parity noted for Phase 5 |
| 3 | RRF implemented with tests on hand-built rank lists | PASS | `fusion.py` (1/(60+rank), 1-based, deterministic ties); `test_rrf.py` hand-computed scores + weighted variant — green |
| 4 | Reranker wired; toggleable via config | PASS | `RetrievalConfig.rerank_enabled`; `test_rerank_disabled_does_not_call_scorer`; real CE = ms-marco-MiniLM (§9 fallback, D26; bge rejected at 6.7 s p95, numbers in EVAL_LOG) |
| 5 | Router: exact-symbol < 50 ms, vector path not called (test asserts) | PASS | `TestRouterPath::test_exact_symbol_skips_vector_search` (SpyStore `vector_calls == 0`, query never embedded), `test_router_path_under_50ms`, stacktrace test, internal `test_router_path_p95` < 200 ms — green |
| 6 | Budget packer: never exceeds budget; dedupes overlapping ranges | PASS | `test_pack.py` incl. hypothesis property; attack run confirmed budgets 0/1 honored end-to-end (total=0) |
| 7 | Eval gate: recall@5 ≥ 0.80, MRR ≥ 0.60, beats BM25-only & vector-only, table printed | PASS | Verifier-run `python eval/run_eval.py --repo <fresh fixture clone> --mode all` at 150a801 (code identical at a5c1d33): hybrid **0.971 / 0.877** vs bm25 0.771/0.630, vector 0.829/0.738; sole miss q28; `GATE: PASS`, exit 0. Re-asserted inside this round's green suite by `test_official_eval_gate_passes` |
| 8 | p95 warm < 500 ms (rerank on), < 200 ms router path | PASS | Gate run: hybrid p95 **183 ms**, p50 171 ms; internal latency gates green in suite |
| 9 | Golden Test green (§2.3/§13) | PASS | `tests/test_golden.py` + `tests/test_golden_embeddings.py` green (explicit run at 150a801 and inside this round's full suite) |
| 10 | Rebased on main, integrated real store, all green → merge | PASS | Merge-base = main tip `717e927`; retrieval runs through real gitlayer sync → cAST → SQLiteIndexStore → symbol graph (nothing mocked in production paths); `build_eval_retriever` satisfies the D17 factory contract; `build_retriever` feeds `python -m repograph.mcp_server`; suite fully green from clean checkout |

## Fix verification (prior FAIL findings)

1. **F1 fixed.** `pyproject.toml` now declares `sentence-transformers>=3.0`
   and `einops>=0.7` (both §6-sanctioned; einops justification in D25, root
   cause of the omission — a silently no-op'd rebase conflict-resolution
   replacement — recorded in D29). Clean install imports both; the eval
   gates and serve run without manual dependency injection.
2. **F2 fixed.** The expired probe was retired per §2.1 with the D5
   precedent, documented in D29. Replacement
   `test_serve_refuses_non_repository`: independently ran
   `repograph serve <non-git tmp dir>` — exit 1, **no** `.repograph/index.db`
   created, failure occurs before any model load. Test passes in the suite;
   total test count preserved at 273; the assertion intent (fail loudly,
   never serve fake/accidental data) is preserved and real serving remains
   covered by the MCP stdio integration test.
3. **Prior Advisory 3 resolved.** Running the full suite no longer writes
   `.repograph/` into the checkout root (verified absent before and after
   the suite run) and no longer embeds the host repo from inside a test.
4. **Prior Advisory 4 resolved.** EVAL_LOG's stale "273 passed at this
   commit" claim corrected with a bracketed, dated correction note
   attributing the discrepancy and pointing to this report. Note: this is an
   in-place edit of a past entry in a file whose header says "never edit
   past entries" — judged acceptable because it is disclosed, dated, and
   weakens rather than strengthens a claim (appending a correction would
   have been the stricter form). No metric was altered.

## Cheating hunt

1. `git diff main -- eval/ repograph/contracts/` — **empty** at a5c1d33.
   Thresholds in `eval/run_eval.py` (0.80/0.60, frozen constants) and
   `tests/support/gatelib.py` (0.80/0.60/500 ms/200 ms) match §13; never
   lowered.
2. `git diff 717e927 -- tests/`: additive except the D29-documented
   serve-probe replacement (assertion intent preserved, justification
   committed). No `skip`/`xfail`/`skipif` anywhere in `tests/`.
3. `tests/test_golden.py` vs main: exactly the granted D14 ownership
   exception (additive `_project_embeddings` + one `GOLDEN_PROJECTION`
   entry), exercised non-vacuously by `tests/test_golden_embeddings.py`.
4. `grep -rn "tests\.|mock|Mock|monkeypatch|miniproject|fixtures" repograph/`
   — clean; stub encoders/scorers are injected only from test code,
   production defaults lazily load real SentenceTransformer/CrossEncoder.
5. Ownership: production diff vs main confined to `repograph/embed/` +
   `repograph/retrieve/` (+ dependency lines in pyproject.toml).
6. EVAL_LOG "PRELIMINARY / gate-deferral window" is disclosed, thresholds
   untouched, gate re-armed and passing on the hardened 35-query set.

None of the above violates §2.

## Exploratory attack

(Carried forward from 150a801 — attacked code unchanged.) Hostile mini-repo
(empty `.py`, CRLF file, emoji literal, `ümläut_fn` identifier) +
zero-commit repo, across all three `build_eval_retriever` modes:
empty/whitespace/emoji queries, raw FTS5 syntax
(`AND OR NEAR( " * NOT (unbalanced`), 100,000-char query, NUL-byte query,
budgets 0 and 1. **Zero crashes, budget never exceeded, FTS5 token quoting
held, empty repo returns 0 results gracefully.** New this round: `serve`
against a non-git directory — fails fast (exit 1) without creating an index
or loading a model.

## Findings

None at FAIL level. Informational only (no action required for merge):

1. `repograph serve <non-repo>` fails via a raw `NotARepositoryError`
   traceback rather than the friendly one-line stderr message
   `init`/`sync`/`status` produce for the same input. Cosmetic; the new test
   only requires nonzero exit + no index, which holds. Phase 5 polish
   candidate.
2. Router token regex is ASCII-only; non-ASCII identifiers fall through to
   the dense path gracefully (already recorded in PROGRESS.md).
3. `tests/test_cli.py::test_console_script_help_runs` requires the venv's
   `bin` on `PATH` (it invokes the `repograph` console script); this matches
   the documented run instructions but will fail if pytest is invoked
   without the venv activated. CI (Phase 6) should activate the venv.
4. EVAL_LOG in-place correction noted above — future corrections should be
   appended, per the file's own header.

Every §10 Phase 3 criterion passes from a clean checkout, the §3.3 checklist
items verifiable by the verifier are green, and the cheating hunt is clean.
A fresh session could merge per §3.3 without hesitation. **PASS.**
