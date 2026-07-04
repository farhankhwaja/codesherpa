# Blocked / needs human decision

## B3 — §13 A/B token-reduction target (≥50 %) not met (Phase 5)

Measured (EVAL_LOG 2026-07-04, full report verification/ab/ab-results.md):
tokens_total per solved task, arm B (sherpa) vs arm A: fixture −69.8 %
(B uses MORE), sizly +2.2 %. Target was ≥ +50 %. Solve-rate guardrail
passed (B 21/21 vs A 19/21 — B solved both tasks A failed); tool calls and
whole-file reads dropped materially; billing-weighted cost within ±25 %.

Per §13 the threshold cannot be lowered and a miss stops for human input.
Per the Phase 5 execution amendments ("Record whatever the numbers are — no
cherry-picking") the benchmark was recorded honestly and the remaining
phase work continued; the Phase 5 merge and the Phase 6 README report these
actual numbers with the miss stated plainly (no reduction claim is made).

RESOLUTION (human decision, Phase 6): lever (a) was implemented as D39
(compact-first search_code: 1500-token default, signature+expand_id rows)
and the benchmark rerun as A/B v2 on the same 21 frozen tasks (EVAL_LOG
Phase 6 entry; v1 untouched). Outcome: fixture raw-token gap −69.8 % →
−16.0 %, sizly parity with cost −52.7 %, all interaction metrics improved,
solve guardrail holds — but the raw-token ≥50 % reduction target is STILL
not met. Remaining open question for the human: accept shipping with the
measured profile (the README reports it verbatim), or hold the release on
the raw-token number (§13 forbids lowering the threshold).
