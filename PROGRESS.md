# Progress

## Current phase & worktree
Phase 5 (Hardening + Full Benchmarks) — COMPLETE on branch `phase-5`,
awaiting Verifier + §3.3 merge. Then: project rename repograph→sherpa
(human instruction, see below), then Phase 6 (ship) on main.

## Done (one line each, with commit hash)
- Phases 0–4 + Phase 3 retrieval — merged on main through 35cf67a; Phase 4
  human smoke transcripts 24eb65a; A/B task lists committed (ebf9660 sizly,
  fixture list this branch)
- D30: server startup never syncs/embeds/downloads; init/sync own the
  embedding pass (retrieve/warm.py) with progress + --no-embed; warming
  status from MCP tools; local_files_only warm starts; `repograph search`
  CLI — 00a0dce
- D31 router regex stays ASCII (documented); D32 q28 text-weighting attempt
  REJECTED with numbers — ac6e588
- External validation: flask (616 chunks, 231.5 s cold init, 13 MB index)
  + sizly (216 chunks, 73.7 s, 5.9 MB); 5 sensible queries each;
  transcripts verification/phase5/ (sizly redacted to paths) — f7b4edf
- D33 embedder rematch on real repos: nomic stays default (hybrid wins both
  repos; honest note: its isolated dense channel is weak on real repos);
  D34 expansion delta flask/sizly: recall Δ 0.000 both, kept ON; golden
  replay on flask 30 commits PASS; CI workflow (venv ACTIVE) — b2f0d3a
- A/B benchmark executed + recorded (D35): §13 ≥50 % token target MISSED
  (fixture −69.8 %, sizly +2.2 %); solve rate B 21/21 > A 19/21; fewer tool
  calls/file reads; BLOCKED.md B3 filed — b507945
- GOLDEN_DEEP=1 soak re-run: PASS (this workstation, this branch)

## In progress
Phase 5 close-out: full suite from clean state → Verifier → §3.3 merge.

## Blocked / open questions
- BLOCKED.md B3: A/B raw-token target missed (recorded honestly, phase
  proceeded per the human's "record whatever the numbers are" amendment).
  Human decides: accept reframed value prop vs pursue token-diet levers.

## Notes for the next session
- HUMAN INSTRUCTION (pending, do before Phase 6): rename repograph→sherpa.
  PyPI name `codesherpa`, package/imports/CLI/MCP-server `sherpa`, index dir
  `.sherpa/`; docs/tests/PROGRESS/DECISIONS updated; suite green from clean
  checkout; record in DECISIONS (incl. contracts/ import-line touch under
  explicit human instruction).
- venv: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python
  .venv/bin/python`; tests: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m
  pytest -q` (~300 tests incl. two real-model eval gates; models cached at
  ~/.cache/repograph/).
- Production wiring: `build_retriever(repo)` OPENS the existing index only
  (IndexNotBuiltError if missing); eval wiring `build_eval_retriever` still
  syncs+embeds. Embedding pass: `repograph.retrieve.warm.embed_index`
  (embed-tag invalidation wipes vectors on model/text-version change).
- External harnesses: eval/golden_replay.py <repo>; eval/external/
  bench_external.py <repo> <gold.jsonl>; eval/external/ab_runner.py (see
  verification/ab/ab-results.md for the protocol as executed).
- Known limitations for the README: q28-class semantic misses (D32), CPU
  reranker fallback bge TODO(upgrade) (D26), expansion MRR dip on flask
  (D34), A/B raw-token miss (B3/D35).
- GPG signing requires unsandboxed git commits. Never commit sizly file
  contents — paths/scores only.
