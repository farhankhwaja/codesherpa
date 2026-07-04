# A/B Token Benchmark — Results (Phase 5)

Protocol: `eval/ab_harness.md`. Tasks frozen before arm A ran:
`eval/ab_tasks.md` (miniproject fixture, 10 tasks) and
`eval/ab_tasks_sizly.md` (sizly, 11 tasks — the primary repo). Agents saw
ONLY the task text (ground-truth HTML comments stripped by
`eval/external/ab_runner.py::parse_tasks`; verified programmatically before
any run). One fresh headless Claude Code session per task per arm
(`claude -p`, model sonnet, max-turns 40, 20-min wall cap); identical
prompts/settings across arms; arm B additionally had the repograph MCP
server attached (`--mcp-config`, tools allowlisted).

Transcripts: fixture (our own code) committed under
`verification/ab/fixture/`. Sizly raw transcripts contain sizly source and
are NOT committed (Phase 5 amendment: paths only) — redacted per-task
metrics in `verification/ab/sizly-metrics.csv`; raw streams retained
locally by the operator.

## Grading

Graded against the frozen ground-truth keys by symbol/path match
(programmatic keyword check over the final answer + manual review; script in
the session log). Judgment call, applied identically in both arms: when the
final message was only "my earlier answer stands" after a verification
subagent returned, the task counts as solved iff the key file+symbol were
stated in a prior in-session answer (occurred twice: fixture M-F5 arm A,
sizly F5 arm B).

| repo | arm A solved | arm B solved |
|---|---|---|
| fixture | 10/10 | 10/10 |
| sizly | 9/11 (D2 timed out at 20 min/107 tool calls; D5 stalled asking for shell permission) | **11/11** |

Solve-rate guardrail (B ≥ A): **PASS** — repograph rescued both arm-A
failures (D2: subdomain brand extraction, solved in B in 355 s with 14
repograph calls; D5: PWA service-worker auth interception, solved in B in
120 s).

## Token / efficiency metrics (mean over SOLVED tasks per arm)

`tokens_total` = input + cache_creation + cache_read + output (the CLI's
cumulative session usage — the harness's "input + output tokens" includes
cache reads, which dominate). `fresh` = the same minus cache reads.
`cost` = the CLI's billing-weighted total_cost_usd (cache reads at 0.1×).

### miniproject fixture (10 solved / arm)
| metric | A (no repograph) | B (repograph) | Δ (1 − B/A) |
|---|---|---|---|
| tokens_total | 300,849 | 510,731 | **−69.8 %** (B higher) |
| fresh tokens | 11,135 | 28,868 | −159.3 % |
| cost (USD) | 0.506 | 0.383 | **+24.4 %** |
| tool calls | 28.9 | 14.9 | +48.4 % |
| file reads | 15.1 | 4.7 | +68.9 % |

### sizly (A: 9 solved, B: 11 solved — B's mean includes the two hardest tasks A failed)
| metric | A | B | Δ |
|---|---|---|---|
| tokens_total | 608,948 | 595,789 | +2.2 % |
| fresh tokens | 35,694 | 48,916 | −37.0 % |
| cost (USD) | 0.910 | 0.985 | −8.3 % |
| tool calls | 33.6 | 29.5 | +12.2 % |
| file reads | 14.6 | 8.8 | +39.4 % |

Adoption (arm B): fixture 7/10 tasks used repograph tools; sizly 11/11.
"Fallback" (used grep/Read/Glob after repograph): fixture 5/10, sizly 11/11
— in practice agents interleave repograph (locate) with Read (verify), which
the tool descriptions do not discourage.

## Verdict against the §13 target

**The ≥50 % token-reduction target is NOT met** on the primary metric
(tokens over solved tasks): −69.8 % on the fixture, +2.2 % on sizly.
Recorded as-is; gap filed in BLOCKED.md per §13. No reruns were performed
after seeing results (honesty rule).

What the data does show, honestly summarized:
- **Capability**: B solved 21/21; A solved 19/21. Both A failures were
  navigation failures on the vocabulary-mismatch tasks repograph targets.
- **Interaction economy**: consistently fewer tool calls (−12 %/−48 %) and
  whole-file reads (−39 %/−69 %).
- **Where the tokens went**: repograph responses are token-dense (packed
  code chunks up to the 4 k budget) and headless sessions re-read the
  growing context every turn as cache reads, so per-turn context in B is
  fatter even though B takes fewer turns. On billing-weighted cost the arms
  are within ±25 % (B cheaper on the fixture, pricier on sizly).
- Caveat: single model (sonnet), single run per task/arm, n=21 tasks;
  variance across identical reruns was not measured.
