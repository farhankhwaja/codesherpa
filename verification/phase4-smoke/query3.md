Query: Use the repograph tool get_recent_changes with since HEAD~5

Use the repograph tool get_recent_changes with since HEAD~5

  Called repograph

Here's what changed in the last 5 commits (all by Farhan Khwaja, today 2026-07-04) — this is the tail end of Phase 3 landing:

fa23903 — docs: CLAUDE.md — commits must not list Claude as author
Only CLAUDE.md; no symbol changes.

35cf67a — chore: Phase 3 verifier PASS report; PROGRESS to merge-ready
Docs only: PROGRESS.md plus the two verifier reports under verification/.

a5c1d33 — fix: verifier findings — declare sentence-transformers+einops; retire expired serve probe
Dependency declarations in pyproject.toml, plus one test swap in tests/test_cli.py: test_serve_reports_missing_retrieval_pipeline removed, test_serve_refuses_non_repository added.

150a801 — feat: eval gate PASS on hardened set — the big one, 19 files. Highlights:
- New module repograph/retrieve/passages.py with focus_passage and query_terms (query-focused passage extraction for the cross-encoder).
- New repograph/retrieve/evalfactory.py: build_retriever (the official factory), build_eval_retriever, and a SingleChannelRetriever for BM25-only/vector-only baselines.
- Modified rrf_fuse (weighted blend), HybridRetriever._dense_candidates (CE pool union), and RetrievalConfig.
- tests/support/indexer.py gutted — the whole regex-based mock symbol extractor (~15 symbols) removed, with tests/support/realstore.py now building the real index instead.
- New eval-gate tests: recall@5, MRR, and hybrid-strictly-beats-BM25/vector-only.

77f0659 — test: golden projection extended with embeddings
tests/test_golden.py gained _project_embeddings (embeddings now part of GOLDEN_PROJECTION), and a new tests/test_golden_embeddings.py adds the incremental-equals-rebuild and cache-boundedness tests for embeddings.

Net picture: the last five commits are Phase 3's eval-gate hardening, verifier remediation, and PASS sign-off — production retrieval code changed only in 150a801; everything since is tests and docs.

** Worked for 25s **