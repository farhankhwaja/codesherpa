# Phase 1 Verification Report

Verdict: PASS
Date / commit verified: 2026-07-04 / 35ef6d1733feb1182036691c6ba93ec7f20db5b4 (branch `worktree-core-index`)

Method note: the verifier's isolated worktree is sandbox-locked at dc77f33, so
verification ran from a fresh `git clone` of the repo checked out at 35ef6d1 in
a scratch directory, with a brand-new uv-managed Python 3.12 venv
(`uv venv --python 3.12 .verifier-venv`; `uv pip install -e ".[dev]"`).
Install succeeded (pygit2 1.19.3, sqlite-vec 0.1.9, pytest, hypothesis).

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 0 | Full suite from clean checkout | PASS | `PATH=".verifier-venv/bin:$PATH" .verifier-venv/bin/python -m pytest -q` → **74 passed in 3.97s**, 0 skipped/xfailed |
| 1 | `repograph init` on fixture: `.repograph/index.db`, four hooks, `.gitignore` | PASS | Fixture built via `tests/fixtures/build_miniproject.py` (HEAD 3f2519b4070e), copied to scratch; `repograph init` → exit 0, `index.db` created (188 K), hooks `post-merge, post-checkout, post-rewrite, post-commit` present + executable, each contains `repograph sync --quiet`; `.gitignore` gains `.repograph/`. Live hook check: a real `git commit` of a new file triggered post-commit sync — new blob appeared in `files`/`blobs`/`chunks` (33→34). |
| 2 | Schema: blobs, files(ref,path,blob), chunks, chunks_fts (FTS5), symbols, edges, embeddings, meta documented in `store/schema.sql` | PASS | `repograph/store/schema.sql` defines and documents all 8 tables (files has ref/path/blob_hash/mtime, chunks_fts is fts5 with `_` tokenchars); live DB `sqlite_master` shows all 8 (+fts5 shadow tables). vec0 table lazily created (documented, D8). |
| 3 | Golden Test v1: hypothesis-driven, ≥10 random ops (add/modify/delete/branch/switch/merge/revert), sync after each, incremental == rebuild, <120 s | PASS | `pytest tests/test_golden.py -q` → 1 passed, **2.46 s**. Source review: `@given(ops=st.lists(_OPS, min_size=10, max_size=16))`, all 7 op kinds in the strategy plus a pinned `@example` exercising every kind; `sync` after every op; equality asserted over active blobs, HEAD file map, per-blob chunk ids+code, and FTS coverage of active chunks (active-projection equality is exactly the §10 wording — "active blobs, chunks, FTS rows"; inactive-row retention is the documented soft-delete design, D7). `derandomize=True`/6 examples is justified in-file by the CI-time bound; still hypothesis-driven. |
| 4 | Sync idempotent: second run changes zero rows | PASS | `tests/test_sync.py::test_sync_is_idempotent` passed; it compares a full table-by-table DB dump (all 7 tables + FTS) before/after the second sync, excluding only `meta.last_sync`. Independently reproduced on an adversarial repo: second `repograph sync` → `0 new blobs, 0 reactivated, 0 deactivated`. |
| 5 | Concurrent-safety (lockfile) | PASS | `tests/test_sync.py::test_concurrent_syncs_do_not_corrupt` passed: two spawn-context processes sync simultaneously, both succeed, `PRAGMA integrity_check` = ok, result equals a fresh rebuild, no leftover lockfile. |
| 6 | Throughput measured, logged to EVAL_LOG.md, ≥2000 LOC/s | PASS | EVAL_LOG.md entry present (189,338 / 200,836 LOC/s claimed). Reproduced: `.verifier-venv/bin/python tests/bench_indexing.py 400` → **199,615 LOC/s** cold (18,200 LOC in 0.091 s), warm sync 0.018 s. ~100× over target. EVAL_LOG honestly notes this is with the Phase-1 line-window chunker and that Phase 2 must re-measure. |

Additional §2/§3.3-relevant checks: `repograph --help` runs; PROGRESS.md and
DECISIONS.md are updated; golden test commit (7e3e7c9) is an ancestor of the
store (591e164) and gitlayer (e1f3c48) commits — the golden test existed
before the indexer was written, per §2.3.

## Cheating hunt

1. `git diff dc77f33 35ef6d1 -- repograph/contracts/ eval/` → **empty**. Contracts untouched; eval thresholds untouched. CLAUDE.md unchanged (§13 thresholds intact).
2. `git diff dc77f33 35ef6d1 -- tests/` → all additions except one 4-line change to `tests/test_cli.py`: the unimplemented-command probe retargeted `status` → `search anything`. Judged **not a weakening**: Phase 1 is spec-required to implement `status`, so the Phase-0 probe's example became stale while its assertions (exit code 2, clear message) are byte-identical; the change is recorded in DECISIONS.md D5 per §2.1.
3. `grep -rn "mock|Mock|monkeypatch" repograph/` → none.
4. `grep -rn "miniproject|fixtures" repograph/` → none (no hardcoded fixture paths in production code).
5. No `skip`/`xfail` markers anywhere in `tests/` (only incidental substring matches in a test name and a docstring). `pyproject.toml` pytest config is plain (`testpaths=["tests"]`, `addopts="-q"`), no deselection tricks.
6. New runtime deps `pygit2`, `sqlite-vec` are both on the approved §6 list; per-phase-declaration policy is recorded (D2).
7. Incremental sync is genuinely incremental, not a disguised rebuild: `test_sync_reindexes_only_new_blobs_on_modify` asserts exactly 1 blob reindexed after a modify; warm sync is 5× faster than cold on the bench; branch-switch test asserts pure reactivation with 0 blobs parsed.
8. Store queries (FTS, vector, symbol) all join `blobs ... AND b.active = 1`, so soft-deactivated rows cannot leak into search results.

## Exploratory attack

Built a fresh git repo containing: a Python file with emoji/π/non-ASCII
identifiers, a 5 MB generated `bundle.js`, a UTF-16-encoded `.py` file, a CRLF
`.ts` file, a filename with spaces/accents/`#` (`weird name éè (copy) #1.py`),
a self-referencing symlink (`selfloop -> .`) and a dangling symlink. Ran
`repograph init`, then `repograph sync` twice.

Result: no crashes; exit 0 everywhere. Indexed: emoji.py, crlf.ts, and the
weird-named file (3 blobs / 3 chunks). Skipped by design: 5 MB bundle (>2 MiB
size cap, D9), UTF-16 file (NUL-sniffed as binary, D6 — a known, documented
limitation, not a defect), both symlinks. Second sync fully idempotent
(0/0/0); `PRAGMA integrity_check` = ok.

## Findings

None blocking. Two non-blocking observations for future phases:

1. (observation) UTF-16-encoded source files are treated as binary and never
   indexed (consequence of D6 NUL-sniffing). Acceptable and documented for
   Phase 1; worth revisiting if a real repo ever ships UTF-16 sources.
2. (observation) The golden test uses `derandomize=True` with 6 hypothesis
   examples plus one pinned all-ops example to stay inside the <120 s CI
   budget (actual: 2.46 s). There is ~48× headroom; a future phase could
   afford more examples or occasional non-derandomized runs for extra
   coverage. Not a violation — the criterion is met as written.
