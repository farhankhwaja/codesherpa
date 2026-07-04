# Phase 6 Verification Report (FINAL, whole-repo)
Verdict: FAIL
Date / commit verified: 2026-07-05 / 2246cd828f5e89e73f5c98c86ebd0866be002777 (branch `phase-6`; main at 47e8d26)

One defect, confined to a single README sentence (finding 1). Everything
else — the full suite from a clean checkout, the golden test, all cheating
hunts, the A/B v2 reproduction, the install flow, and the standing
memory-ceiling attack — passed. The fix is a one-line README edit; no code,
test, or data changes are implicated.

## Setup
- Fresh `git clone --branch phase-6` into a scratch dir; `uv venv --python
  3.12 .verifier-venv`; `uv pip install -e ".[dev]"` → clean install, no
  errors.
- Full suite with venv bin on PATH: **290 passed, 0 failed, 0 skipped, exit
  0** (290 collected; the "~292" expectation matches). Both
  `tests/test_embed_memory.py` tests ran (dots, not skips) — the real-model
  subprocess RSS test executed against the cached nomic model.
- `pytest tests/test_golden.py -q`: **PASS** (exit 0).

## Criteria
| # | Criterion (abridged, as amended) | Result | Evidence |
|---|---|---|---|
| 1 | README: what/why, 3-cmd quickstart, diagram, real EVAL_LOG-traceable numbers, comparison, roadmap, honest limitations (D32/D26/D34/A-B miss v1+v2) | **FAIL (one number)** | Quickstart matches the amended form exactly (`pip install codesherpa` / `sherpa init` / `claude mcp add sherpa -- python -m codesherpa.mcp_server "$PWD"`). Diagram, comparison paragraph (Aider/codebase-memory-mcp/Unblocked/Headroom), roadmap present. Limitations state q28/D32 (wording matches DECISIONS), CPU reranker fallback with bge +0.034 MRR / 6.7 s p95 (= EVAL_LOG 6696 ms) and TODO(upgrade) intent, D34 expansion deltas (Δrecall 0.000; MRR −0.054 flask / +0.014 other — exact), and the A/B raw-token miss in BOTH rounds, plainly ("Honest miss: raw token usage per solved task still did not drop ≥50 %"). 12+ numbers spot-checked against EVAL_LOG: hybrid 0.971/0.877/178 ms; bm25 0.771/0.630/0.3 ms; vector 0.829/0.738/25 ms; flask 0.857/0.768/261 ms; sizly-app 0.833/0.674/207 ms; flask init 231 s/616 chunks/13 MB; app 74 s/216/5.9 MB; ~150 kLOC/s; solve rates v1 21/21 vs 19/21, v2 20/21 vs 19/21; cost +52.7 % (v2); token gaps −70/+2 (v1), −16/+1 (v2) — **all trace**. Defect: the "48–61 % fewer whole-file reads" range traces to nothing (see finding 1). |
| 2 | Install flow verified + documented | PASS | `verification/phase6-install-flow.md` present with exact commands, init output, peak RSS (4.06 GB), and a real `claude mcp list` Connected handshake. Independently corroborated by my own clean-clone run (below). |
| 3 | LICENSE (MIT), CONTRIBUTING.md, ci.yml activates venv | PASS | LICENSE first line "MIT License"; CONTRIBUTING.md 48 lines; `.github/workflows/ci.yml` runs `. .venv/bin/activate` before BOTH the full suite and the explicit golden-test step; caches `~/.cache/sherpa` + HF. |
| 4 | D38/D38-final memory bounds + D39 compact-first, with tests | PASS | `MAX_CHUNK_BYTES = 16384` byte cap in `codesherpa/chunker/fallback.py` (with contiguity-preserving slicing); `ENCODER_MAX_TOKENS = 1024` clamp on `model.max_seq_length` in `codesherpa/embed/engine.py` (+ `ENCODER_MAX_CHARS` pre-guard on both chunk and query paths). Failing-first regression tests all present and substantive: `test_embed_memory.py` (clamp assertion + REAL-nomic subprocess asserting ru_maxrss < 6 GB), `test_chunker_fallback.py` (single-line 2 MB file byte-capped, contiguous, deterministic), `test_embed_cache.py` (encoder never sees >ENCODER_MAX_CHARS), `test_sync.py` (end-to-end: committed 500 KB single-line file → max stored chunk ≤ 16384). D39: `search_code(query, budget_tokens=1500, include_code=False)`; MCP integration test asserts budget 1500, `"code" not in row`, breadcrumb+expand_id present, and `include_code=true` restores bodies. |
| 5 | A/B v2 separate entry; v1 untouched; aggregates reproduce; no sizly content | PASS | EVAL_LOG diff vs main: 22 added lines, **0 deletions** (append-only; v1 entry byte-identical). Recomputed from `verification/ab/fixture-v2/summary-{A,B}.jsonl` and `sizly-metrics-v2.csv`: fixture A 372,012/$0.660/40.0/20.8; fixture B 431,544/$0.558/25.3/9.4; sizly A (solved 9/11) 590,570/$1.703/62.0/30.3; sizly B (solved 10/11) 583,342/$0.805/32.1/11.9 — **every EVAL_LOG v2 aggregate reproduces exactly**, incl. −16.0 %, +1.2 %, +52.7 %, fresh-token −4.2 %. `sizly-metrics-v2.csv` is 10 metric columns only (no answers/content); zero "sizly" matches in `verification/ab/fixture-v2/`; the only new sizly-named file is the metrics CSV. |
| — | Full suite + Golden from clean checkout | PASS | 290 passed / 0 skipped, exit 0; golden exit 0. |

