# Phase 4 Verification Report (full integrated scope, gates §3.3 merge)
Verdict: PASS
Date / commit verified: 2026-07-04 / 0974226 (`worktree-graph-mcp`, rebased on main bb9e0d6)

Verifier environment: fresh `uv venv --python 3.12 .verifier-venv` (CPython
3.12.13), `uv pip install -e ".[dev]"` — install clean (pygit2, sqlite-vec,
tree-sitter 0.26.0, tree-sitter-language-pack 1.12.2, mcp 1.x). `repograph
--help` runs; `import repograph, mcp, pygit2` ok.

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 0a | Full suite from clean checkout | PASS | `.verifier-venv/bin/python -m pytest -q` → exit 0, 179 tests (72+72+35 dots), no skips/xfails anywhere in `tests/` (grep clean) |
| 0b | Golden Test green (now incl. symbols+edges projections) | PASS | `pytest tests/test_golden.py -q` → 1 passed (3.8 s). Bonus: `GOLDEN_DEEP=1` randomized soak → exit 0 |
| 1 | Defs/refs/imports/calls for Py+TS on fixture; ≥10 known edges spot-checked | PASS | `tests/test_graph_extract.py` + `tests/test_graph_index.py` → 53 passed. 28 parametrized known edges (15 CALLS incl. TS/TSX, 5 IMPORTS, 5 REFERENCES, 3 DEFINES) cross-checked against fixture sources; `test_graph_index.py` proves the same edges survive the REAL SQLite store via real `gitlayer.sync` (incl. delete-file cleanup and the new-file-rebinds-callers case that motivated D19) |
| 2 | `get_callers` ranked with rationale | PASS | `tests/test_graph_view.py` → 9 passed against the real store: same-file caller outranks cross-package; scores strictly sorted; every result carries rationale ("calls X", "inbound refs", "last changed" from git recency), expand_id, token_count; recency tie-break test on synthetic real-store graph |
| 3 | `get_recent_changes(since)` correct vs fixture history | PASS | `tests/test_recent_changes.py` → 8 passed (fixture v2, 7 commits): ref + ISO-date since, newest-first, symbol-level added/modified/removed diffs, limit, unknown-ref ValueError, compact payload |
| 4 | MCP integration test via SDK client; every tool; valid schemas; <4000 tokens default | PASS | `tests/test_mcp_server.py` → 5 passed. Primary test runs over the REAL stdio transport (subprocess server `tests/mcp_stdio_entry.py`, real SQLite index): all 7 §7.6 tools called in one session, schemas checked, `total_tokens ≤ budget == 4000` AND serialized response < 4000 est. tokens (D18), expand round-trip, grep-selling descriptions. Edge cases (router path, 300-token budget, unknown expand_id, bad ref → tool error) on in-memory session |
| 5 | Graph expansion behind config flag; eval re-run; recall@5 non-decreasing; delta logged | PASS (scoped pre-Phase-3, judged faithful) | Expansion hook = `SymbolGraph.neighbors()` (production); flag + ×0.6 discount in tests-only stand-in `tests/simple_retriever.py` (§7.5.5 shape). `tests/test_run_eval.py::test_graph_expansion_does_not_reduce_recall` asserts non-decrease over the real store, permanently. EVAL_LOG.md logs delta 0.000 (0.686 → 0.686 recall@5, MRR 0.649 both). Production pipeline re-run explicitly assigned to the Phase 3 eval gate in PROGRESS.md. Given Phase 3 is unmerged and §8 has graph-mcp building against contracts pre-merge, this satisfies the criterion as literally as is possible today; the obligation is not silently dropped |
| 6 | Manual smoke via `claude mcp add` + 3 queries, transcripts in verification/ | AWAITING-HUMAN (not done, not failed) | PROGRESS.md "Blocked / open questions" contains the exact commands (venv, `repograph init`, `claude mcp add` with `tests/mcp_stdio_entry.py`, 3 suggested queries + transcript destination). Runnable in principle: verified `repograph init` end-to-end on a scratch repo (db + all four hooks + .gitignore + first index) and the stdio entry works under the SDK client (criterion 4's subprocess test). PROGRESS explicitly forbids marking it done before a human runs it |
| 7 | Eval harness sanity (Phase-4-owned `eval/`) | PASS | `tests/test_run_eval.py` → 9 passed: thresholds frozen at 0.80/0.60 (asserted by test), gate requires hybrid to strictly beat baselines, CLI pass/fail exit codes, gold set loads (35 entries) |

§3.3 merge checklist (items checkable by the verifier):
- Full suite from clean checkout: PASS (exit 0)
- Golden Test: PASS (+ deep soak)
- Eval scores appended to EVAL_LOG.md: yes (Phase 4 entry with expansion ON/OFF table, delta 0.000; correctly labeled NOT a Phase 3 gate run)
- `repograph/contracts/` vs main: **empty diff** — unmodified
- PROGRESS.md / DECISIONS.md updated: yes (D15–D21; PROGRESS current, <150 lines)
- Verifier PASS report committed: this report (committing it is the last box)

## Cheating hunt

1. `git diff main -- tests/`: additions only except `tests/test_golden.py`
   (+30/−2) — verified to contain ONLY `_project_symbols`/`_project_edges`,
   two `GOLDEN_PROJECTION` entries, and the matching NOTE-comment edit;
   exactly the D14 ownership exception. No test deleted/weakened vs main.
2. D20 claim (MCP tests folded, assertions moved not removed) — verified by
   line-by-line comparison of `ff237f6^:tests/test_mcp_server.py` (11 tests)
   vs HEAD (5 tests): every assertion from the 11 old tests is present in the
   stdio test or retained as an edge-case test. Two intentional substitutions,
   both equal-or-stronger: `last_sync_ref == "HEAD"` (in-memory fake meta) →
   real meta keys `last_sync`/`last_sync_head` + `head == last_sync_head`;
   `"pyserver/auth.py" in files` subsumed by the changed-symbols assertion on
   the same file. Net: real transport + real store + one NEW test (tiny
   budget). Claim verified — not a §2.1 weakening.
3. D21 claim (gold set strengthened): `tests/test_gold_queries.py` and
   `eval/gold_queries.jsonl` are IDENTICAL to main (hardening merged as
   bb9e0d6, already on main). VALID_TYPES={nl,symbol,stacktrace,nl_hard,
   decoy} with all five REQUIRED, min count 35 (raised from 20). Additive
   strengthening confirmed.
4. `tests/inmemory_store.py` deleted (was tests-only, 228 lines): replaced by
   the real `SQLiteIndexStore` + real sync in every consumer — coverage moved
   onto the production path, none lost.
5. Mocks in production: `grep -rn "mock|Mock|monkeypatch" repograph/` → only a
   docstring in `mcp_server/__main__.py` saying it refuses to serve mock data
   (verified: exits 2 with an honest message until Phase 3 provides
   `build_retriever` — §2.5 compliant, no fake data path).
6. Hardcoded fixture paths in `repograph/`: grep for `miniproject|fixtures` →
   none.
7. Eval thresholds: `eval/run_eval.py` RECALL_AT_5_MIN=0.80, MRR_MIN=0.60,
   module constants, no CLI override; `test_thresholds_are_frozen_values`
   ratchets them. CLAUDE.md §13 unchanged vs main (empty diff).
8. Production diff vs main outside graph-mcp's §8 ownership: `pyproject.toml`
   (+3 approved §6 deps), `cli.py` (+9: `serve` wiring), `gitlayer/sync.py`
   (+14: `sync_graph` call inside the existing lock). All post-merge shared
   edits, permitted by §8 once core-index merged; minimal and reviewed.
   `store/` untouched.

No cheating found.

## Exploratory attack

Scratch repo (outside the worktree) containing: (a) `huge.js` — 5 MB of
syntactically valid generated JS (a graph-supported language, so it would hit
tree-sitter extraction if the >2 MiB skip failed); (b) `🚀rocket.py` — emoji
filename, emoji string/comment content, and non-ASCII unicode identifiers
(`café_lookup`, `naïve_arg`); (c) `main_module.py` calling `café_lookup`
cross-file. Results, all through the real pipeline:

- `sync`: `paths_skipped=1`, `huge.js` absent from `files`, ZERO `gen_*`
  symbols leaked into the graph — D9 skip shields graph extraction as claimed
  (closes old advisory A1 by construction).
- `get_definition("café_lookup")` → `🚀rocket.py`; `get_callers` returns the
  cross-file caller ranked with full rationale ("calls café_lookup; same
  package; 0 inbound refs").
- Re-sync idempotent (symbols/edges/chunks tables byte-identical).
- Two concurrent subprocess syncs (stress on the new DELETE+REPLACE graph
  step under the lockfile): both exit 0, tables unchanged, `PRAGMA
  integrity_check` = ok.
- Fresh rebuild DB == incremental DB on the attack repo (mini golden).
- Bonus CLI smoke: `repograph init` on the attack repo → index.db + all four
  hooks + .gitignore update + correct `repograph status` (5 symbols, 4 edges).

Attack survived completely. (One earlier failure was a bug in the verifier's
own script — macOS `multiprocessing` spawn semantics — not in repograph.)

## Findings

None blocking. Verdict PASS. Notes for the record (not defects):

1. Criterion "manual smoke via claude mcp add" is AWAITING-HUMAN by design;
   preparation verified runnable. The checkbox must not be marked done until
   a human pastes transcripts into `verification/` (Phase 4's §10 list keeps
   one open box until then; merging now is justified by PROGRESS.md's
   explicit tracking of the outstanding human step — flagging so the merge
   decision is made consciously).
2. The Phase 3 session MUST re-run the expansion delta inside the production
   pipeline at its eval gate (already assigned in PROGRESS.md) and provide
   `repograph.retrieve.build_retriever` / `build_eval_retriever` per D17.
3. `python -m repograph.mcp_server` intentionally exits 2 until Phase 3;
   after Phase 3 merges, the PROGRESS smoke instructions should switch to the
   canonical form (already noted there).
