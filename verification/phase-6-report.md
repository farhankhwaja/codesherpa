# Phase 6 Verification Report (FINAL, whole-repo)
Verdict: PASS
Date / commit verified: 2026-07-05 / 0f594cdd69d8f67c064e101870fa65095165cae0 (branch `phase-6`; main at 47e8d26)

Two-round verification. Round 1 (commit 2246cd8) returned **FAIL** on a
single defect — one untraceable README benchmark range — with four minor
observations; that report is preserved verbatim in-repo at
`verification/phase-6-report-fail-round.md`. Round 2 verified the fix
commit 0f594cd, which addresses the defect and all four minor observations.
All round-1 evidence (clean-checkout suite, golden test, cheating hunts,
A/B v2 reproduction, exploratory attacks) was gathered at 2246cd8;
`git diff 2246cd8 0f594cd --stat` touches ONLY `README.md` (+10/−7) and the
new `verification/phase-6-report-fail-round.md`, no test references the
project README (all `README` matches in tests/ are fixture-internal
filenames), so those results carry over — and the golden test was
additionally re-run at 0f594cd in the clean clone (exit 0).

## Setup (round 1, carried over)
- Fresh `git clone --branch phase-6` into scratch; `uv venv --python 3.12
  .verifier-venv`; `uv pip install -e ".[dev]"` → clean install, no errors.
- Full suite with venv bin on PATH: **290 passed, 0 failed, 0 skipped,
  exit 0**. Both `tests/test_embed_memory.py` tests ran (no skips) — the
  real-model subprocess RSS test executed against the cached nomic model.
- `pytest tests/test_golden.py -q`: PASS at 2246cd8 AND re-run PASS at
  0f594cd (exit 0 both).

## Criteria
| # | Criterion (abridged, as amended) | Result | Evidence |
|---|---|---|---|
| 1 | README: what/why, 3-cmd quickstart, diagram, real EVAL_LOG-traceable numbers, comparison, roadmap, honest limitations (D32/D26/D34/A-B miss v1+v2) | **PASS** (after fix 0f594cd) | Quickstart matches the amended form exactly (`pip install codesherpa` / `sherpa init` / `claude mcp add sherpa -- python -m codesherpa.mcp_server "$PWD"`). Diagram, comparison paragraph (Aider / codebase-memory-mcp / Unblocked / Headroom), roadmap present. Limitations state q28/D32 (wording matches DECISIONS), the CPU reranker fallback with bge +0.034 MRR / 6.7 s p95 (= EVAL_LOG 6696 ms), D34 expansion deltas (Δrecall 0.000; MRR −0.054 flask / +0.014 other — exact), and the A/B raw-token miss in BOTH rounds, plainly. 16+ numbers now spot-checked against EVAL_LOG / raw data — **all trace** (details below). No number rounded up or spun. |
| 2 | Install flow verified + documented | PASS | `verification/phase6-install-flow.md`: exact commands, init output, peak RSS 4.06 GB, real `claude mcp list` Connected handshake. Corroborated by my own clean-clone run (attacks, below). |
| 3 | LICENSE (MIT), CONTRIBUTING.md, ci.yml activates venv | PASS | LICENSE "MIT License"; CONTRIBUTING.md present (48 lines); `.github/workflows/ci.yml` runs `. .venv/bin/activate` before BOTH the full-suite step and the explicit golden-test step; caches `~/.cache/sherpa` + HF. |
| 4 | D38/D38-final memory bounds + D39 compact-first, with tests | PASS | `MAX_CHUNK_BYTES = 16384` fallback byte cap (`codesherpa/chunker/fallback.py`, contiguity-preserving); `ENCODER_MAX_TOKENS = 1024` clamp on `model.max_seq_length` (`codesherpa/embed/engine.py`) + `ENCODER_MAX_CHARS` pre-guard on chunk AND query paths. Substantive failing-first regressions: `test_embed_memory.py` (clamp assertion + REAL-nomic subprocess asserting ru_maxrss < 6 GB — executed, not skipped), `test_chunker_fallback.py` (2 MB single-line file byte-capped, contiguous, deterministic), `test_embed_cache.py` (encoder never sees > ENCODER_MAX_CHARS), `test_sync.py` (end-to-end: committed 500 KB single-line file → max stored chunk ≤ 16384). D39: `search_code(query, budget_tokens=1500, include_code=False)`; MCP integration test asserts budget 1500, `"code" not in row`, breadcrumb + expand_id, and `include_code=true` restoring bodies. |
| 5 | A/B v2 separate EVAL_LOG entry; v1 untouched; aggregates reproduce; no sizly content | PASS | EVAL_LOG diff vs main: 22 added lines, **0 deletions** (append-only; v1 entry byte-identical). Recomputed from `verification/ab/fixture-v2/summary-{A,B}.jsonl` + `sizly-metrics-v2.csv`: fixture A 372,012 / $0.660 / 40.0 / 20.8; fixture B 431,544 / $0.558 / 25.3 / 9.4; sizly A (9/11 solved) 590,570 / $1.703 / 62.0 / 30.3; sizly B (10/11) 583,342 / $0.805 / 32.1 / 11.9 — **every EVAL_LOG v2 aggregate reproduces exactly**, incl. −16.0 %, +1.2 %, +52.7 %, fresh −4.2 %. `sizly-metrics-v2.csv` = 10 metric columns, no content; zero "sizly" matches under `verification/ab/fixture-v2/`; the only new sizly-named file is the metrics CSV. |
| — | Full suite + Golden from clean checkout | PASS | 290 passed / 0 skipped, exit 0; golden exit 0 (both commits). |

