# Verification Report — branch `fix/config-mutation`

Verdict: **PASS**
Date / commit verified: 2026-07-18 / acbd0ac ("fix: copy the caller's
RetrievalConfig in SingleChannelRetriever, never mutate it"), parent
5c7fe3d == origin/main (merge-base check: branch is exactly one commit
atop main).

Verifier: adversarial QA agent (CLAUDE.md §11), fresh clone + fresh
`uv venv --python 3.12` (Python 3.12.13), `uv pip install -e ".[dev]"`,
venv bin on PATH for all runs. Model caches from ~/.cache/sherpa.

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 1 | Clean install from fresh clone + venv | PASS | `uv pip install -e ".[dev]"` completed cleanly |
| 2 | Full suite (claim: 355 passed) | PASS | exit=0; exactly 355 progress dots, zero F/E/s/x markers in the raw redirected log (summary line suppressed by local shell output filtering; dot count + exit code verified) |
| 3 | `pytest tests/test_golden.py -v` | PASS | `1 passed in 5.31s` |
| 4 | `GOLDEN_DEEP=1 pytest tests/test_golden.py -v` | PASS | `1 passed in 21.60s` |
| 5 | Official eval gate `tests/test_eval_gate.py` | PASS | `9 passed in 70.85s`; hybrid recall@5 **0.974**, MRR **0.869**, p95 450.2 ms, miss q28 only; bm25 0.744/0.611; vector 0.795/0.714; per-type decoy=1.00 nl=1.00 nl_hard=0.89 stacktrace=1.00 symbol=1.00; `GATE: PASS`. Byte-identical to claimed main numbers (same miss set, same per-type recall) |
| 6 | Latency gates (flake protocol) | PASS, no flake | warm p95 = 340.4 ms vs 500 ms budget; router p95 = 0.2 ms vs 200 ms budget. Well outside the 10% flake band; no isolated re-run needed |
| 7 | Bug present on main (direct experiment) | CONFIRMED | On origin/main: `RetrievalConfig(rerank_blend_vector_weight=1.0)` → `SingleChannelRetriever` flips caller's `rerank_enabled`/`expansion_enabled` True→False; `r._config is cfg` → True (aliased) |
| 8 | Fix works on branch (direct experiment) | CONFIRMED | Caller's config stays True/True; retriever's own `_config` still has rerank/expansion False (baseline semantics preserved); `r._config is cfg` → False (copied via `dataclasses.replace`) |
| 9 | New tests genuinely failing-first | CONFIRMED | Copied `tests/test_evalfactory.py` onto a main checkout: `2 failed, 2 passed` — the two mutation-pinning tests fail on main with the exact aliasing failure (`hybrid._config.rerank_enabled` False); the two baseline-semantics tests pass on both, as expected. All 4 pass on the branch |

## Cheating hunt

1. `git diff --stat origin/main...HEAD` touches exactly two files:
   `codesherpa/retrieve/evalfactory.py` (+10/−3) and new
   `tests/test_evalfactory.py` (+76). Nothing else — no test on main
   modified, deleted, skipped, weakened, or xfail-ed.
2. `git diff origin/main...HEAD -- codesherpa/contracts/ eval/ tests/
   CLAUDE.md` (excluding the new test file): empty. Contracts frozen,
   eval thresholds untouched.
3. `grep -rn "mock|Mock|monkeypatch" codesherpa/`: no matches.
   `grep -rn "miniproject|fixtures" codesherpa/`: no matches.
4. Commit authorship: Author and Committer both
   `Farhan Khwaja <farhan.khwaja@gmail.com>`, no co-author trailers —
   complies with repo attribution policy.
5. The new test's `_StubStore` lives in tests only; its `active_blobs`
   raises if the auto-blend path runs, so the stub cannot mask real store
   access.

## Exploratory attack (assigned: sweep for the same aliasing pattern)

Grepped `codesherpa/` and `eval/` for in-place attribute assignments on
config-like objects and shared dataclasses.

- `codesherpa/`: **zero** remaining mutation sites. The fixed site was the
  only one.
- Lookalikes (not defects): `eval/external/bench_external.py:99-100` and
  `:127-129` mutate `RetrievalConfig` objects, but each is constructed on
  the immediately preceding line (97, 126) — fresh local objects, never
  caller-supplied. Listed for triage awareness only.
- Aliasing-without-mutation observation (not a defect):
  `codesherpa/retrieve/retriever.py:67`
  (`self._config = config or RetrievalConfig()`), `evalfactory.py:115`,
  and `warm.py:132` store/pass the caller's config by reference but are
  read-only today (verified: no `self._config.<attr> =` assignment exists
  anywhere; auto-blend weight goes to a local then
  `self._blend_vector_weight`). Any future in-place write to
  `self._config` would reintroduce this bug class; the new shared-config
  test partially guards HybridRetriever.

## Findings

None at FAIL level.

Observations (non-blocking):

1. `PROGRESS.md`/`DECISIONS.md` untouched on this branch. The fix involves
   no non-obvious decision; a one-line PROGRESS entry is added at merge
   time (rebase), with the full account in the commit message and PR body.
2. The full-suite summary line was suppressed by local shell output
   filtering; verification relied on exit code 0 plus an exact count of
   355 pass markers with zero failure markers in the raw log. Individual
   gate runs printed normal summaries.

## Summary

**PASS.** The fix is real, minimal, and correct: bug reproduced on main
(caller's config mutated, aliased into the retriever), fix verified on
branch (`dataclasses.replace` copy, caller untouched, baseline semantics
preserved, other tunables survive the copy). Full suite 355 green, golden
+ deep golden green, eval gate byte-identical to main (0.974/0.869, miss
q28 only), latency comfortably within budget with no flake. Diff scope
exactly as claimed; no contract, threshold, or test tampering.
