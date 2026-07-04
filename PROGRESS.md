# Progress

## Current phase & worktree
Phase 1 (Git Layer + Store) — implementation complete in worktree
`core-index`; awaiting Verifier run. Phase 2 (cAST chunker) follows in this
same worktree, then merge to main per §3.3.

## Done (one line each, with commit hash)
- Phase 0 complete on main (contracts, fixture builder, gold set, verifier agent, PASS report) — dc77f33
- Golden Test v1 written before any indexer code (hypothesis, 6 examples + pinned all-ops example) — 7e3e7c9
- SQLite IndexStore: schema.sql, FTS5, sqlite-vec lazy vec0 + brute-force fallback, embedding cache — 591e164
- Chunker dispatcher + line-window fallback (120/20, byte-exact, deterministic) — (chunker commit)
- gitlayer: init (4 hooks, .repograph/, .gitignore) + blob-diff sync (lockfile, idempotent, skip rules); CLI init/sync/status; golden green — (gitlayer commit)
- Throughput bench: ~200k LOC/s cold sync (target ≥2k) logged in EVAL_LOG.md; DECISIONS D5–D9 — (bench commit)

## In progress
Phase 1 Verifier run (agent `.claude/agents/verifier.md`), then Phase 2:
cAST split-then-merge chunker via tree-sitter + tree-sitter-language-pack for
python/typescript/javascript/tsx, slotting into `chunker/dispatch.chunk_blob`.

## Blocked / open questions
None.

## Notes for the next session
- venv: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python .venv/bin/python`.
  Run tests with `.venv/bin` on PATH (one CLI test needs the console script):
  `PATH=".venv/bin:$PATH" .venv/bin/python -m pytest -q`.
- Sync semantics: single indexed ref = HEAD (D7). Binary blobs never stored
  (D6). Blob at N paths indexed once under sorted-first path. Golden equality
  is over the ACTIVE projection (inactive rows are retained by design).
- The store is the concrete `SQLiteIndexStore`; extra non-contract helpers are
  allowed on the concrete class but retrieval/graph code must use the ABC.
- Phase 2 must keep: reassembly byte-exactness (fallback chunker property test
  exists), same-blob-same-chunks determinism, golden test green, and re-measure
  throughput with tree-sitter parsing on (EVAL_LOG entry).
- GPG signing: commits must run unsandboxed (gpg agent socket) — commit with
  dangerouslyDisableSandbox or expect "No agent running".
