# Progress

## Current phase & worktree
Phases 0–2 complete and merged to main (plus golden-test hardening D14).
Phase 4 (Symbol Graph + MCP) integration underway in worktree `graph-mcp`:
pre-merge build was verifier-PASSed against the contracts + in-memory store;
now rebased onto main and being wired to the real SQLite store. Phase 3
(retrieval) runs in parallel in worktree `retrieval`.

## Done (one line each, with commit hash)
- Phase 0: contracts, fixture builder, gold set, verifier agent, PASS — dc77f33
- Phase 1: SQLite store, gitlayer init/sync + hooks, golden v1, throughput logged, verifier PASS — e1f3c48..b2dfc1a
- Phase 2: cAST chunker (Py/TS/JS/TSX), verifier PASS after findings fixed — c2caf44..bd05580
- Golden hardening: real-merge op, GOLDEN_DEEP soak, fixture v2 (+export_tasks.js), GOLDEN_PROJECTION; D14 — c35392a
- Phase 4 pre-merge (graph extraction, ranked queries, recent_changes, MCP server, eval harness, verifier PASS) — rebased onto main in this worktree

## In progress
graph-mcp: Phase 4 integration against the real store (this session).
Next concrete steps: finish rebase → harden gold queries (merge to main
standalone; retrieval is blocked on it) → index symbols/edges through the
real store → extend GOLDEN_PROJECTION per D14 exception → full §10 Phase 4
criteria → verifier → merge per §3.3.

## Blocked / open questions
None.

## Notes for the next session
- venv: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python .venv/bin/python`;
  tests: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -q` (one CLI
  test needs the console script on PATH).
- tree-sitter: use `tree_sitter.Parser(tslp.get_language(name))`, NOT
  `tslp.get_parser()` (Rust API, incompatible — D10). Python grammar inlines
  `expression_statement`; TS wraps awaited generic callees in
  `await_expression` (handled in graph/queries/*.scm).
- Store implements the frozen `IndexStore` ABC (`store/sqlite_store.py`);
  Phases 3/4 code against the ABC. vec0 created lazily on first
  `put_embedding` (dim in meta.vec_dim — D8).
- Sync tracks ref=HEAD only (D7); binaries never stored (D6); >2MiB skipped
  (D9); golden equality = ACTIVE projection.
- Golden projection: Phases 3/4 MUST extend GOLDEN_PROJECTION in
  tests/test_golden.py (embeddings; symbols+edges) — explicit ownership
  exception recorded there and in D14. GOLDEN_DEEP=1 soak must pass once
  before the Phase 5 merge.
- Fixture is v2 (commit 7 adds webclient/scripts/export_tasks.js; earlier
  SHAs unchanged; version marker auto-rebuilds stale prebuilt fixtures).
- Graph resolution precision heuristics: D16 (language-family fence,
  generic-name stoplist) — precision > recall for get_callers.
- Phase 3 eval gates (§13): recall@5 ≥0.80, MRR ≥0.60, beat BM25-only and
  vector-only; p95 <500ms warm, router path <200ms/<50ms. Harness:
  eval/run_eval.py; factory contract in D17.
- GPG signing requires unsandboxed git commits (gpg agent socket).
