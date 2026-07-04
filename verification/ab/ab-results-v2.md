# A/B Token Benchmark v2 — after compact-first search_code (D39)

The human's B3 resolution: ship the token diet (`search_code` defaults to a
1500-token budget and signature+expand_id rows, no code bodies) and rerun
the SAME 21 frozen tasks. Method identical to v1
(`verification/ab/ab-results.md`): same task files, same runner, same model
(sonnet), same grading keys and judgment rules; v1 results untouched.
Fixture v2 transcripts committed under `verification/ab/fixture-v2/`; sizly
redacted metrics in `sizly-metrics-v2.csv` (no sizly content).

## Solve rates (grading notes below)

| repo | arm A v2 | arm B v2 | (v1: A / B) |
|---|---|---|---|
| fixture | 10/10 | 10/10 | 10/10 / 10/10 |
| sizly | 9/11 | 10/11 | 9/11 / 11/11 |

Guardrail B ≥ A: holds (20/21 vs 19/21). Grading notes, applied with v1's
rules: sizly A-D2 stalled asking for shell permission (unsolved — same
failure mode as v1 A-D5); sizly A-F4 named a NONEXISTENT wiring file
(`backend/app.js`; only `index.js` exists) — right middleware, wrong third
element, unsolved; sizly A-F6 stated the full answer in-session with a
"my answer stands" final message (solved, v1 precedent); sizly B-D2 hit the
20-min cap (unsolved). Run-to-run variance is visibly real: v1's B solved
D2 and v1's A failed D5; v2 reversed both.

## Efficiency (mean over SOLVED tasks; Δ = 1 − B/A)

### fixture
| metric | A | B | Δ v2 | Δ v1 |
|---|---|---|---|---|
| tokens_total | 372,012 | 431,544 | **−16.0 %** | −69.8 % |
| fresh tokens | 20,299 | 21,151 | −4.2 % | −159.3 % |
| cost (USD) | 0.660 | 0.558 | +15.5 % | +24.4 % |
| tool calls | 40.0 | 25.3 | +36.7 % | +48.4 % |
| file reads | 20.8 | 9.4 | +54.8 % | +68.9 % |

### sizly
| metric | A | B | Δ v2 | Δ v1 |
|---|---|---|---|---|
| tokens_total | 590,570 | 583,342 | +1.2 % | +2.2 % |
| fresh tokens | 38,982 | 33,846 | **+13.2 %** | −37.0 % |
| cost (USD) | 1.703 | 0.805 | **+52.7 %** | −8.3 % |
| tool calls | 62.0 | 32.1 | +48.2 % | +12.2 % |
| file reads | 30.3 | 11.9 | +60.8 % | +39.4 % |

MCP adoption in B: fixture 8/10 tasks, sizly 10/11.

## Verdict

- The §13 raw-token ≥50 % target is **still not met** (fixture −16.0 %,
  sizly +1.2 %) — reported as-is; BLOCKED B3 updated, threshold untouched.
- Compact-first clearly worked in its own terms: the fixture raw-token
  regression collapsed from −69.8 % to −16.0 %, fresh tokens went from far
  worse to parity-or-better on both repos, and sizly billing cost dropped
  52.7 % (caveat: arm A's v2 mean is inflated by two very heavy sessions —
  A-D1 alone burned 2.4 M tokens; single-run-per-task variance remains the
  biggest limitation of this harness).
- Every interaction-economy metric improved or held: tool calls −37/−48 %,
  whole-file reads −55/−61 %, with equal-or-better solve rates.
No reruns were performed after seeing these results.