## Round-2 verification of the fix commit (0f594cd)
`git diff 2246cd8..0f594cd --name-only` = `README.md`,
`verification/phase-6-report-fail-round.md` only. The preserved fail-round
report is byte-identical to my round-1 report (diff: IDENTICAL). Each
amendment checked against my independently recomputed aggregates
(v1 reads 68.9 % / 39.7 %, v2 54.8 % / 60.8 %; v1 tools 48.4 % / 12.2 %,
v2 36.7 % / 48.2 %):
1. Reads: "39–69 % fewer whole-file reads across both rounds (55–61 % in
   v2)" — floor 39 ≤ 39.7 (rounded DOWN, conservative), top 69 ≈ 68.9
   (nearest), v2 55/61 nearest of 54.8/60.8. **Traceable, honest.**
2. Tool calls: "12–48 % fewer (37–48 % in v2)" — 12 ≤ 12.2, 48 ≤ 48.4,
   37 ≈ 36.7, 48 ≤ 48.2. **Traceable, honest** (now includes the weak v1
   sizly round instead of hiding it).
3. Init times exact: "flask 231.5 s", "React+Node app 73.7 s" = EVAL_LOG
   verbatim.
4. Warm re-sync: "18–44 ms (synthetic bench corpus, EVAL_LOG Phase 1/2)" =
   the measured 0.018–0.044 s, with the corpus honestly attributed.
5. Roadmap: shipped compact-first line removed; replacement "per-blob graph
   extraction cache (`TODO(upgrade)` in graph/index.py)" verified genuine —
   `codesherpa/graph/index.py:13` contains that `TODO(upgrade)`.

## Cheating hunt (round 1, carried over — unchanged by 0f594cd)
1. `git diff main -- tests/`: 5 files, 194 insertions / 3 deletions; the
   only modified assertions (test_mcp_server.py) are a tightening tracking
   the D39 default (4000→1500) plus NEW assertions. Nothing deleted,
   skipped, weakened, or xfail-ed; new tests are real regressions.
2. `grep -rn "mock|Mock|monkeypatch" codesherpa/` — no matches.
3. `grep -rn "miniproject|fixtures" codesherpa/` — no matches.
4. Contracts: diff vs main **empty**; diff vs pre-rename main (3d44a72) is
   exclusively `repograph→codesherpa/sherpa` name/path strings (D37,
   human-authorized), checked line by line. D39 did NOT touch the frozen
   Retriever contract (its search() default stays 4000; 1500 is MCP-layer).
