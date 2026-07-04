# Progress

## Current phase & worktree
ALL PHASES COMPLETE — Phase 6 merged to main with final whole-repo Verifier
PASS (verification/phase-6-report.md; FAIL round on one README number
preserved alongside). Project shipped as: PyPI dist + package `codesherpa`,
user-facing command/MCP/index `sherpa` (D37). CLAUDE.md still says
"repograph" — same project.

## Done (one line each, with commit hash)
- Phase 5 merged (verifier PASS 284/284; A/B v1 target miss filed B3) — 3d44a72
- Rename repograph→sherpa/codesherpa (D37; clean-checkout green) — 47e8d26
- README (real EVAL_LOG numbers + honest limitations), LICENSE (MIT),
  CONTRIBUTING, install-flow verification — 8efce06 + this branch
- D38/D38-final: embedding memory blowup found dogfooding (single-line JSONL
  → mega-chunks → 3k-token batches → 10–15 GB RSS); fixed with fallback
  byte cap + ENCODER_MAX_TOKENS=1024 clamp; failing-first regression tests
  incl. real-model RSS bound; clean-clone init proof 535/535 @ 4.06 GB peak;
  legacy-.repograph warning; accidental 7.5 MB index binaries untracked —
  143c12c et al.
- D39 (human's B3 resolution): compact-first search_code (1500-token
  default, signature+expand_id rows, include_code opt-in) — with MCP tests
- A/B v2 rerun on the same 21 frozen tasks (EVAL_LOG Phase 6 entry; v1
  untouched): fixture raw-token gap −69.8 %→−16.0 %, sizly cost −52.7 %,
  reads −55/−61 %, solve B 20/21 ≥ A 19/21; raw ≥50 % target STILL missed —
  recorded verbatim, B3 updated

## In progress
Nothing. Post-ship candidates live in the README roadmap and TODO(upgrade)
markers.

## Blocked / open questions
None. B3 resolved by the human: SHIP with the measured v2 profile (D40);
the ≥50 % raw-token target stays recorded as missed and moves to the
roadmap as a large-repo re-measurement. BLOCKED.md deleted per charter.

## Notes for the next session
- Names: `pip install codesherpa` → command `sherpa` → `import codesherpa`;
  index `.sherpa/`, ignore file `.sherpaignore`, models `~/.cache/sherpa/`.
- venv: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]" --python
  .venv/bin/python`; tests `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m
  pytest -q` (~292 tests; real-model gates use the cache).
- Memory safety invariants (D38-final): fallback chunks ≤ 16 KiB bytes;
  encoder texts ≤ 8192 chars AND model max_seq_length clamped to 1024
  tokens; hook syncs never download models; verifier standing attack =
  clean-clone init under 6 GB RSS.
- MCP: search_code is compact-first (D39) — bodies via expand(); budget
  default 1500; include_code=true restores v1 behavior.
- A/B harnesses: eval/external/ab_runner.py; raw sizly streams live only in
  the session scratchpad (never commit sizly content); fixture streams
  committed under verification/ab/fixture*/.
- GPG signing requires unsandboxed git commits.
