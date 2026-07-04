# Phase 4 Verification Report (PRE-MERGE scope)
Verdict: PASS
Date / commit verified: 2026-07-04 / 3b822aea3e81cfa2459f2f265d29ce5c4b97cc36 (branch `worktree-graph-mcp`)

Scope: per CLAUDE.md §8, graph-mcp built Phase 4 against the frozen contracts
with a tests-only in-memory index; Phases 1–3 have not merged to main. Three
§10 Phase 4 criteria are therefore **pending integration** (not failures):
graph-expansion wiring + eval re-run, `claude mcp add` manual smoke, and
rebase/integrate/merge. This PASS covers the pre-merge criteria only; a full
Phase 4 verification must be re-run after rebase on a main containing
Phases 1–3.

Environment: fresh detached checkout in an isolated verifier worktree; clean
venv `uv venv --python 3.12` + `uv pip install -e ".[dev]"` — install clean,
`repograph --help` runs.

## Criteria
| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 0a | Clean install from checkout | PASS | `uv pip install -e ".[dev]"` succeeds; console script runs |
| 0b | Full test suite | PASS | `python -m pytest -v` → **115 passed in 1.68s**, 0 skipped/xfailed |
| 0c | Golden Test | N/A pre-merge | `tests/test_golden.py` does not exist on main or this branch; it is owned by the unmerged core-index worktree (Phase 1). Must exist and pass before any merge to main (§2.3). |
| 1 | Defs/refs/imports/calls for Py+TS on fixture; spot-checks assert ≥10 known edges | PASS | `tests/test_graph_extract.py`: 15 known CALLS edges + 5 IMPORTS + 5 REFERENCES + 3 DEFINES, parametrized against the unmodified Phase-0 fixture builder; plus kind checks, signatures, determinism, cross-language fence. All green. |
| 2 | `get_callers` returns ranked results with rationale fields | PASS | `tests/test_graph_view.py`: scores strictly descending; same-file caller (`fetch_json`) outranks cross-package caller; every result carries `rationale` ("calls retry_request", "inbound refs", recency), `expand_id`, `token_count`; recency tie-break test. All green. |
| 3 | `get_recent_changes(since)` correct against fixture history | PASS | `tests/test_recent_changes.py`: since=ref (`HEAD~2`) and since=ISO date; symbol-level diffs added/modified/removed match known fixture commits; deleted-file symbols reported `removed`; limit; unknown ref → clean ValueError. All green. |
| 4 | MCP server integration test via SDK client; every tool callable; schemas valid; responses < 4000 tokens default | PASS | `tests/test_mcp_server.py` uses `mcp.shared.memory.create_connected_server_and_client_session` (SDK in-memory client). All 7 §7.6 tools listed and called; input schemas validated (`type: object`, properties present); `search_code` response asserted `estimate_tokens(text) < 4000` and `total_tokens ≤ budget_tokens == 4000` (envelope trimming per DECISIONS D8); expand round-trip; bad ref → tool error not crash. All green. |
| — | Graph expansion wired into retrieval pipeline + eval re-run | PENDING INTEGRATION | Needs Phase 3 `retrieve/`. Hook ready (`SymbolGraph.neighbors()` tested, EXPANSION-tagged). |
| — | Manual smoke via `claude mcp add` on this repo | PENDING INTEGRATION | Needs real index (Phases 1–3). `repograph serve` / `python -m repograph.mcp_server` exit 2 with a clear "Phase 3 missing" message rather than serving mock data (tested in `test_cli.py`). |
| — | Rebase, integrate, all green → merge | PENDING INTEGRATION | Merge order §3.3: core-index must merge first. |

## Cheating hunt
1. `git diff main -- tests/` — additions only (7 new test files + 2 test
   doubles + 13 added lines in `test_cli.py` for `serve`). No test deleted,
   modified, skipped, weakened, or xfail-ed. `tests/fixtures/`, `conftest.py`,
   `eval/gold_queries.jsonl` byte-identical to main.
2. `repograph/contracts/` — zero diff vs main (frozen contracts intact).
3. Mocks in production code: none. The only grep hit is a docstring in
   `mcp_server/__main__.py` explaining it refuses to serve mock data. The
   in-memory store and naive retriever live in `tests/` only
   (`tests/inmemory_store.py`, `tests/simple_retriever.py`).
4. Hardcoded fixture paths in `repograph/`: none (`miniproject|fixtures|pyserver|webclient` → no hits outside a Phase-0 docstring example in contracts).
5. Eval thresholds: `eval/run_eval.py` module constants `RECALL_AT_5_MIN = 0.80`,
   `MRR_MIN = 0.60`, no CLI override; CLAUDE.md §13 has zero diff vs main.
   EVAL_LOG.md entry is explicitly informational (naive baseline 0.68/0.62),
   not a gate claim.
6. No `skip`/`xfail` markers anywhere in `tests/` (only a test *named*
   `test_unsupported_language_is_skipped`, which is a real behavior test).

## Exploratory attack
Ran weird inputs through `repograph.graph.extract`, `gitio`, and
`recent_changes` in a scratch dir:
- **Unicode/emoji identifiers (Python)**: `café`, `Résumé`, emoji string
  literals — correct symbols, correct CALLS/DEFINES edges, byte offsets sane.
- **~2.8 MB single-line generated JS (60k functions)**: no crash; 60,000
  symbols + 119,997 edges extracted — but took **328 s** (see Finding A1).
- **UTF-16 Python file**: no crash; graceful fallback to module-only node.
- **CRLF TypeScript**: correct extraction (3 symbols, 3 edges).
- **Empty repo (no commits)**: `recent_changes` raises a clean ValueError;
  `source_files_at_rev` / `last_change_dates` leak a raw
  `subprocess.CalledProcessError` (see Finding A2).
- **Emoji-named file committed to a repo**: extraction and `recent_changes`
  both correct.

## Findings
No FAIL-level findings. Advisories (not Phase 4 pre-merge criteria; carry
forward to integration):

- **A1 (perf, integration risk):** `extract_project` has no file-size guard
  and spends ~5.5 min on a 2.8 MB single-line generated JS file (resolver
  cost over 60k symbols). §7.1 says generated/minified files are skipped by
  the git layer, which is unmerged — after integration, verify gitlayer's
  skip logic actually protects `graph/` from such files, or add a size guard.
- **A2 (robustness, minor):** on a repo with zero commits,
  `gitio.source_files_at_rev` and `gitio.last_change_dates` raise raw
  `CalledProcessError` (git exit 128 on missing HEAD) instead of a clean
  domain error. The MCP SDK converts handler exceptions to tool errors, so
  the server does not crash, but the error text is unfriendly. Worth
  normalizing when gitio is routed through gitlayer (DECISIONS D5
  TODO(upgrade)).
- **A3 (bookkeeping):** the Golden Test does not exist yet anywhere on this
  branch or main. That is correct ownership-wise (core-index, Phase 1), but
  §3.3 makes it a hard gate for the eventual merge — the post-integration
  Phase 4 verification must run it.
