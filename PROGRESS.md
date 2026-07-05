# Progress

## Current phase & worktree
SHIPPED. All phases complete and merged to main: Phases 0–6 (final
whole-repo verifier PASS, verification/phase-6-report.md) + PR #1
(Go support D43, proto D44, name-repetition fixes D45, verifier PASS
verification/phase-A-fix-report.md; merged 2026-07-05, CI green).
Project naming: PyPI dist + package `codesherpa`, user-facing
command/MCP/index `sherpa` (D37); CLAUDE.md updated to match.
Open (roadmap, not blocking): TODO(upgrade) — revalidate the large-regime
blend weight + router ambiguity threshold on a public large repo
(grafana/grafana protocol in D45: tuning + held-out gold split); PyPI
publish; A/B raw-token target re-measure on a large repo.

## Done (one line each, with commit hash)
- Phase 5 merged (verifier PASS 284/284; A/B v1 target miss filed B3) — 3d44a72
- Rename repograph→sherpa/codesherpa (D37; clean-checkout green) — 47e8d26
- README (real EVAL_LOG numbers + honest limitations), LICENSE (MIT at ship; relicensed Apache-2.0 + NOTICE + DCO policy, sole-author relicense verified — 50/50 commits Farhan),
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
Phase A close-out: PR to main with the §3.3 checklist (suite 323/323 from
clean checkout, golden + GOLDEN_DEEP green, extended gate PASS 0.974/0.869,
verifier PASS incl. 4.13 GB memory-attack), then Phase B.
Go support summary: cAST chunking with (ReceiverType) breadcrumbs, go.scm
symbol graph with evidence-authoritative receiver-typed call resolution
(incl. generics), aliased package imports, router code-context morphology
(D43); fixture v3 append-only Go package; gold set 39.

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
