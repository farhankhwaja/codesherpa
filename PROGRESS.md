# Progress

## Current phase & worktree
Phase 3 (Embeddings + Retrieval) — COMPLETE on `worktree-retrieval`, fully
integrated with the real store/chunker/graph (Phases 1–2 and 4 are on main).
Official eval gate PASSES (`eval/run_eval.py --mode all`: hybrid 0.971/0.877,
strictly beats bm25 0.771 and vector 0.829; exit 0). Verifier **PASS**
(`verification/phase-3-report.md`; one FAIL round fixed per D29 — deps
declaration + expired serve probe). Merged to main per §3.3 (retrieval
merged last; order satisfied). Next: Phase 5 (hardening + benchmarks) on
main, single session.

## Done (one line each, with commit hash)
- Phases 0–2 + golden hardening + Phase 4 (graph, MCP, eval harness,
  hardened 35-query gold set) — all on main, dc77f33..717e927
- Phase 3 pipeline (RRF, router, packer, embed cache, reranker,
  HybridRetriever + structural lookups) — first 5 commits of this branch
- Real-store integration; memstore + test symbol populator retired (real
  sync now provides symbols/edges) — this branch
- Golden projection extended with embeddings (D14 exception) + non-vacuous
  golden-embeddings test (embed-per-sync incremental == rebuild) — this branch
- Rerank robustness vs hardened set: channel-union CE pool, query-focused
  passages, CE+vector weighted rank blend w=4 (D27); official + internal
  gates green; p95 178 ms — this branch
- Embedder benchmark on real chunks: nomic wins among runnable §6 candidates
  (jina still transformers≥5-incompatible; MiniLM parity noted) — D28
- `build_eval_retriever` (D17 factory) + production `build_retriever` for
  `python -m repograph.mcp_server` — this branch
- Expansion delta in the production pipeline: 0.000, non-decreasing ✓ —
  EVAL_LOG

## In progress
Nothing in retrieval. All six §3.3 boxes checked at merge time (clean-
checkout suite 273/273 by the verifier, golden green, eval thresholds met +
logged, verifier PASS committed, contracts untouched, docs updated).

## Blocked / open questions
None for Phase 3 (BLOCKED.md removed: B1 resolved by hardened gold set +
D27 pipeline work; B2 by Phases 1–2/4 merging).

**Awaiting human (Phase 4 manual-smoke checkbox — do NOT mark done until a
human runs it):**
- [ ] Manual smoke: connect Claude Code to this repo's index, run 3 real
  queries, paste transcripts into `verification/phase4-smoke/`.
  After Phase 3 merges the canonical wiring is:
  `repograph init` then
  `claude mcp add repograph -- "$PWD/.venv/bin/python" -m repograph.mcp_server "$PWD"`
  Suggested queries: `search_code("how does sync decide which blobs are new")`,
  `get_callers("sync_graph")`, `get_recent_changes("HEAD~5")`.

## Notes for the next session
- venv: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python
  .venv/bin/python`; tests: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m
  pytest -q` (273 tests, ~8 min incl. two real-model eval gates; models
  cached at ~/.cache/repograph/, first run downloads ~750 MB).
- Official gate: `python eval/run_eval.py --repo <repo> --mode all` resolves
  `repograph.retrieve:build_eval_retriever` (D17). Production wiring:
  `repograph.retrieve.build_retriever(repo)` -> (HybridRetriever, store).
- Non-obvious retrieval defaults (repograph/retrieve/config.py): rerank
  depth 20 + 700-char query-focused passages (latency gate, D26/D27),
  CE+vector blend weight 4 (D27), nomic needs trust_remote_code + einops
  (D25/D28 — einops is a runtime dep).
- Known limitation: q28 (nl_hard, MemoCache) missed by every channel —
  Phase 5 candidate (e.g. docstring-weighted embedding text).
- MiniLM reached fixture parity with nomic (D28) — re-benchmark embedders on
  real external repos in Phase 5; `embed_model` is config.
- jina benchmarking needs a throwaway venv (`transformers<5`, D25); never
  pin transformers in the product.
- Router token regex is ASCII-only (verifier informational) — non-ASCII
  identifiers fall to the dense path gracefully; widen `_TOKEN_RE` if needed.
- GOLDEN_DEEP=1 soak: one PASS logged (Phase 4); re-record before Phase 5
  merge. GPG signing requires unsandboxed git commits.
