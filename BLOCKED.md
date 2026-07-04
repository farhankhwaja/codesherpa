# Blocked

Two Phase 3 items need input that this worktree cannot supply. Everything
else in Phase 3 is implemented, tested (105 passing), and eval-gated — see
PROGRESS.md and EVAL_LOG.md.

## B1 — §13 "hybrid strictly beats vector-only on recall@5" is saturated at 1.00

With the benchmark-winning embedder (nomic-embed-text-v1.5) BOTH hybrid+rerank
and the vector-only baseline score recall@5 = 1.00 on the 25-query gold set
(symbol-aware relevance, which is already the *stricter* definition — see
DECISIONS D7; under file-level relevance vector-only also saturates). A
strictly-greater comparison against a baseline at metric ceiling is
structurally impossible; no change to breadcrumbs or query preprocessing (the
remedies §10 prescribes) can alter that, because they improve hybrid, not the
saturated baseline.

Honest current standing: hybrid+rerank ≥ vector-only on recall@5 (tie at
1.00), strictly better on MRR (0.873 vs 0.867), and strictly better than
bm25-only on recall@5 (1.00 > 0.96). Thresholds have NOT been edited.

Proposed resolution (needs human sign-off or the graph-mcp worktree, which
owns `eval/`): extend `eval/gold_queries.jsonl` with ~10 harder queries —
paraphrases with zero lexical overlap, cross-file behavioral questions,
distractor-heavy queries — so the ceiling lifts and the comparison becomes
meaningful. The eval harness (tests/support/evallib.py) needs no changes.

## B2 — Final Phase 3 criterion "rebase on main, integrate real store, merge"

Blocked on Phases 1–2: `main` is still at the Phase 0 tip (no `store/` or
`chunker/` implementation exists on any branch). Per §8 the retrieval worktree
built against the frozen contracts with a test-only in-memory store; per §3.3
merge order is core-index → graph-mcp → retrieval. A core-index session must
land Phases 1–2 on main before this branch can integrate and merge.
