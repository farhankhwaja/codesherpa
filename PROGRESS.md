# Progress

## Current phase & worktree
SHIPPED. All phases complete and merged to main: Phases 0–6 (final
whole-repo verifier PASS, verification/phase-6-report.md) + PR #1
(Go support D43, proto D44, name-repetition fixes D45, verifier PASS
verification/phase-A-fix-report.md; merged 2026-07-05, CI green).
Project naming: PyPI dist + package `codesherpa`, user-facing
command/MCP/index `sherpa` (D37); CLAUDE.md updated to match.
The `graph/index.py` TODO(upgrade) (per-blob extraction facts) is DONE — D47.
Open (roadmap, not blocking): TODO(upgrade) — revalidate the large-regime
blend weight + router ambiguity threshold on a public large repo
(grafana/grafana protocol in D45: tuning + held-out gold split); PyPI
publish; A/B raw-token target re-measure on a large repo.

## Done (one line each, with commit hash)
- fix/partial-ast-salvage: cAST no longer discards a whole file on
  `root.has_error` — clean top-level declarations keep real chunks, only
  error-tainted extents line-window (D47). Measured on grafana pkg/services:
  0 → 842 of 989 clean declarations (85.1%) recovered across 57 of 66 broken
  files; byte-exact partition preserved. Unblocks working-tree indexing.
  D47a (owner decision): root-level ERROR relaxed from wholesale-fallback to
  just-another-tainted-extent — 654 → 842 declarations; byte-exactness
  re-verified on all 57 salvaged files incl. the 2.6 KB straddling ERROR spans.
- feat/bench-and-graph-cache: per-blob graph extraction cache (D47, new
  `graph_facts` table + `graph_facts_tag` invalidation), real `sherpa bench`
  (D48, logic moved to `codesherpa/bench.py`; `tests/bench_indexing.py` is now
  a thin wrapper), and a quadratic Go import-resolution fix found while
  measuring (D49). grafana `pkg/` no-op sync 164.93 s → 7.52 s; suite 351→363
- feature/gain: `sherpa gain` local usage analytics (usage table, dispatch
  wrapper, privacy invariants test-pinned, terminal + self-contained HTML,
  README methodology) — D46, this branch
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
- **OPEN RISK — §13 p95 warm latency fails in the field (not caused by
  fix/partial-ast-salvage; needs its own change).** Fixture: 259 ms quiet /
  502.5 ms under load vs a <500 ms budget. Grafana index (17,495 chunks):
  614 ms on the shipping default, 826/780 ms at w=2/w=4. The gate passes on the
  39-query fixture and fails on a real repo — see DECISIONS D47a for both data
  points and why the chunker branch is ruled out.
- **Branch protection (2026-07-05): `main` requires PRs — direct pushes are
  blocked. ALL work, including doc-only fixes, goes through a branch + PR
  with CI green before merge. No exceptions (the old "doc changes may push
  straight to main" allowance is revoked).**
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
- Graph cache (D47): if you change what `extract._extract_file` collects, BUMP
  `GRAPH_FACTS_VERSION` — the Golden Test compares two runs of the same code
  and structurally CANNOT catch a stale payload written by an older sherpa.
  `.scm` edits and grammar upgrades invalidate automatically via
  `extraction_tag()`; pass-1 logic changes do not.
- Sync perf on large repos is dominated by graph pass 2 (cross-file
  resolution) + writing symbols/edges, not by parsing. Profile
  `_resolve_project` before optimizing anything else; `sherpa bench` on the
  repo gives the cold/no-op split directly.
