# A/B Token Benchmark Protocol (executed in Phase 5)

Goal (CLAUDE.md §10 Phase 5, §13): show **≥ 50 % token reduction on solved
tasks with no drop in solve rate** when Claude Code has the sherpa MCP
server vs. plain file tools. Record whatever the real numbers are in
`EVAL_LOG.md` — never cherry-pick.

## Setup

- Two repos: `tests/fixtures/miniproject` (built by
  `tests/fixtures/build_miniproject.py`) and one real mid-size external repo
  (e.g. `pallets/flask`), both indexed with `sherpa init`.
- Two Claude Code configurations, identical model and settings otherwise:
  - **A (control):** no sherpa; agent may use its normal tools
    (grep/glob/read).
  - **B (treatment):** sherpa MCP server attached via
    `claude mcp add sherpa -- python -m codesherpa.mcp_server <repo>`;
    same normal tools still available (we measure *choice* too).
- Fresh session per task per arm (no context reuse). Same task prompt,
  verbatim, in both arms.

## Tasks (10 per repo: 5 debugging, 5 feature-location)

Write the concrete task list before running arm A, freeze it, and commit it
to `eval/ab_tasks.md`. Task templates:

- Debugging: "This stack trace / wrong behavior occurs: <trace>. Find the
  defect and name the function(s) that must change."
- Feature location: "Where would you add <capability>? Name the files and
  functions to modify and why."

Each task has a written *solution key* (files + symbols) decided in advance;
an arm "solves" a task if its final answer names the key file(s)+symbol(s).

## Metrics per task per arm

| Metric | How measured |
|---|---|
| tokens_total | input + output tokens from Claude Code's session usage |
| solved | final answer matches the solution key (graded by a human or a fresh judge session shown only key + answer) |
| tool_calls | count of tool invocations in the transcript |
| file_reads | count of whole-file reads (Read tool) |
| fallback_rate (arm B) | fraction of tasks where the agent fell back to grep/read after trying sherpa tools |

## Reporting

- Primary: mean tokens_total over *solved* tasks, per arm, per repo, and the
  reduction `1 - B/A`. Target ≥ 0.50.
- Guardrail: solve rate B ≥ solve rate A.
- Append the full table + transcript paths to `EVAL_LOG.md`; store
  transcripts under `verification/ab/`.

## Honesty rules

- No editing tasks after arm A has run.
- Failed/unsolved tasks are reported, not dropped from the table (they are
  only excluded from the token mean, per the target's definition).
- If the target is missed, record the actual number and file the gap in
  `BLOCKED.md` per §13 — do not rerun until the number looks better.
