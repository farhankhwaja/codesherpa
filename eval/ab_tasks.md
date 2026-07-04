# A/B Benchmark Tasks — miniproject fixture

Repository: `tests/fixtures/miniproject` (build with
`python tests/fixtures/build_miniproject.py` — see conftest.py).

Same rules as `eval/ab_tasks_sizly.md`: each task is stated purely in terms
of observable behavior or intent — no file paths or identifiers in the task
text. Ground truth lives in HTML comments and is shown ONLY to the grader,
never to the agent under test. Frozen before arm A ran (harness honesty
rule).

Scoring: full credit = primary file(s) AND the specific function/symbol;
partial = right file, wrong/no symbol; zero = wrong module.

---

## Debugging tasks (5)

### M-D1
Symptom: When the outbound call that pings an external endpoint hits a
momentary network blip, the ping is lost for good — the operation gives up on
the first hiccup for some kinds of failures that ought to be retried.
Task: locate the retry decision and explain what governs which failures are
retried.

<!--
GROUND TRUTH:
- pyserver/http_client.py — HttpClient.retry_request(): retries HttpTimeout /
  URLError up to self.attempts with exponential backoff (RETRYABLE_STATUS for
  HTTP codes); non-retryable statuses raise immediately.
- (context: pyserver/services/notifications.py send_task_notification is the caller)
Scoring: http_client.py + retry_request.
-->

### M-D2
Symptom: A member types the correct secret phrase but the check that compares
it with what we saved sometimes disagrees; we need to review how the phrase is
transformed and compared on both the write and the read path.
Task: locate both halves of that logic.

<!--
GROUND TRUTH:
- pyserver/auth.py — hash_password() (salted sha256, iterations) and
  verify_password() (recompute + compare).
Scoring: auth.py + hash_password AND verify_password.
-->

### M-D3
Symptom: After a person's details are updated, the old details keep being
served for up to half a minute; there is a small remember-for-a-while layer in
front of the lookup that nobody remembers the rules of.
Task: find that layer, its expiry rule, and where lookups go through it.

<!--
GROUND TRUTH:
- pyserver/cache.py — MemoCache (ttl_seconds, get/put expiry via clock).
- pyserver/routes/users.py — _user_cache = MemoCache(ttl_seconds=30.0) used in get_user().
Scoring: cache.py + MemoCache; bonus for routes/users.py wiring.
-->

### M-D4
Symptom: Creating an entry whose heading exceeds the allowed length blows up
with an unhandled error instead of the clean complaint the API promises.
Task: locate where headings are checked and where that check is (or should
be) applied on the create path.

<!--
GROUND TRUTH:
- pyserver/validators.py — validate_title() (length/emptiness rules, ValidationError).
- pyserver/routes/tasks.py — create_task() calls validate_title.
Scoring: validators.py + validate_title; bonus for routes/tasks.py create_task.
-->

### M-D5
Symptom: The web client re-attempts a failed call even when the server said
the request itself was malformed — wasting attempts on responses that can
never succeed on retry.
Task: locate where the client decides which failures are worth another try.

<!--
GROUND TRUTH:
- webclient/src/http.ts — RETRYABLE status set + fetchWithRetry() decision
  (HttpError.status membership).
Scoring: http.ts + RETRYABLE / fetchWithRetry.
-->

## Feature-location tasks (5)

### M-F1
Request: Show one more piece of information on each row of the item list in
the web UI, sourced from a field the server already returns. Where does the
row rendering live and where is the row's data shape declared?

<!--
GROUND TRUTH:
- webclient/src/components/TaskItem.tsx — TaskItem / TaskItemProps (row rendering).
- webclient/src/types.ts — Task interface (data shape).
Scoring: TaskItem.tsx + types.ts.
-->

### M-F2
Request: Add another subcommand to the server's command-line tool. Where are
the existing subcommands declared and dispatched?

<!--
GROUND TRUTH:
- pyserver/cli.py — main() argparse subparsers + dispatch.
Scoring: cli.py + main.
-->

### M-F3
Request: Change how "how long ago" timestamps read in the web client (e.g.
"3h ago" → "3 hours ago") everywhere at once. Where is that string produced?

<!--
GROUND TRUTH:
- webclient/src/utils/dates.ts — formatRelative().
Scoring: dates.ts + formatRelative. (pyserver/utils/time.py humanize_delta is
the SERVER-side analogue — naming only that one is the wrong layer.)
-->

### M-F4
Request: The maintenance script that dumps items to a spreadsheet-friendly
file needs one more column. Where is a row assembled, and where is the column
order decided?

<!--
GROUND TRUTH:
- webclient/scripts/export_tasks.js — formatTaskRow() and TaskExporter
  (header/order + row assembly).
Scoring: export_tasks.js + formatTaskRow/TaskExporter.
-->

### M-F5
Request: Add a new tunable setting that operators can override via an
environment variable. Where are settings declared, read, and defaulted?

<!--
GROUND TRUTH:
- pyserver/config.py — Settings dataclass + load_config() (env overrides,
  defaults).
Scoring: config.py + Settings/load_config.
-->
