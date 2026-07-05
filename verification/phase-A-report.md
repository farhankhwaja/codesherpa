# Phase A Verification Report — Go language support (feature/go-support)
Verdict: PASS
Date / commit verified: 2026-07-05 / 8cd591de02679f1b9f2142c6d64f5d7782247a71 (branch `feature/go-support`, 2 commits ahead of main 57ffb64)

Method: fresh `git clone` of the repo, checkout `feature/go-support`, fresh
`uv venv --python 3.12` (Python 3.12.13), `pip install -e ".[dev]"` — install
clean. All commands below ran from that clean clone with the venv active
(canonical invocation `python -m pytest`, per CI; venv bin on PATH is required
by the console-script test — verified that the one failure seen without
activation disappears with the venv active, i.e. environment quirk, not code).

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 1a | Go chunking via tree-sitter-language-pack, cAST split-then-merge (functions, receiver methods, type decls, const/var blocks) | PASS | `chunker/languages.py` adds a `LanguageSpec("go")` with scope/definition node types only — architecture rule (language = spec + query file) held. 8 tests in `tests/test_chunker_go.py` cover each shape; all green. |
| 1b | Method breadcrumbs `path :: (ReceiverType) :: func sig`, pointer stripped | PASS | `test_method_breadcrumb_carries_receiver_type` asserts `// pkg/store.go :: (Store) :: func (s *Store) Save` and that plain functions carry no receiver scope. `cast.py::_receiver_type` strips `*` generically. |
| 1c | Byte-exact reassembly + arbitrary-bytes hypothesis property | PASS | `test_reassembly_is_byte_exact` (contiguity asserted pairwise), `test_arbitrary_bytes_never_crash_and_cover` (`@given(st.binary(...))`, 25 examples, full 0..len coverage). Same standard as existing languages. |
| 1d | Unparseable Go → line windows + logged warning | PASS | `test_broken_go_falls_back_to_line_windows` asserts `chunk_ast` returns None, fallback breadcrumb `L1-…`, and the "falling back to line windows" WARNING record. |
| 2a | go.scm: defs (functions, receiver-keyed methods, types, package consts/vars), aliased imports, refs, calls | PASS | `graph/queries/go.scm` has all capture families; `test_definition_kinds`, `test_package_level_consts_and_vars_only` (block-locals excluded), `test_aliased_import_produces_module_edge_and_cross_package_call`, `test_stdlib_imports_resolve_to_nothing` all green. |
| 2b | Receiver-typed resolution, type evidence AUTHORITATIVE (no match → dropped edge) | PASS | `extract.py::resolve_method` consults only the evident type's methods; `test_receiver_typed_call_disambiguation` (two types share `Flush`, never cross-wired) and `test_interface_satisfaction_is_not_resolved` (interface param → zero call edges) both green. |
| 2c | No interface-satisfaction resolution, documented (D43) + pinned by tests | PASS | DECISIONS.md D43(b) states it explicitly ("interface-satisfaction resolution is explicitly out of scope"); go.scm header repeats it; both pinning tests present in `tests/test_graph_extract_go.py`. |
| 2d | get_callers ranked with rationale for Go | PASS | `test_get_callers_ranked_with_rationale_for_go`: rationale non-empty and mentions the symbol; same-package caller must rank above cross-package. Green. |
| 3a | Fixture goexport/gorunner ≥4 files, struct+methods, interface, cross-file calls, aliased import | PASS | Commit 8 adds go.mod + `goexport/{archive,sink,compact}.go` + `gorunner/main.go` (4 .go files): `Archive` struct w/ 4 methods, `Sink` interface, `Flush→CompactRows` cross-file, `ax "example.com/taskhub/goexport"` aliased import. |
| 3b | APPEND-ONLY commit 8; commits 1–7 SHAs unchanged; deterministic-build test | PASS | Built the fixture from BOTH builders (main's and branch's) in scratch: commits 1–7 SHAs byte-identical (e92a87e9…660ccccd), branch appends only `6e1a7a1d… feat: go export service`. `test_build_is_deterministic` unchanged vs main and green. FIXTURE_VERSION 2→3 confirmed in the diff. |
| 3c | ≥8 known-edge spot-checks against the REAL synced store | PASS | `tests/test_graph_go_fixture.py`: 9 explicit edge tests (edge_1…edge_9) + kinds test + interface-field-ladder test + ranked-callers test (12 tests). Store fixture = `synced_miniproject` → `codesherpa.gitlayer.sync.sync()` on a copy of the real fixture repo; no mocks. |
| 3d | ≥4 Go gold queries incl. ≥1 nl_hard, additive; old 35 byte-identical; nl_hard ratchet intact | PASS | `head -35` of branch file `diff`s clean against main's file (byte-identical); q36 nl / q37 symbol / q38 nl_hard / q39 stacktrace appended. `tests/test_gold_queries.py` has zero diff vs main; ratchet test passed in the full run. |
| 4a | Full suite green from clean checkout | PASS | `python -m pytest -x -q -rs`: exit 0, 323 collected, 0 failed, 0 skipped (no `s` in output; `-rs` reported nothing). |
| 4b | Golden Test + GOLDEN_DEEP=1 soak | PASS | `pytest tests/test_golden.py -q` exit 0; `GOLDEN_DEEP=1 pytest tests/test_golden.py -q` exit 0 (ran both myself). |
| 4c | Official eval gate, 39 queries, thresholds untouched | PASS | `python eval/run_eval.py --repo <fresh fixture build> --mode all`: hybrid **0.974 / 0.869** (p50 166 ms, p95 181 ms), bm25 0.744/0.611, vector 0.795/0.714, sole miss q28 (pre-existing), nl_hard 0.89 → `GATE: PASS`, exit 0. `RECALL_AT_5_MIN = 0.80`, `MRR_MIN = 0.60` — `eval/run_eval.py` has ZERO diff vs main. |
| 4d | DECISIONS.md D43 | PASS | D43 present (a–d): receiver breadcrumbs, evidence-authoritative resolution, package-import representative-file resolution, router code-context morphology; documents the interface non-goal and the Go generic-name stoplist additions. |
| 5 | Cheating hunt | PASS (see below) | — |
| 6a | Standing attack D38-final: clean-clone `sherpa init .` under `/usr/bin/time -l` | PASS | Exit 0; embedding reached `810/810 (100%)`; maximum resident set size 4,433,936,384 B ≈ **4.13 GiB < 6 GB**. |
| 6b | Exploratory Go attack | PASS | See below. |

