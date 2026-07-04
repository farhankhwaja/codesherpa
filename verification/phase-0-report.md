# Phase 0 Verification Report
Verdict: PASS
Date / commit verified: 2026-07-04 / 6551e832da8853779d7f867af24f65cde38b4aa4 (`chore: verifier agent (isolation: worktree) + progress/decisions/eval logs`)

Environment: isolated git worktree, fresh venv via `uv venv --python 3.12 .verifier-venv` (CPython 3.12.13), `uv pip install -e ".[dev]"` — install succeeded with zero runtime deps (pytest + hypothesis as dev extras).

Full test suite: `pytest -x -q` → **32 passed, 0 failed, 0 skipped** (test_cli: 4, test_contracts: 17, test_fixture_miniproject: 6, test_gold_queries: 5).

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 1 | `pyproject.toml` installs; `repograph --help` runs | PASS | `uv pip install -e ".[dev]"` clean; `.verifier-venv/bin/repograph --help` exits 0 and shows all six subcommands (init/sync/search/status/serve/bench). `--version` also wired. |
| 2 | `contracts/types.py` defines `Chunk`, `SymbolNode`, `Edge`, `SearchResult`, `PackedContext` (dataclasses, fully typed) | PASS | All five present as `@dataclass(frozen=True)`; every field annotated; enums `SymbolKind`/`EdgeKind`/`RetrievalSource` are `str` subclasses; `chunk_id` = `blob_hash:byte_start:byte_end` matches the content-addressed design. |
| 3 | `contracts/index_contract.py` defines `IndexStore` ABC | PASS | ABC with blob add/lookup/deactivate (`add_blob`, `has_blob`, `active_blobs`, `set_blobs_active` — soft-deactivate, never delete), file mapping, chunk CRUD (`add_chunks`, `get_chunk`, `chunks_for_blob`), symbol CRUD (`add_symbols`, `add_edges`, `get_definitions`, `get_edges`), FTS (`fts_search`) + vector (`vector_search`) + `symbol_search` query methods, plus meta. All `@abstractmethod`. |
| 4 | `contracts/retrieval_contract.py` defines `Retriever` ABC (`search`, `get_definition`, `get_callers`, `get_references`, `expand`) | PASS | All five abstract methods present with contract-correct signatures (`search(query, budget_tokens=4000) -> PackedContext`, etc.). |
| 5 | `tests/fixtures/miniproject/`: real git repo built by script, ≥15 Py + ≥10 TS files, cross-file imports and calls, ≥5 commits | PASS | Built via `python tests/fixtures/build_miniproject.py`. Verified independently: **20 .py files** (15 excluding `__init__.py`), **11 .ts/.tsx files**, **6 commits** (`git rev-list --count HEAD` = 6, including a modify + delete commit). Cross-file imports confirmed on both sides (e.g. `routes/tasks.py` imports from `db`, `models.task`, `utils.time`, `validators`; `TaskList.tsx` imports `TaskStore`, `TaskItem`, `pluralize`). Cross-file calls confirmed (`validate_title(...)`, `task_from_row(...)`, `utc_now_iso()` called in `routes/tasks.py`). Fixture is gitignored + rebuilt on demand; the spec explicitly allows "created by a script … committed as … build script". |
| 6 | `eval/gold_queries.jsonl` ≥20 entries: nl / exact-symbol / stack-trace mix, each with expected file(s) and symbol(s) | PASS | 25 valid JSONL entries: **14 nl, 7 symbol, 4 stacktrace**. Every entry has non-empty `expected_files` and `expected_symbols`. Programmatic cross-check of **all 25** entries against the built fixture: every expected file exists and every expected symbol appears in at least one of its expected files (0 failures). Manual spot-checks: `retry_request` (http_client.py:19), `fetchWithRetry` (http.ts:21), `validate_email` (validators.py:21), `slugify` (utils/text.py:8), `hash_password` (auth.py:11). |
| 7 | `.claude/agents/verifier.md` exists with `isolation: worktree` (§11) | PASS | Present, frontmatter includes `isolation: worktree`; procedure matches §11. |
| 8 | Verifier PASS → merge to main → spawn worktrees | N/A | This report is that sign-off; merge/spawn is the invoking session's next step. |

## Cheating hunt

1. Mock/fake imports in production code: `grep -rn "mock|Mock|monkeypatch|MagicMock" repograph/` → **no matches**.
2. Hardcoded fixture paths in production code: `grep -rn "miniproject|fixtures" repograph/` → **no matches**.
3. Test weakening: `grep -rn "skip|xfail" tests/` → **no matches**; all four test files contain real assertions (9/14/18/10 assert lines). This is the first phase, so no prior-phase diff exists to compare against.
4. Eval thresholds: CLAUDE.md §13 intact (recall@5 ≥ 0.80, MRR ≥ 0.60, latency, ≥50% A/B). `eval/run_eval.py` does not exist yet — correct for Phase 0 (only `gold_queries.jsonl` is required).
5. Contracts: written this phase (that is Phase 0's job); worktree is clean, no uncommitted modifications. From Phase 1 on, any diff under `repograph/contracts/` is an automatic FAIL.

None found.

## Exploratory attack

1. **Fixture determinism**: built the fixture twice; `git rev-parse HEAD` identical both times (`3f2519b4070e22382f913dc0cd8b456b431cb920`) — deterministic SHAs as claimed in DECISIONS.md D1.
2. **Hostile path**: built the fixture into a directory with spaces and unicode (`…/wörk dir ✓/nested/mini`) — succeeded, and produced the **same HEAD SHA**, proving determinism is location-independent.
3. **CLI outside a git repo**: ran `repograph --help` from a non-repo scratch directory — works (exit 0), no crash.

## Findings

None. All Phase 0 criteria pass from a clean checkout; a fresh session may merge per §3.3 (after committing this report) and spawn the three worktrees.

Informational (non-blocking) observations, no action required for Phase 0:
1. The trunk branch is `master`, while CLAUDE.md §3.3/§10 speak of merging to `main`. Not a Phase 0 criterion, but the team should settle the trunk name before worktree merges begin to avoid a split-brain trunk.
2. `pyproject.toml` declares zero runtime deps (justified in DECISIONS.md D2); the Verifier will re-check dep additions against the §6 approved list each phase.
