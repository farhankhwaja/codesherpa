# Progress

## Current phase & worktree
Phase 0 (Skeleton & Contracts) — done on `main`, pending Verifier sign-off.
Phase 1 has NOT been started (per explicit instruction). Next step after this:
spawn the three worktrees per CLAUDE.md §8 and start Phase 1 in `core-index`.

## Done (one line each, with commit hash)
- Phase 0 skeleton: pyproject (console script `repograph`), package dirs, stub CLI — (this commit)
- Frozen contracts: `contracts/types.py`, `index_contract.py`, `retrieval_contract.py` — (this commit)
- Fixture: `tests/fixtures/build_miniproject.py` builds deterministic git repo (15 non-init .py, 11 .ts/.tsx, 6 commits incl. modify+delete) — (this commit)
- Gold set: `eval/gold_queries.jsonl`, 25 queries (14 nl / 7 symbol / 4 stacktrace) — (this commit)
- Verifier agent: `.claude/agents/verifier.md` (isolation: worktree) — (this commit)
- Tests: contracts/CLI/fixture/gold-queries, 32 passing — (this commit)

## In progress
Nothing. Awaiting Phase 0 Verifier report → commit report → Phase 0 complete.

## Blocked / open questions
None.

## Notes for the next session
- **Golden Test first**: per §2.3, `tests/test_golden.py` must exist BEFORE any
  indexer code is written. It is the first task of Phase 1 (core-index worktree).
- Python: system has only 3.9; use `uv` (installed via brew) — `uv venv --python 3.12 .venv`,
  then `uv pip install -e ".[dev]" --python .venv/bin/python`.
- The miniproject fixture is generated, not committed: `tests/fixtures/miniproject/`
  is gitignored; tests build it on demand via the session-scoped `miniproject`
  conftest fixture. Build is deterministic (fixed dates/identity → same SHAs).
- Runtime deps are added per phase from the approved list (§6); pyproject
  currently has none (Phase 0 is stdlib-only). See DECISIONS.md D2.
- Contracts are now FROZEN. Worktrees code against the ABCs in
  `repograph/contracts/` only.