## Cheating hunt

1. `git diff main --name-only`: exactly 18 files. `codesherpa/contracts/` — zero diff. `eval/run_eval.py` — zero diff. `CLAUDE.md` §13 — zero diff. `eval/ab_harness.md` — zero diff.
2. `EVAL_LOG.md`: 0 removed lines vs main (append-only); +21-line Phase A entry.
3. Modified tests: `test_recent_changes.py` and `test_mcp_server.py` changes are pure fixture-v3 history shifts (HEAD~N and index bumps for the appended commit), scrutinized line-by-line — every prior assertion survives at its shifted anchor, plus a NEW `test_new_go_files_symbols_are_added`; strictly equivalent-or-stronger. `test_gold_queries.py`, `test_golden.py`, `conftest.py` untouched.
4. `tests/test_router_tokens.py` was also modified — outside the two files the phase enumerated as allowed, but the diff is +27/−0: two brand-new tests (Go stack-trace positive + D21 sentence-case anti-hijack negative), no existing line touched. Additive in substance; noted as Finding 3, not a violation.
5. No `skip`/`xfail` anywhere in the touched tests; no deleted tests.
6. `grep -rn "mock|Mock|monkeypatch" codesherpa/` → empty. `grep -rn "miniproject|fixtures" codesherpa/` → empty. `grep -rn "goexport|gorunner|NewArchive|CompactRows|taskhub" codesherpa/` → one COMMENT in `retrieve/router.py` using `goexport.(*Archive).Flush` as an illustrative example; the code itself (`_CODE_CONTEXT_RES` regexes) is fully generic. Verified against a sentence-case prose query that the D21 anti-hijack property still holds (pinned by the new negative test).
7. Fixture builder diff is append-only: version constant, one new commit dict, one `COMMITS` list entry. Proven behaviorally by the dual-builder SHA comparison (criterion 3b).

