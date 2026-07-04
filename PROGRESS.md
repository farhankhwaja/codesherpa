# Progress

## Current phase & worktree
Phases 1–2 COMPLETE (worktree `core-index`, Verifier PASS on both) and merged
to `main` per §3.3. Next: Phase 3 (embeddings + retrieval) in worktree
`retrieval` and Phase 4 (graph + MCP) in worktree `graph-mcp`, both building
against the frozen contracts and the now-real store.

## Done (one line each, with commit hash)
- Phase 0: contracts, fixture builder, gold set, verifier agent, PASS — dc77f33
- Golden Test v1 before any indexer code — 7e3e7c9
- SQLite IndexStore (schema.sql, FTS5, sqlite-vec lazy vec0 + brute-force fallback) — 591e164
- Line-window fallback chunker + dispatcher — dc09a25
- gitlayer init/sync (4 hooks, lockfile, skip rules) + CLI init/sync/status; golden green — e1f3c48
- Throughput ~200k LOC/s logged; D5–D9 — c56b44b
- Phase 1 Verifier PASS — b2dfc1a
- cAST chunker (tree-sitter Py/TS/JS/TSX, byte-exact, breadcrumbs+docstrings); 88 tests; D10–D12 — c2caf44
- Verifier Phase 2 round 1 FAIL fixes: deps declared, recursion-proofed (depth cap 50 + fallback net), JS test; 91 tests; D13 — f8284da
- Phase 2 Verifier PASS (supersedes FAIL) — bd05580

## In progress
Nothing in core-index. Store/gitlayer/chunker are live on main.

## Blocked / open questions
None.

## Notes for the next session
- venv: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python .venv/bin/python`;
  tests: `PATH=".venv/bin:$PATH" .venv/bin/python -m pytest -q` (one CLI test
  needs the console script on PATH).
- tree-sitter: use `tree_sitter.Parser(tslp.get_language(name))`, NOT
  `tslp.get_parser()` (Rust API, incompatible — D10).
- Store implements the frozen `IndexStore` ABC (`store/sqlite_store.py`);
  Phases 3/4 must code against the ABC. vec0 table is created lazily on first
  `put_embedding` (dim pinned in meta.vec_dim — D8).
- Sync tracks ref=HEAD only (D7); binaries never stored (D6); >2MiB skipped
  (D9); golden equality = ACTIVE projection.
- Chunker: add a language = one entry in `chunker/languages.py`. Depth cap 50
  then hard split (D13). Docstrings may be bare `string` nodes (D12).
- Fixture has no plain .js file (verifier info-note) — fine for Phase 2; a
  later fixture addition is allowed (core-index owns fixtures) but would
  change fixture SHAs, so coordinate with gold-set/eval work first.
- Phase 3 eval gates (§13): recall@5 ≥0.80, MRR ≥0.60, beat BM25-only and
  vector-only; p95 <500ms warm, router path <200ms/<50ms.
- GPG signing requires unsandboxed git commits (gpg agent socket).
