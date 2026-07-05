# Phase "gain" Verification Report (`feature/gain` — `sherpa gain` local usage analytics)
Verdict: PASS
Date / commit verified: 2026-07-05 / 910e43d73c7d60b521fa4907b3da44550204ae5c (2 commits atop main 559a00e)

Environment: fresh detached checkout of 910e43d in an isolated worktree; fresh
`uv venv --python 3.12` (cpython 3.12.13) + `uv pip install -e ".[dev]"` — install OK.

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 1 | Clean install from fresh venv | PASS | `uv pip install -e ".[dev]"` exit 0 |
| 2 | Full suite from clean checkout | PASS | 350 tests collected, `python -m pytest -q` exit 0, progress output is dots-only (no F/s/x) — 350 passed, 0 skipped. Two independent runs green |
| 3 | Golden Test | PASS | `pytest tests/test_golden.py -q` exit 0 (1 passed) |
| 4 | GOLDEN_DEEP=1 golden | PASS | `GOLDEN_DEEP=1 pytest tests/test_golden.py tests/test_golden_embeddings.py -q` exit 0 (3 passed) |
| 5 | `usage` table appended to store/schema.sql | PASS | 22-line addition, `CREATE TABLE IF NOT EXISTS usage` + `idx_usage_ts`; columns are hash/counts/sums only. Pre-gain DBs are migrated on store open (verified: dropped `usage`, reopened `SQLiteIndexStore`, table recreated) |
| 6 | Populated by a SINGLE wrapper `_tool` at MCP dispatch, no per-tool logging | PASS | All 7 tools decorated `@_tool` (server.py:126,166,174,183,191,200,219); `gain.record_call` has exactly ONE call site (server.py:108); the only `mcp.tool()` usage is inside the wrapper (line 124) |
| 7 | Recording failure logs warning, NEVER fails the query | PASS | Suite test (monkeypatched raise) green; plus an independent REAL failure: `DROP TABLE usage` behind a live server → search_code isError=False, 2 results, warning "usage recording failed for search_code (query unaffected)" logged |
| 8 | `RetrievalConfig.analytics=True` honored at dispatch | PASS | `analytics: bool = True` on config; gate computed at `create_server` dispatch wrapper; `test_analytics_flag_off_records_nothing` green |
| 9 | `sherpa gain`: totals by tool/path, avg/p95 latency, tokens vs budgets, expand rate | PASS | Live run on attack repo: `queries: 8 (search_code 3 · …)`, `paths: graph 3 · router 2 · n/a 2 · dense 1`, `latency: avg 535 ms · p95 4263 ms`, `tokens served: 1,528 (40% of offered budgets)`, `expand rate: 1 expands / 3 searches (33%)` |
| 10 | Counterfactual carries "estimated" adjacent to the number in EVERY rendering | PASS | Terminal: `estimated context avoided: 0 tokens (estimate — see README methodology)`; HTML card: `<h2>{n}</h2><p><b>estimated</b> context avoided (tokens)</p>` + methodology paragraph. Only two renderers exist (render_terminal, render_html); both test-pinned |
| 11 | `--since` / `--days` filters | PASS | CLI: `--since 2026-07-06` → 0 rows (zero-state, exit 0); `--days 1` → all 8 rows; unit tests cover the 2001-dated exclusion row and label text |
| 12 | Friendly zero-state | PASS | Fresh `sherpa init --no-embed` repo: "no usage recorded yet… claude mcp add…" exit 0; missing index → "run `sherpa init` first" exit 1 |
| 13 | `--html` self-contained single file, default `.sherpa/gain.html`, `--out` override | PASS | Default path written & printed; no `http(s)://` outside HTML comments, no `<script`, no `url(`, no `@import`; 2 hand-rolled inline SVGs; `--out` covered by test_cli_gain_end_to_end |
| 14 | README "Measuring what sherpa saves" + quickstart step | PASS | Section present with exact formula and facts/estimate split; `sherpa gain` added to quickstart |
| 15 | DECISIONS D46 documents the design | PASS | D46 present (privacy invariants, single-wrapper, honest-measurement rationale, rejected expand→search linkage) |

## Privacy attack (required)

Scratch repo with `topsecret_billing/wire_transfer_keys.py` +
`topsecret_billing/ledger.py`, symbols `decrypt_customer_pan`,
`rotate_wire_keys`, `settle_wire`, constant `SECRET_MARKER_XYZZY =
"pan-vault-master-4242"`. `sherpa init --no-embed`, then a REAL in-memory MCP
session (SDK `create_connected_server_and_client_session`, real
`build_retriever` — dense path loaded the real model) issued:
search_code("decrypt_customer_pan wire_transfer_keys SECRET_MARKER_XYZZY"),
a NL search containing "pan-vault-master-4242", get_definition, get_callers,
get_references, index_status, search_code + expand. 8 usage rows written.

