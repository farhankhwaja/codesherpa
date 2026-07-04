# Progress

## Current phase & worktree
Phase 2 (cAST Chunker) — implementation complete in worktree `core-index`;
awaiting Verifier, then merge core-index → main per §3.3. Phase 1 already has
a Verifier PASS (`verification/phase-1-report.md`).

## Done (one line each, with commit hash)
- Phase 0 complete on main (contracts, fixture builder, gold set, verifier agent) — dc77f33
- Golden Test v1 written before any indexer code (hypothesis + pinned all-ops example) — 7e3e7c9
- SQLite IndexStore: schema.sql, FTS5, sqlite-vec lazy vec0 + brute-force fallback — 591e164
- Chunker dispatcher + line-window fallback (120/20, byte-exact) — dc09a25
- gitlayer: init (4 hooks, .repograph/, .gitignore) + blob-diff sync (lockfile, idempotent, skip rules); CLI init/sync/status — e1f3c48
- Throughput bench ~200k LOC/s; EVAL_LOG entry; DECISIONS D5–D9 — c56b44b
- Phase 1 Verifier PASS report committed — b2dfc1a
- cAST chunker: tree-sitter split-then-merge Py/TS/JS/TSX, byte-exact, breadcrumbs w/ docstrings, fallback on parse errors; 88 tests green; ~152k LOC/s; D10–D12 — c2caf44

## In progress
Phase 2 Verifier run, then the §3.3 merge checklist (full suite from clean
checkout, golden green, EVAL_LOG updated, verifier PASS committed, no
contract edits, PROGRESS/DECISIONS current) and merge core-index → main.

## Blocked / open questions
None.

## Notes for the next session
- venv: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python .venv/bin/python`;
  run tests `PATH=".venv/bin:$PATH" .venv/bin/python -m pytest -q` (one CLI test
  needs the console script on PATH).
- tree-sitter: MUST use `tree_sitter.Parser(tslp.get_language(name))` —
  `tslp.get_parser()` returns an incompatible Rust-API parser (D10).
- Sync semantics: single indexed ref = HEAD (D7); binaries never stored (D6);
  golden equality is over the ACTIVE projection.
- After merge: spawn/continue `graph-mcp` (Phase 4) and `retrieval` (Phase 3)
  worktrees; core-index owns gitlayer/, chunker/, store/, test_golden.py, fixtures.
- Chunker config lives in `chunker/languages.py` (one entry per language);
  graph queries files (Phase 4) are separate and owned by graph-mcp.
- GPG signing requires unsandboxed commits (gpg agent socket).
