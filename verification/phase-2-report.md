# Phase 2 Verification Report
Verdict: PASS
Date / commit verified: 2026-07-04 / f8284dae7c21983c201c12f01aea19336bbd7413 ("fix: verifier Phase 2 findings — declare tree-sitter deps; recursion-proof cAST", branch `core-index`)

This report **supersedes the earlier Phase 2 FAIL run**. Blocking findings 1 (tree-sitter
deps missing from pyproject → clean install broken) and 2 (RecursionError in `_split` on
deeply nested oversized ASTs) were both re-tested from a fresh clone and are fixed.
Non-blocking finding 3 (no direct JS test) is also addressed.

Environment: fresh `git clone` of the core-index worktree at HEAD into a scratch dir;
`uv venv --python 3.12 .verifier-venv` (Python 3.12.13); `uv pip install -e ".[dev]"`.
Install succeeded with **zero manual dependency installs** — `tree-sitter==0.26.0` and
`tree-sitter-language-pack==1.12.2` were pulled automatically from
`[project].dependencies` (pyproject.toml lines 18–19).

## Criteria
| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 0 | Clean install: `uv pip install -e ".[dev]"` in fresh 3.12 venv | PASS | Installed repograph 0.0.1 + tree-sitter 0.26.0 + tree-sitter-language-pack 1.12.2; no manual steps (previous run FAILED here) |
| 1 | Full suite from clean checkout | PASS | `pytest`: **91 passed in 4.08s**, 0 skips/xfails |
| 2 | Split-then-merge per §7.2; oversized class recursed; small siblings merged; interstitial text byte-exact (reassembly == original) | PASS | `test_oversized_class_recursed_into_methods`, `test_small_siblings_merged`, `test_interstitial_text_preserved_byte_exact` all pass; `_reassemble` helper asserts full byte coverage, ordering, no gaps/overlaps |
| 3 | Same blob → identical chunk set (property test) | PASS | `test_same_blob_same_chunks_property` + hypothesis `test_property_valid_python_byte_exact_and_deterministic` (40 examples); determinism also asserted on the depth-capped path in `test_deeply_nested_ast_does_not_crash` |
| 4 | Py/TS/JS/TSX parse with 0 crashes; broken file → line windows + logged warning | PASS | `test_fixture_files_parse_without_fallback` parametrized over (.py) and (.ts,.tsx) asserts zero warning records; JS covered directly by new `test_javascript_class_chunks_and_breadcrumbs` and end-to-end by my attack (app.js indexed via `init`); `test_broken_file_falls_back_with_warning` asserts the "falling back to line windows" log record and L1-2 breadcrumb shape |
| 5 | Breadcrumbs: method in class carries `path :: ClassName :: def method(sig)` | PASS | `test_breadcrumb_method_in_class` asserts `# pyserver/svc.py :: BigService0 :: def method_...(self, value: int) -> int:` + docstring line; TS (`// webapp/src/widget.ts :: Widget :: method`) and JS (`// scripts/gadget.js :: Gadget :: method`) variants pass |
| 6 | Golden Test still green (now covering chunks) | PASS | `pytest tests/test_golden.py -q`: 1 passed, ~2.6 s wall (<120 s). Golden state includes per-blob `(chunk_id, code)` and FTS row-set comparison (test_golden.py lines 188–266) |
| 7 | Merge core-index → main per §3.3 | N/A | Gate for the implementing session after this PASS; contracts untouched, PROGRESS/DECISIONS updated (D10–D13 cover tree-sitter API, cAST design, docstring quirk, recursion guard) |

## Cheating hunt
1. `git diff dc77f33..f8284da -- repograph/contracts/` — **empty**. Frozen contracts untouched.
2. `git diff dc77f33..f8284da -- eval/` — **empty**. No threshold edits; CLAUDE.md §13 unchanged.
3. `git diff dc77f33..f8284da -- tests/` — additions only (1401 insertions, 1 deletion). The single deletion is the known Phase 1 `test_cli.py` change (probe command `status` → `search`, strengthening the test now that `status` is implemented; documented in DECISIONS.md D5, accepted at Phase 1 verification). No test deleted, skipped, weakened, or xfail-ed.
4. `grep -rn "mock|Mock|monkeypatch" repograph/` — no hits.
5. `grep -rn "miniproject|fixtures" repograph/` — no hits.
6. `grep -rn "skip|xfail" tests/` — only a test *name* (`test_sync_skips_binary_...`) and a docstring; no pytest skip/xfail markers.
7. Regression tests for the previous findings are genuine, not weakened: `test_deeply_nested_ast_does_not_crash` uses the **exact** previous attack payload (`b"var x=" + b"1+"*20_000 + b"1;"`) through the full dispatch path and additionally asserts chunk-size cap, byte-exact reassembly, and determinism.

## Exploratory attack
Re-ran the previous RecursionError attack exactly, from the clean venv with
`sys.setrecursionlimit(1000)` to make any stack blow-up obvious:

1. **39 KB chained-operator app.js** (`b"var x=" + b"1+"*20_000 + b"1;"`, 40 008 bytes)
   in a fresh scratch git repo, committed, then `gitlayer.initialize.init()`.
   Previous run: crashed with RecursionError. Now: **init succeeds** —
   `blobs_indexed=2, chunks_added=28`; app.js produced **27 hard-split cAST chunks**
   (breadcrumb `// app.js :: app :: var x=`), verified contiguous 0→40008 with no
   gaps/overlaps. `sync` run twice afterwards: both report
   `blobs_indexed=0, chunks_added=0` — **idempotent**.
2. **5.2 MB single-line big.js** variant: init succeeds, `paths_skipped=1`,
   0 file rows / 0 chunks for big.js (correctly rejected by the
   `MAX_FILE_BYTES = 2 MiB` cap in `gitlayer/ignore.py`), while the sibling
   ok.py was indexed normally.

(Note: initial `git commit` in the scratch repo failed due to this machine's global
gpg-signing config — an environment artifact unrelated to repograph; re-run with
`-c commit.gpgsign=false`.)

## Findings
None blocking.

1. [info] The miniproject fixture contains no `.js` files (20 py / 8 ts / 3 tsx), so the
   "JS parses on the fixture" clause is satisfied indirectly: JS chunking is covered by
   the direct unit test `test_javascript_class_chunks_and_breadcrumbs` and exercised
   end-to-end by the attack repro. Consider adding one small `.js` file to the fixture
   in a later phase (fixture is owned by core-index) — not required for Phase 2.

Phase 2 meets all §10 criteria from a clean checkout. A fresh session could proceed to
the §3.3 merge checklist without hesitation.
