# Phase A-fix Verification Report
Verdict: PASS
Date / commit verified: 2026-07-05 / b422865 (`fix/go-symbol-repetition`, 4 commits atop feature/go-support 043ece3)

Clean-room: detached checkout of b422865 in an isolated worktree, fresh
`uv venv --python 3.12` (.verifier-venv), `uv pip install -e ".[dev]"` — install OK,
`sherpa --help` runs.

## Criteria

| # | Criterion (abridged) | Result | Evidence |
|---|---|---|---|
| 1 | Clean install from fresh venv | PASS | `uv pip install -e ".[dev]"` clean; console script `sherpa` on PATH |
| 2 | Full test suite | PASS | `python -m pytest -q`: 338 collected, 338 passed, 0 failed, 0 skipped, exit 0 |
| 3 | Golden Test | PASS | `pytest tests/test_golden.py -q` green |
| 4 | GOLDEN_DEEP=1 soak | PASS | `GOLDEN_DEEP=1 pytest tests/test_golden.py -q` green |
| 5 | Eval gate, 39-query gold set (`run_eval.py --repo tests/fixtures/miniproject --mode all`) | PASS | hybrid recall@5 **0.974** ≥ 0.80; MRR **0.869** ≥ 0.60; p50 169.8 ms, p95 201.5 ms; sole miss q28. bm25-only 0.744/0.611; vector-only 0.795/0.714 — hybrid strictly beats both on recall@5. Harness prints `GATE: PASS`, exit 0. By type: nl 1.00, symbol 1.00, stacktrace 1.00, decoy 1.00, nl_hard 0.89 |
| 6a | Router anti-hijack test-pinned, non-tautological | PASS | Read tests/test_router_ranking.py + retriever.py: synthetic store with 31 `Service` defs + one `reconcileLedger`; asserts rank-1 file == `pkg/billing/ledgersvc/service/batch_run.go`; fan-out cap ≤ `router_token_fanout`; path-boost keeps the same-package `Service` (asserted on file path, not rationale text); boundary test pins exactly-8 (specific) vs 9 (ambiguous) incl. the flag actually flipping; separate regression against the REAL synced fixture asserts the top chunk's code contains `func (a *Archive) Flush`. Assertions match implementation semantics (tier = 1.0 − 0.12·tier, rank step 0.04, floor via sort key `len(defs) > router_ambiguous_defs`) |
| 6b | Blend auto by index size | PASS | `RetrievalConfig.rerank_blend_vector_weight: float \| None = None`; HybridRetriever resolves at construction: `len(store.active_blobs()) <= RetrievalConfig.SMALL_INDEX_ACTIVE_BLOBS (512)` → 4.0 else 1.0; explicit float pins. Test covers small/large/pinned |
| 6c | Embed v2 announce + hook deferral | PASS | `invalidation_pending()` exists in retrieve/warm.py; cli `_embed_pass` prints "embed text format changed (v2): re-embedding N chunks, one time" when non-quiet; hooks pass `defer_invalidation=hook_safe` (hook_safe=args.quiet). Verified END-TO-END on a live index with a faked stale tag: `sherpa sync --quiet` deferred (tag + 5 old vectors untouched, silent); foreground `sherpa sync` announced and re-embedded, tag advanced to `nomic-ai/nomic-embed-text-v1.5\|text=v2` |
| 6d | Proto family isolation | PASS | `test_proto_is_its_own_family_no_cross_language_edges` exists and passes (Go `Quote` never links to proto `Quote`); `_FAMILY["proto"] = "proto"` in graph/extract.py; proto.scm resolves proto→proto imports only |
| 7 | Standing attack (D38-final) | PASS | Clean clone of this repo @ b422865, `/usr/bin/time -l sherpa init`: peak RSS 4,078,436,352 B = **3.80 GiB < 6 GB**; embedding pass **830/830 (100 %)**; 182.3 s real; exit 0 |

## Cheating hunt