5. Eval thresholds: `eval/run_eval.py` still `RECALL_AT_5_MIN = 0.80`,
   `MRR_MIN = 0.60`, frozen banner intact; `eval/` has no diff vs main;
   CLAUDE.md §13 unchanged.
6. EVAL_LOG.md append-only vs main (0 deleted lines); BLOCKED.md B3
   updated, not removed.

## Honesty questions the task ordered answered explicitly
- **Is the A/B ≥50 % raw-token target miss presented honestly in the
  README?** YES. It is labeled "Honest miss", states the miss for BOTH
  rounds with the actual numbers (v2 −16 % / +1 %; v1 −70 % / +2 %), makes
  no reduction claim, explains the mechanism (cache reads dominate), and
  repeats it in the limitations section ("no ≥50 % raw-token reduction in
  headless runs, even after the compact-first response change"). EVAL_LOG
  ("STILL not met"), ab-results-v2.md ("reported as-is; threshold
  untouched; no reruns after seeing results"), and B3 agree.
- **Is B3's remaining ship-vs-hold question clearly left to the human?**
  YES — BLOCKED.md B3's final paragraph: "Remaining open question for the
  human: accept shipping with the measured profile … or hold the release on
  the raw-token number (§13 forbids lowering the threshold)." Merging
  phase-6 to main does not itself resolve B3; that decision remains with
  the human.

## Exploratory attacks (round 1, carried over)
1. **Standing memory-ceiling attack (D38-final, mandatory).** Fresh clone
   of the branch; venv OUTSIDE the clone (`uv venv --python 3.12`);
   `pip install -e ./repo`; `/usr/bin/time -l <venv>/bin/sherpa init .`
   inside the clone. Result: **exit 0**; embedding reached **788/788
   (100 %)** (up from ~535 because phase-6 itself committed 25 single-line
   JSONL transcripts under `verification/ab/fixture-v2/` — the attack
   corpus now contains even more of the pathological input class);
   **max RSS 4,123,852,800 B = 4.12 GB < 6 GB**; 200 s wall. Follow-up
   `sherpa search` on the built index returned
   `codesherpa/gitlayer/sync.py` chunks for a sync question. **PASS.**
2. **Empty repo (no commits).** `git init` + `sherpa init .` → exit 0,
   "0 files @ unborn HEAD", hooks installed, db created. No crash.
3. **Weird-content repo.** One commit with: emoji/non-ASCII-identifier
   Python (a CPython syntax error → line-window fallback, as designed),
   a UTF-16 file (skipped as binary), a CRLF .js file, a two-link symlink
   loop. init + sync + searches: exit 0 throughout, CRLF function found via
   the symbol channel, no crash, no hang. **PASS.**

## Findings
1. (Round 1, RESOLVED at 0f594cd) README "48–61 % fewer whole-file reads"
   was untraceable to EVAL_LOG and overstated the cross-round floor
   (measured 39.7 %); now "39–69 % across both rounds (55–61 % in v2)" and
   the tool-call range is likewise scoped ("12–48 %, 37–48 % in v2").
   Verified against independently recomputed aggregates. Closed.
2. (Round 1 minor, RESOLVED) Warm re-sync now "18–44 ms" with corpus
   attribution. Closed.
3. (Round 1 minor, RESOLVED) Init times now exact (231.5 s / 73.7 s).
   Closed.
4. (Round 1 minor, RESOLVED) Stale compact-first roadmap line replaced with
   a genuine item whose `TODO(upgrade)` reference was verified to exist.
   Closed.
5. (Informational, no action) `phase6-install-flow.md`'s 535-chunk count
   predates the fixture-v2 transcript commit; a fresh clone now indexes
   788 chunks. True when written; noted so future verifiers expect ~788.

No open findings. A fresh session could merge `phase-6` (0f594cd) per §3.3
without hesitation — noting that the §3.3 merge is a process step and does
NOT constitute the human's B3 ship/hold decision, which remains open in
BLOCKED.md.