## Exploratory attack

Standing attack (D38-final): fresh `git clone -b feature/go-support`, `sherpa init .` under `/usr/bin/time -l` → 177 blobs / 810 chunks indexed, embedding 810/810 (100 %), exit 0, peak RSS 4.13 GiB (< 6 GB). The repo's own single-line JSONL transcripts embedded without incident.

Go-flavored attack, four hostile inputs through `chunk_blob` + `extract_project`:
- **Generics** (`type Pair[K comparable, V any]`, `func Map[T any, U any]`, method on `*Pair[K, V]`): chunked byte-exact, no crash; `Pair`/`Map`/`Use` extracted. The generic-receiver method `Key` was NOT extracted (Finding 1).
- **Build tags + cgo** (`//go:build linux && cgo`, `import "C"`, C preamble comment): parsed, chunked byte-exact, `Add` extracted, no crash.
- **Syntax errors mid-package**: cAST declined, line-window fallback with the logged warning, byte-exact; extractor still recovered `Fine`/`Oops` best-effort. No crash.
- **1 MB generated .go file** (196k-entry map literal): 596 chunks in 0.06 s, byte-exact reassembly; graph pass 0.05 s. No crash, no blowup.

## Findings

All findings are non-blocking (none violates §2, a phase gate, or a stated Phase A criterion); listed for the record and the PR review:

1. **Generic-receiver methods are invisible to the symbol graph.** `go.scm`'s `method_declaration` receiver pattern matches only `type_identifier` / `pointer_type(type_identifier)`; a receiver like `*Pair[K, V]` (a `generic_type` node) matches nothing, so the method (`Key`) gets no definition node — `get_definition("Key")` misses it and calls to it can't resolve. Degrades silently (no crash, chunking unaffected). D43 does not mention generics. Recommend a follow-up: extend the receiver pattern to `(generic_type (type_identifier))` and document the interim gap.
2. **PROGRESS.md was not updated on the branch** — it still reads "ALL PHASES COMPLETE … In progress: Nothing" with no mention of Phase A / feature/go-support. §3.3 lists PROGRESS.md among merge conditions; since this phase merges via PR (human-gated), flagged rather than failed. One paragraph before merge would satisfy the charter.
3. **`tests/test_router_tokens.py` modified beyond the two enumerated files** — purely additive (+27/−0, two new tests, zero existing lines changed). Substantively compliant with "additive new [tests]"; recorded because the phase instruction technically allowed modifications only to `test_recent_changes.py`/`test_mcp_server.py`.
4. **EVAL_LOG.md Phase A entry overstates nothing but miscounts the suite**: it says "Full suite: 305 passed, 0 failed, 0 skipped", while actual collection is 294 on main, 321 at b6c33a7, 323 at the verified tip — 305 matches no measurable state. The gate-relevant numbers in the same entry (0.974/0.869 etc.) reproduced exactly in my clean run. Recommend correcting the count in a follow-up commit (EVAL_LOG is append-only: append a correction, don't edit).

Verdict: **PASS** — every Phase A criterion reproduced from a clean checkout; a fresh session could merge this via PR without hesitation, ideally addressing Findings 2 and 4 in the PR before it lands.

---

**Delta addendum (2026-07-05):** commit 8061bfa was re-verified read-only by the Phase A verifier — scope confirmed limited to the finding-1 fix (go.scm generic-receiver alternations + cast.py type-param trim, pinned by `test_generic_receiver_methods_are_extracted`), the PROGRESS.md update, and an appended-only EVAL_LOG correction (0 deletions); `tests/test_graph_extract_go.py` + `tests/test_chunker_go.py` pass from a clean clone at 8061bfa (15 passed, exit 0) and the original generics attack input now yields the `Key` method — verdict upgraded to PASS-with-delta, finding 3 remains as recorded.