1. `git diff 043ece3..b422865 -- tests/`: no tests deleted, skipped, weakened, or xfail'd. Only pre-existing test modified is tests/test_chunker_go.py — assertions updated `(Store)` → `(pkg.Store)` to match the D45c breadcrumb change (behavior change documented in DECISIONS D45c; the plain-function negative assertion was actually *strengthened* to `"Store)" not in`). New files: test_proto_support.py (+135), test_router_ranking.py (+271), test_warm.py (+23). No `skip`/`xfail` anywhere in the new tests.
2. `git diff main...b422865 -- codesherpa/contracts/`: **empty** — frozen contracts untouched.
3. Mock/monkeypatch grep over `codesherpa/`: no hits. Stub encoders live only in tests.
4. Hardcoded fixture-path grep (`miniproject|fixtures`) over `codesherpa/`: no hits.
5. `eval/`: the 4 delta commits touch nothing under eval/; vs main the only change is +4 additive gold queries (q36–q39, from the already-verified Phase A branch). run_eval.py thresholds identical to main; CLAUDE.md §13 untouched.

## Exploratory attack

Scratch git repo containing: `weird.proto` (proto2 syntax, nested message, `oneof`, legacy `group`, `extend`, `extensions 100 to max`, escaped default string, `import public`), `editions.proto` (`edition = "2023"`), and `cache/cache.go` (generic receiver `func (c *Cache[K, V]) Get`). `sherpa init` completed without crashing: weird.proto fell back to line-window chunks (expected — grammar rejects proto2 group) **yet its symbols still extracted correctly** (Outer, Inner, Svc, rpc Do as method, with defines/references edges); editions.proto parsed as cAST (EdMsg extracted). Generic-receiver breadcrumbs are package-qualified: `// cache/cache.go :: (cache.Cache) :: func (c *Cache[K, V]) Get(k K) (V, bool)`. Router edge-case queries — path-fragments-only, empty string, whitespace-only, emoji-only, `batch_run.go:214` — all return gracefully (fall through to dense/BM25), no exceptions.

## Findings

No FAIL-level findings. Non-blocking observations (numbered for the merging session):

1. **EVAL_LOG.md has no entry for this delta.** §3.3 requires eval scores appended before merge; the last entry is the Phase A gate at the previous tip. The delta changes retrieval scoring (router ranking, blend auto, EMBED_TEXT_VERSION 2), so the merging session must append the b422865 gate numbers (this report's row 5: 0.974 / 0.869 / p95 201.5 ms, GATE PASS, suite 338/338) at merge time. Do not merge without ticking this box.
2. **Pre-existing on main (NOT introduced by this branch): `.repograph/index.db` (7.5 MB) + `index.db-shm` + `index.db-wal` are tracked in git** since the rename commit 44fb297, and propagate to every clone (confirmed in the standing-attack clone). Root cause: the `.gitignore` line `.repograph/   # legacy pre-rename index dir, never commit` — a `#` mid-line is a *literal* character in gitignore patterns, so the rule never matches. Committing a live WAL/SHM pair is also an inconsistent DB snapshot. Recommend fixing on main (untrack the three files; put the comment on its own line).
3. Cosmetic: `RetrievalConfig.SMALL_INDEX_ACTIVE_BLOBS` docstring claims "Class attribute, not a per-instance field", but as an annotated dataclass assignment it *is* an init field on instances. Behavior is unaffected (code/tests read it via the class; default 512).
4. Minor: the blend weight is resolved once at `HybridRetriever` construction; a long-lived server whose index grows across the 512-blob boundary keeps the stale regime until restart.
5. Cosmetic: DECISIONS D44/D45 headers still say "uncommitted per no-commit rule / per freeze" — they are now committed at b422865.
6. Honest-limitation note (already disclosed in D45/config): the large-regime blend weight (1.0) and `router_ambiguous_defs=8` were tuned on a single since-retracted private venue; grafana/grafana re-validation with a held-out split is recorded as pending. Acceptable as documented TODO(upgrade), but it should stay on the roadmap.