## Cheating hunt
1. `git diff main -- tests/` — 5 files, 194 insertions / 3 deletions. The
   only modified assertions (test_mcp_server.py) are a *tightening*: budget
   4000→1500 tracks the D39 default change, plus NEW assertions
   (`"code" not in row`, breadcrumb, include_code round-trip). No test
   deleted, skipped, weakened, or xfail-ed. New tests are real regressions,
   not tautologies.
2. `grep -rn "mock|Mock|monkeypatch" codesherpa/` — no matches.
3. `grep -rn "miniproject|fixtures" codesherpa/` — no matches.
4. Contracts: `git diff main -- codesherpa/contracts/` is **empty**. Diff vs
   pre-rename main (3d44a72) contains only `repograph→codesherpa/sherpa`
   name/path strings (D37, human-authorized) — checked line by line, nothing
   semantic. D39 did NOT touch the frozen Retriever contract (search()
   default stays 4000; the 1500 default is MCP-layer only).
5. Eval thresholds: `eval/run_eval.py` still `RECALL_AT_5_MIN = 0.80`,
   `MRR_MIN = 0.60`, "THRESHOLDS ARE FROZEN" banner intact; `eval/` has no
   diff vs main; CLAUDE.md §13 table unchanged.
6. EVAL_LOG.md append-only vs main (0 deleted lines). BLOCKED.md B3 updated,
   not removed.
7. Honesty checks the task ordered: the A/B ≥50 % raw-token miss is stated
   plainly in README (both rounds, no reduction claim made), EVAL_LOG
   ("STILL not met"), ab-results-v2.md ("reported as-is; threshold
   untouched"), and B3. B3's final paragraph explicitly leaves the ship-vs-
   hold decision to the human. **Presented honestly, not spun** — with the
   single numeric exception in finding 1.

## Exploratory attacks
1. **Standing memory-ceiling attack (D38-final, mandatory).** Fresh
   `git clone --branch phase-6` into scratch; venv created OUTSIDE the
   clone (`uv venv --python 3.12`); `pip install -e ./repo`; then
   `/usr/bin/time -l <venv>/bin/sherpa init .` inside the clone.
   Result: **exit 0**; per-file sync progress printed; embedding reached
   **788/788 (100 %)** — the count grew from ~535 because phase-6 itself
   committed 25 single-line JSONL transcripts under
   `verification/ab/fixture-v2/`, i.e. the attack corpus now contains even
   more of the pathological input class; **max RSS 4,123,852,800 bytes =
   4.12 GB < 6 GB**; 200 s wall. A follow-up `sherpa search` on the built
   index returned `codesherpa/gitlayer/sync.py` chunks for a sync question.
   **PASS.**
2. **Empty repo (no commits).** `git init` + `sherpa init .` → exit 0,
   "0 files @ unborn HEAD", hooks installed, db created. No crash.
3. **Weird-content repo.** One commit containing: a Python file with emoji/
   non-ASCII identifiers (a syntax error in CPython — falls back to line
   windows, as designed), a UTF-16 file (skipped as binary), a CRLF .js
   file, and a two-link symlink loop. `sherpa init` + `sync` + two searches:
   exit 0 throughout, 2 chunks embedded, CRLF function found via symbol
   channel, no crash, no hang. **PASS.**

## Findings
1. **[FAIL — criterion 1] README benchmark number not traceable to
   EVAL_LOG and overstated under its own framing.** README line
   ("Agent A/B" section): *"With sherpa: **48–61 % fewer whole-file
   reads**, 37–48 % fewer tool calls, and on the real app 52.7 % lower
   billed cost (v2)."* Measured reads reductions are: v1 fixture 68.9 %,
   v1 sizly 39.7 % (solved basis; 44.0 % all-tasks), v2 fixture 54.8 %,
   v2 sizly 60.8 %. No basis yields 48; the project's own
   `verification/ab/ab-results-v2.md` says "whole-file reads −55/−61 %".
   The sentence is framed across "two rounds", under which the claimed
   floor (48 %) overstates the worst measured round (39.7 %); under a
   v2-only reading the range should be 55–61. Either way the number is
   wrong. Fix: "55–61 % (v2)" or "39–69 % across both rounds", and scope
   the tool-call range too (37–48 % is exact for v2 only; v1 sizly was
   12.2 %). This is the sole defect; every other spot-checked README
   number (12+) traces exactly.

### Minor observations (not FAIL-level; fix opportunistically with finding 1)
- README "Warm re-sync with no new blobs: ~20–40 ms" — the EVAL_LOG
  Phase 1/2 warm-sync measurements are 18–44 ms (and were taken on the
  synthetic bench corpus, not the external repos discussed in that
  paragraph). Suggest "~20–45 ms" or citing the source table.
- README flask cold init "231 s" vs EVAL_LOG 231.5 s — round-half-up would
  give 232 s; trivial, but the criterion asked for no favorable rounding.
- README Roadmap still lists "Compact-first `search_code` responses (the
  A/B token lever)" as future work, but D39 shipped it in this very branch
  (and the same README describes the v2 rerun "after `search_code` went
  compact-first"). Stale line; drop or replace with a genuine future item.
- The clean-clone chunk count in `phase6-install-flow.md` (535) predates
  the fixture-v2 transcript commit; a fresh clone now indexes 788 chunks.
  Not an error in the doc (it was true when written); noted so the next
  verifier expects ~788.
