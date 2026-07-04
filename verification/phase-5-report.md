# Phase 5 Verification Report

Verdict: **PASS**
Date / commit verified: 2026-07-04 / `02e3ef5efa20f21037e2f0a724c8b8d1234eb45f` (branch `phase-5`)

Verifier environment: fresh clone of `phase-5` into a scratch dir, new uv venv
(CPython 3.12), `uv pip install -e ".[dev]"` — install clean. Full suite run
with the venv bin on PATH: **284 passed, 0 failed, 0 skipped, exit 0**
(~8 min, includes both real-model eval gates). `pytest tests/test_golden.py -q`
green. Model caches at `~/.cache/repograph/models` used as instructed.

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 1 | Sizly redaction: no sizly file contents committed; paths/byte-ranges/scores/symbols only | PASS | `git grep -il sizly` → 9 files, all reviewed: `verification/phase5/sizly-init-and-queries.md` (paths/ranges/scores only, explicit redaction note), `verification/ab/sizly-metrics.csv` (numeric metrics only), `verification/ab/ab-results.md` (aggregates; states sizly raw streams NOT committed — only fixture streams are, and they contain no sizly mention), `eval/external/sizly_gold.jsonl` (queries + expected paths/symbols only), `eval/ab_tasks_sizly.md` (task text + ground-truth path/symbol comments — allowed, human-committed on main at `ebf9660`, byte-identical on this branch), plus BLOCKED/DECISIONS/EVAL_LOG/PROGRESS (metrics/paths only). Zero code fences / source excerpts from sizly anywhere. |
| 2 | A/B benchmark run (sizly primary + fixture), metrics complete, ≥50% target miss reported honestly per §13 + D35 amendment | PASS | EVAL_LOG entry titled "TARGET MISSED, recorded as-is"; `BLOCKED.md` B3 filed; `verification/ab/ab-results.md` §"Verdict against the §13 target": "**The ≥50 % token-reduction target is NOT met**". I recomputed every headline number from the committed raw data: sizly CSV → A 9/11 solved, 608,948 tok, $0.910, 33.6 calls, 14.6 reads; B 11/11, 595,789 tok, $0.985, 29.5, 8.8 — exact match. Fixture summary JSONLs → A 300,849/$0.506/28.9/15.1; B 510,731/$0.383/14.9/4.7 — exact match (−69.8%). Both arms measured on tokens/tool-calls/file-reads/fallback; solve rate B 21/21 > A 19/21. No spin: B-uses-more-tokens is stated first, cost framing is labeled as secondary. Thresholds untouched (see cheating hunt). D35 records the "record whatever the numbers are" amendment and zero post-measurement reruns. |
| 3a | Embedder re-benchmark on both external repos, decision in D33 | PASS | D33: nomic vs MiniLM on flask (14 q) + sizly (12 q), full tables, nomic kept as default with the honest caveat that its isolated dense channel loses to MiniLM on real repos; mirrored in EVAL_LOG. `eval/external/bench_external.py` committed. |
| 3b | Expansion delta re-measured on flask | PASS | D34 + EVAL_LOG: flask recall 0.857→0.857 (Δ 0.000, gate holds), MRR −0.054 disclosed; sizly Δ 0.000 / MRR +0.014. Kept ON with mechanism explanation. |
| 3c | q28 fix attempted, outcome recorded | PASS | D32: two variants measured (tables), both REJECTED with numbers (net recall down / side effects); q28 kept as documented limitation; embed-tag invalidation retained as infrastructure. |
| 3d | Friendly serve error on non-repo; router regex decision documented | PASS | D31 documents the ASCII-regex decision with reasons. Live check from clean checkout: `repograph serve` on a non-git dir → exit 2, "not inside a git repository … run `git init`"; on a repo without index → exit 2, "run `repograph init`". Also pinned by `tests/test_cli.py::test_serve_refuses_non_repository` and `tests/test_serve_startup.py::test_serve_without_index_exits_2_with_hint`. |
| 3e | MCP startup never embeds/downloads in handshake; regression tests | PASS | `tests/test_serve_startup.py`: cold subprocess handshake asserted < 5 s in an offline env (empty fake HOME + HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE) with router tools (index_status, symbol search_code, get_definition, get_callers, expand) exercised in that same offline process; `build_retriever` asserted to never sync/embed; warming status test. All ran green in my full-suite run. |
| 3f | local_files_only when cached; init prints embedding progress | PASS | `repograph/embed/engine.py:105` and `repograph/retrieve/rerank.py` pass `local_files_only=model_is_cached(...)`; hooks embed with `require_cached_model=True` (`warm.py:135`). Progress verified live: my own `repograph init` on a fresh flask clone printed 0%→100% 10%-step progress lines. |
| 4a | GOLDEN_DEEP=1 soak recorded green | PASS | Recorded in EVAL_LOG ("pre-merge obligations": PASS). Independently re-run by the verifier on the clean checkout: `GOLDEN_DEEP=1 pytest tests/test_golden.py -q` → exit 0. |
| 4b | ci.yml activates the venv for the suite | PASS | `.github/workflows/ci.yml`: `. .venv/bin/activate` before both the full suite and the explicit golden-test step; model caches cached. |
| 5a | Init end-to-end on both external repos; cold time + index-size-vs-repo-size logged | PASS | EVAL_LOG table: flask 616 chunks / 231.5 s / 13.0 MB vs 13 MB .git; sizly 216 chunks / 73.7 s / 5.9 MB vs 4.5 MB .git. Independently reproduced: fresh `pallets/flask` clone, full `repograph init` → 224 blobs / 616 chunks / 616 embeddings / 12.4 MB / ~241 s wall, no crashes. |
| 5b | 5 sample queries per repo with transcripts | PASS | `verification/phase5/flask-init-and-queries.md` and `sizly-init-and-queries.md` (sizly one redacted to paths/scores). Spot-replicated 3 flask queries on my own index: blueprint query → `Blueprint.register` rank 1; `full_dispatch_request` router path → exact definition + ranked neighbors in **0.106 s total process time** (no model load); stack-trace query → `Flask.make_response` interior chunk rank 1. Matches transcripts. |
| 5c | Golden replay against flask's last 30 commits | PASS | `eval/golden_replay.py` committed and real (uses `test_golden.GOLDEN_PROJECTION`/`golden_state`). Logged PASS in EVAL_LOG; independently re-run by the verifier on a fresh flask clone: "GOLDEN REPLAY: PASS — incremental == rebuild across 7 projections" (replay 5.75 s, rebuild 0.28 s). |
| — | Full suite + Golden Test from clean checkout | PASS | 284 passed / 0 skipped, exit 0; `tests/test_golden.py` green standalone. |

