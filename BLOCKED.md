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

Open questions for the human:
1. Accept the reframed value proposition (higher solve rate, fewer tool
   calls/file reads, cost-parity) or hold the release on raw-token
   reduction?
2. If raw-token reduction stays the goal, the two obvious levers are
   (a) smaller default search_code budget / compact-first responses with
   expand-on-demand nudges in tool descriptions, and (b) fewer, richer
   turns (batching). Neither was attempted post-measurement (honesty rule:
   no tuning-then-rerunning inside the same benchmark).