- (a) Every row × every column dumped and grepped for all 9 distinctive
  needles (incl. paths `topsecret_billing`, `ledger.py`): **0 hits**.
- (b) Byte-level grep over `sqlite3 .dump usage` (usage table only, 25
  lines): **0 hits** for every needle.
- (c) `usage.query_hash` of row 1 == `sha256("decrypt_customer_pan
  wire_transfer_keys SECRET_MARKER_XYZZY")` hex — exact match; index_status
  row carries sha256("") (`e3b0c442…`), confirming plain sha256 of the
  primary text arg.
- HTML report from the same DB also contains none of the needles.
- Stored columns are exactly: ts, tool, query_hash, path_taken (router/dense/
  graph/NULL), tokens_returned, budget_tokens, latency_ms, results_count,
  files_count, files_spanned_tokens, expanded. No text, no code, no paths.

## Behavioral checks

- (a) Golden projection excludes usage: `GOLDEN_PROJECTION` keys verified
  (active_blobs/files_head/chunks/fts/symbols/edges/embeddings only);
  test_golden.py diff vs main is comment-only (+5 comment lines, raw diff
  inspected); `test_usage_rows_do_not_perturb_golden_projections` green.
- (b) Recording failure: real `DROP TABLE usage` under a live server — query
  succeeded, single warning logged (see criterion 7).
- (c) Zero-usage `sherpa gain` → friendly line, exit 0.
- (d) `gain.html` verified self-contained and "estimated"-labeled (criteria
  10/13); no secrets.
- (e) Single-point dispatch confirmed: `grep record_call server.py` → one
  call site.

## Cheating hunt

1. `git diff main...feature/gain -- tests/`: only tests/test_gain.py added
   (354 lines, 12 tests) and a comment-only change to tests/test_golden.py.
   No test deleted/weakened; no skip/xfail added anywhere in the diff.
2. `git diff main...feature/gain -- codesherpa/contracts/`: empty.
3. `git diff main...feature/gain -- eval/`: empty; EVAL_LOG.md untouched; no
   thresholds changed anywhere (CLAUDE.md not modified on this branch).
4. `grep -rn "mock\|Mock\|monkeypatch" codesherpa/`: none.
5. `grep -rn "miniproject\|fixtures" codesherpa/`: none.
6. Full changed-file list is exactly the 11 files in the feature scope
   (docs + gain.py + cli + server + config + retriever + schema + tests).

No cheating found.

## Exploratory attacks

1. **Emoji/unicode query** (`🐍🔥 décrypt_客户_pan … émoji`): isError=False,
   row recorded, no crash.
2. **5.25 MB query** (`"decrypt_customer_pan " * 250000`): isError=False in
   1.3 s; query_hash == sha256 of the full 5 MB text; no fragment of the
   query stored (dump grep negative).
3. **12 concurrent tool calls racing the usage INSERT** (anyio task group on
   one session): 0 errors, exactly +14 rows for 14 calls, `PRAGMA
   integrity_check` = ok.
4. **`sherpa gain --html --out` into a chmod-555 directory**: raw
   PermissionError traceback (finding 1 below), non-zero exit; DB unharmed.
5. **STANDING ATTACK (D38-final)**: clean `git clone` of this repo @910e43d,
   `sherpa init` under `/usr/bin/time -l`: exit 0, embedding pass reached
   **853/853 (100%)**, maximum resident set size **4,077,797,376 bytes
   (3.80 GiB) < 6 GB**. PASS.

## Findings

1. (Minor, non-blocking) `sherpa gain --html --out <path in unwritable
   directory>` surfaces a raw Python `PermissionError` traceback instead of a
   friendly one-line error like the other CLI failure modes
   (codesherpa/cli.py `_cmd_gain`: `out.write_text(...)` is uncaught). No §10
   or task criterion covers this; cosmetic UX only.
2. (Observation, not a defect) `estimated context avoided` clamps at 0 when
   tokens served exceed the full-file equivalent (e.g. many tools re-serving
   the same two small files, JSON/breadcrumb overhead). This is the honest
   direction of error and the rendering still carries the "estimated" label.
3. (Observation) No EVAL_LOG.md entry for this branch — acceptable: the
   feature has no eval-gated threshold; golden, GOLDEN_DEEP, and the full
   suite were re-verified green, and no existing threshold was touched.

Verdict: **PASS** — a fresh session could merge `feature/gain` per §3.3
without hesitation (findings 1–3 are non-blocking; finding 1 is worth a
follow-up commit but does not gate the merge).
