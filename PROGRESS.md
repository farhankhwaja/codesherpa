# Progress

## Current phase & worktree
Phase 4 (Symbol Graph + MCP) — COMPLETE except one awaiting-human checkbox
(manual smoke, below). Full-scope Verifier PASS
(`verification/phase-4-report.md`); merged to main per §3.3 (graph-mcp
merges before retrieval, per §8). Phase 3 (retrieval) is the only worktree
still open; it re-runs the expansion delta inside the production pipeline at
its eval gate and must extend GOLDEN_PROJECTION with embeddings.

## Done (one line each, with commit hash)
- Phases 0–2 + golden hardening on main — dc77f33..c35392a
- Gold set hardened: +8 nl_hard (zero identifier-token overlap, ratchet-tested), +2 decoy; 35 entries; merged to main standalone — bb9e0d6
- Phase 4 rebased onto main; fixture-v2 test adaptations — 16707b2..
- Symbols/edges indexed through the REAL store on every sync; golden projection extended (symbols+edges; D14 exception exercised, see below); GOLDEN_DEEP 25/25 — ff237f6^..
- All graph/MCP/eval tests migrated to the real SQLite index; in-memory store deleted — ff237f6
- MCP integration test over REAL stdio transport (SDK client, subprocess server, every tool) — ff237f6
- Graph expansion behind config flag; recall@5 delta 0.000 (non-decreasing gate PASS, logged in EVAL_LOG) — ff237f6
- Suite: 179 tests green incl. golden

## In progress
Nothing in graph-mcp. Next: Phase 3 finishes in `retrieval`; then Phase 5
(hardening + benchmarks) on main, which also needs the human smoke transcript
below and a GOLDEN_DEEP=1 soak record (one PASS already logged in EVAL_LOG).

## Blocked / open questions
None blocking. **Awaiting human (Phase 4 manual-smoke checkbox — do NOT mark
done until a human runs it):**

- [ ] Manual smoke: connect Claude Code to this repo's index and run 3 real
  queries; paste transcripts into `verification/`.
  From the repo root (uses the current venv):
  1. `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python .venv/bin/python`
  2. `.venv/bin/repograph init` (builds `.repograph/index.db` incl. symbols/edges)
  3. Until Phase 3 merges (no production retriever yet), attach the test
     wiring: `claude mcp add repograph -- "$PWD/.venv/bin/python" "$PWD/tests/mcp_stdio_entry.py" "$PWD" "$PWD/.repograph/index.db"`
     (After Phase 3 merges, the canonical form is:
     `claude mcp add repograph -- "$PWD/.venv/bin/python" -m repograph.mcp_server "$PWD"`.)
  4. Suggested queries, then paste transcripts to `verification/phase4-smoke/`:
     - `search_code("how does sync decide which blobs are new")`
     - `get_callers("sync_graph")` (expect the call site inside gitlayer/sync.py, ranked, with rationale)
     - `get_recent_changes("HEAD~5")` (expect symbol-level diffs for recent commits)

## Notes for the next session
- Ownership exception EXERCISED (granted in test_golden.py + D14, recorded
  here per instruction): graph-mcp added `_project_symbols`/`_project_edges`
  and two GOLDEN_PROJECTION entries in tests/test_golden.py — nothing else
  in that file was touched. Phase 3 still owes the embeddings extractor.
- Graph design: symbols/edges are recomputed + REPLACED each sync
  (`graph/index.py`, D19) because edges are a global function of the active
  mapping; chunks/embeddings stay incremental. TODO(upgrade): persist
  per-blob extraction facts.
- Proposals to retrieval worktree (per §8): expose
  `repograph.retrieve.build_eval_retriever(repo_path, mode)` with
  mode ∈ {hybrid, bm25, vector} (run_eval default factory, D17) and
  `build_retriever(repo_path) -> (Retriever, store)` (consumed by
  `repograph serve` / `python -m repograph.mcp_server`, already wired).
  Graph-expansion hook for the pipeline: `SymbolGraph.neighbors()`
  (EXPANSION-tagged, ranked; ×0.6 discount precedent in
  tests/simple_retriever.py; re-run the expansion delta inside the real
  pipeline at the Phase 3 eval gate).
- nl_hard queries score 0.12 recall@5 lexically (by design); the Phase 3
  hybrid must close that gap to clear the 0.80 gate. Full numbers in
  EVAL_LOG.md.
- venv: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python .venv/bin/python`;
  tests: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -q`.
- tree-sitter: use `tree_sitter.Parser(tslp.get_language(name))` (D10);
  python grammar inlines expression_statement; awaited TS generic callees
  nest under await_expression (graph/queries/*.scm).
- Store: `store/sqlite_store.py` implements the frozen ABC; vec0 lazy on
  first put_embedding (D8); sync tracks HEAD only (D7); >2MiB skipped (D9 —
  this also shields graph extraction, closing advisory A1).
- Fixture v2 (7 commits; version marker auto-rebuilds prebuilt copies).
- GPG signing requires unsandboxed git commits (gpg agent socket).
- Verifier informational finding (pre-rebase run): router token regex is
  ASCII-only — non-ASCII identifiers skip the <50 ms fast path (graceful
  dense-path fallback, no crash). Widen `_TOKEN_RE` if needed.
