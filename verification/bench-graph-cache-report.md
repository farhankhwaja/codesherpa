# Verification Report — feat/bench-and-graph-cache

**Verdict: PASS**
Date / commit verified: 2026-07-18 / ab8ac3d (branch
`feat/bench-and-graph-cache`; commits 8566c51, f0db70f, 3b36e64, a7d0d2b,
ab8ac3d over origin/main 5c7fe3d)

Verifier: adversarial QA agent (CLAUDE.md §11), fresh clone + fresh uv
venv (Python 3.12.13), `uv pip install -e ".[dev]"`.

## Criteria / Gates

| # | Gate | Result | Evidence |
|---|---|---|---|
| 1 | Clean install | PASS | install completed; `sherpa` console script functional |
| 2 | Full suite `python -m pytest -q` (venv on PATH) | PASS | exit 0; 363 test dots, zero F/E/s markers — matches claimed 363 passed. The trailing "N passed" summary line was stripped from captured output by the local rtk output filter; exit code + dot count are the evidence |
| 3 | Golden Test | PASS | `pytest tests/test_golden.py -q` exit 0 |
| 4 | Deep Golden `GOLDEN_DEEP=1` | PASS | exit 0 — the critical incremental==rebuild gate for the new cache |
| 5 | Official eval gate `tests/test_eval_gate.py` | PASS | hybrid recall@5 **0.974**, MRR **0.869**, p95 360.5 ms; gate table hybrid+rerank 0.97/0.869/475 ms < 500 ms; beats bm25 (0.744) and vector (0.795); "GATE: PASS". Matches claims. No latency flake observed (475 ms, first run) |

## Cheating hunt

1. `git diff origin/main...HEAD -- codesherpa/contracts/ eval/
   codesherpa/chunker/` — **empty**. Contracts frozen, eval thresholds
   untouched, chunker/ (other branch's territory) untouched. EVAL_LOG.md
   diff is append-only (zero removed lines).
2. Tests touched: exactly three files. (a) `tests/test_cli.py`: probe test
   renamed to `test_unsupported_subcommand_exits_nonzero`, moved from
   `bench` to `definitely-not-a-command`. Assertions NOT weakened: still
   `returncode == 2`, still an explanatory stderr assertion
   (`"invalid choice"`, argparse's correct message for the new probe),
   PLUS a new no-traceback assertion; two new bench tests added.
   DECISIONS.md D49 justifies the move citing the D5/D29 precedent, as
   required. (b) `tests/bench_indexing.py` (script, not a pytest test) is
   now a thin CLI over `codesherpa.bench.bench_synthetic` — single
   implementation, same workload. (c) `tests/test_graph_facts_cache.py`
   new: 10 tests incl. `extract_project_cached == extract_project`,
   zero-parse no-op sync, single-blob reparse, stale-tag wipe with
   corrupted payloads, incremental-vs-rebuild graph echo. Suite grew
   351 → 363, none removed/skipped/xfailed.
3. `grep -rn "mock|Mock|monkeypatch" codesherpa/` and
   `grep -rn "miniproject|fixtures" codesherpa/` — no matches.
4. `codesherpa/bench.py` reviewed line-by-line: every number comes from
   `time.perf_counter()` around real `sync()`/`retriever.search()` calls;
   queries come from `--query-file` or a deterministic SQL sample of
   most-referenced definitions; indexing uses a throwaway tempdir DB,
   never `.sherpa/index.db`. No fabricated values.
5. D47→D48 renumbering note is present in DECISIONS.md above D48 (commit
   messages retain old numbers to preserve GPG signatures). Mapping
   confirmed: cache=D48, bench=D49, Go fix=D50.

## Directed experiments

1. **Cache is a pure accelerator (flask).** Shallow clone of
   pallets/flask; `sherpa init --no-embed` → 224 blobs/616 chunks
   (0.33 s); no-op syncs 0.19 s / 0.11 s. Baseline: 1837 symbols, 5283
   edges, 81 graph_facts rows. Deleted 27/81 graph_facts rows → re-sync
   repopulated to 81; full symbols+edges dumps **byte-identical** to
   baseline. Flipped `meta['graph_facts_tag']` to a bogus value → re-sync
   restored
   `v1|q=cf647d8bc7a6d2f5|tree-sitter=0.26.0,tree-sitter-language-pack=1.12.5`,
   rebuilt the cache, symbols/edges again byte-identical.
2. **`sherpa bench`.** `--indexing` on flask: cold 0.32 s, 107,844 LOC/s,
   1837 symbols/5283 edges — matches the live index's actual counts, so
   measurements are real. `--retrieval --queries 10`: p50 2.9 ms, p95
   8.4 ms, router path labeled with its 200 ms gate. `--synthetic 60`:
   33,664 LOC/s. Failure modes: outside a repo →
   `sherpa bench: not inside a git repository: .` exit 1; repo without
   index → `sherpa bench: no index at ... — run \`sherpa init\`...`
   exit 1. Both one-line, start with "sherpa bench:", no traceback.

## Exploratory attack (Go fix, D50)

1. **Semantic identity vs main:** loaded main's and the branch's
   `languages.py` side by side; 7,123 fuzzed `_go_resolve_import` calls
   over random mixed path sets: **0 mismatches**. Explicit
   shared-directory case (`pkg/util/{alpha,beta,zeta}.go`): both resolve
   to `pkg/util/alpha.go`, the lexicographic minimum.
2. **lru_cache staleness on deletion:** in-process, resolving against
   `{alpha,beta}` then `{beta}` returns alpha then beta (frozenset key
   changes — no stale entry). End-to-end: tiny Go repo, imports edge
   targeted `pkg/util/alpha.go`; after `git rm alpha.go` + commit + sync,
   the edge repointed to `pkg/util/beta.go`; incremental DB vs
   from-scratch rebuild at the same HEAD: active symbols and edges
   **byte-identical**.

## Standing attack (D38-final)

`sherpa init` on a clean clone of this repo under `/usr/bin/time -l`:
exit 0, peak RSS **4.51 GB < 6 GB**, embedding pass reached **876/876
(100%)**, DB confirms 876 active chunks / 876 embeddings.

## Findings

None at FAIL level. Two informational notes:

1. (info) The rtk output filter on this machine strips pytest's final
   summary line from captured logs; verification relied on exit codes
   plus dot counts. Not a defect of the branch.
2. (info) `_go_package_dirs`'s `lru_cache(maxsize=4)` keys purely on the
   path frozenset — correct, since the map is a pure function of the path
   set; CLI syncs are fresh processes, and the long-lived MCP case is
   safe because any active-set change changes the key.

**A fresh session could merge this branch per §3.3 without hesitation.**