## Cheating hunt

1. `git diff origin/main -- tests/`: additions only (`test_serve_startup.py`,
   `test_warm.py`, two new tests in `test_cli.py`). The one modification is the
   console-script "unimplemented command" probe retargeting `search` → `bench`
   (search is now implemented); assertions unchanged, documented D5 precedent.
   No test deleted, skipped, weakened, or xfail-ed; suite grew 273 → 284 with
   zero skips.
2. `repograph/contracts/` vs main: **tree hashes identical**
   (`d13918d0efeb…` on both `origin/main:repograph/contracts` and
   `HEAD:repograph/contracts`). Frozen contracts untouched.
3. Mocks/monkeypatch in non-test code: grep over `repograph/**/*.py` → none.
4. Hardcoded fixture paths (`miniproject`/`fixtures`) in `repograph/` → none.
5. Eval thresholds: `eval/run_eval.py` unchanged vs main; `RECALL_AT_5_MIN =
   0.80`, `MRR_MIN = 0.60` intact. `CLAUDE.md` §13 unchanged vs main (diff
   empty). `eval/` diff vs main is new files only (ab tasks, external
   harnesses, gold sets, golden_replay); `gold_queries.jsonl` untouched.
6. `EVAL_LOG.md` diff vs main: append-only (zero deletion lines).
7. A/B integrity: reported means recomputed from committed raw artifacts and
   match to the digit (see criterion 2); `ab_runner.py::parse_tasks` strips
   ground-truth HTML comments in code; task files frozen on main before arm A
   (`ebf9660`, unchanged on this branch); `eval/ab_harness.md` unchanged vs
   main.

No cheating found.

## Exploratory attack

1. `repograph init` on an **empty git repo** (no commits): exit 0, clean
   "0 blobs, 0 chunks" index; `status` and hooks fine. No crash.
2. Repo with a Python file containing **emoji and Cyrillic identifiers** plus a
   **UTF-16 file**: init exit 0; emoji file is a tree-sitter syntax error and
   fell back to line-window chunks **with a logged warning** (exactly the §7.2
   contract); UTF-16 file skipped as binary; `repograph search "party"` returns
   the chunk via bm25. No crash.
3. Live friendly-error checks: `serve` on a non-repo dir and on an un-indexed
   repo both exit 2 with actionable hints (see criterion 3d).

Minor observations (non-blocking, informational only):
- `repograph status <path>` does not accept a positional path (unlike
  `init`/`serve`/`search`); `status` works from inside the repo. Cosmetic CLI
  asymmetry, no criterion touches it.
- `verification/ab/fixture/summary-{A,B}.jsonl` rows carry no `solved` field
  (fixture was 10/10 in both arms, so the reported means are unambiguous);
  sizly per-task solved flags are in the CSV. Worth adding the field if the
  harness is rerun, purely for auditability.
- `repograph search` on a `--no-embed` index loads the embedding model to
  embed the query even though zero chunk vectors exist (returns correct bm25
  results; no crash). A skip-dense-when-cold shortcut would save a few seconds
  in the warming window. Not a criterion.

## The A/B target miss — compliance statement

The §13 "≥50% token reduction" target was **missed** (fixture −69.8%, sizly
+2.2%) and this is a **documented BLOCKED.md item (B3) per §13, not a hidden
failure**. Handling complies with the honesty rules: the miss is stated
plainly and first in EVAL_LOG ("TARGET MISSED, recorded as-is"),
`verification/ab/ab-results.md` ("NOT met"), BLOCKED.md B3, and D35; no
threshold was edited anywhere; no post-measurement reruns or tuning were
performed; the raw per-task data is committed and reproduces the reported
aggregates exactly; and the phase proceeded under the human's explicit
"record whatever the numbers are" amendment, which D35 records verbatim. The
open product decision (accept the reframed value prop vs pursue token-diet
levers) is correctly left to the human in B3.

## Findings

None at FAIL level. Verdict: **PASS** — a fresh session could merge `phase-5`
per §3.3 without hesitation (all §3.3 boxes verified from a clean checkout:
suite green, golden green, eval scores in EVAL_LOG, contracts untouched,
PROGRESS/DECISIONS updated, this report committed).
