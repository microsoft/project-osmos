# Status dashboard

Operational reference read by the `project-osmos`
skill at runtime. Defines the on-disk layout, the `window.__STATE`
schema, and the open / refresh contract for the local HTML status
dashboard. The dashboard is a per-task, browser-loadable, read-only
view for observability while a long-running Project Osmos task is in
flight; it cannot start, cancel, or modify a task.

## On-disk layout

For each task the skill maintains a directory in the user's working
directory:

```text
./.dataprojects/<task-id>/
├── dashboard.html               # written once, never overwritten
├── state.js                     # overwritten after every poll cycle
├── state.json                   # mirror of __STATE for grep / curl
├── messages.ndjson              # append-only audit trail of orchestrator messages
├── poller.pid                   # PID of the active poller; removed on clean exit
├── poller.log                   # poller stdout/stderr tail
├── terminal.json                # exit marker (status + reason); read by the agent on re-engage
└── terminal.<UTC-ts>.<time_ns>.<pid>.json  # archived prior exit markers
```

Use a `terminal.*.json` glob when looking for archived exit markers; the
archive suffix includes nanoseconds and the poller PID to avoid same-second
respawn collisions.

The skill must use the user's current working directory, not a temp
directory and not the user's home. This keeps each task dashboard
co-located with task context and easy to delete or version-control.

If `./.dataprojects/` does not exist, the skill creates it. If the
directory for a given task ID already exists (re-run), the skill reuses
it and overwrites `state.js` / `state.json`; `messages.ndjson` is
appended, never truncated.

## `window.__STATE` schema

`state.js` is a single statement assigning to a global:

```js
window.__STATE = {
  schema_version: 1,
  task: {
    id: "uuid",
    environment: "prod" | "msit",


    workspace_id: "guid",
    workspace_name: "string",
    lakehouse_id: "guid",     // Spark session default lakehouse — NOT necessarily source or destination
    lakehouse_name: "string", // Spark session default lakehouse — NOT necessarily source or destination
    created_at: "iso8601",
    started_at: "iso8601 | null",
    last_polled_at: "iso8601",
    status: "Created" | "Running" | "Cancelling" | "Completed" | "Failed" | "Cancelled" | "Canceled",
    status_detail: "string | null",
    operation_id: "guid | null",
    session_id: "guid | null",
    capacity_id: "guid | null"
  },
  intake: {
    project_type: "Exploration" | "Transformative ingest" | "Additive" | "Mutative" | "Schema migration" | "Unclear",
    classification_confidence: "high" | "medium" | "low",
    answers: [
      {
        id: "Question 1" | "Question 2" | "Question 3" | "Question 4" | "Question 5" | "Question 6" | "Question 7" | "Question 8" | "Question 1a" | "Question 1b" | ...,
        question: "string (the What this means subtitle)",
        answer: "string (the option label, e.g. clone-and-promote)",
        recommended: true | false,
        scope: "string | null"
      }
    ],
    user_outcome: "string (verbatim user instruction)"
  },
  spec: "string (the rendered ## Operational constraints block, verbatim)",
  summary: "string  // REQUIRED. One plain-English sentence ≤180 chars describing what the task does. Author from the user instruction; do not quote verbatim. See the Initial-seed checklist for examples.",
  messages: [
    {
      ts: "iso8601",
      role: "assistant" | "user",  // tool & system are dropped from state.messages — kept only in messages.ndjson
      text: "string",
      seq: 0,
      // Optional. Set when the skill collapses runs of consecutive identical
      // (role + normalized-text) messages from the orchestrator. The skill
      // increments this on the first instance and drops the duplicates.
      // Default 1 if absent. The dashboard renders a "× N" badge when > 1.
      repeats: 1,
      // Optional. ISO timestamp of the most recent occurrence of the
      // collapsed run. Used to display the freshest "last seen at" while
      // keeping the original `ts` of the first occurrence.
      last_seen_ts: "iso8601",
      // Optional implementation detail used by the poller to remember duplicate
      // message IDs collapsed into this visible entry across poll cycles.
      collapsed_ids: ["message-id"]
    }
  ],
  artifacts: {
    notebook: { workspace_path: "string", url: "string | null" } | null,
    table:    { lakehouse_path: "string", url: "string | null" } | null
  },

  // Written by scripts/dashboard-poller.py. Absent before the first poll.
  // The dashboard uses this to render the auto-retry pill, the
  // auth-broken banner, and the "↻ Auto-retry in progress" notice.
  recovery: {
    auth_status: "ok" | "broken",
    auto_retries_total: 0,
    auto_retries_max: 10,
    auto_retries_exhausted: false,
    last_retry_at: "iso8601 | null",
    last_retried_signature: "sha256-prefix | null",
    last_progress_at: "iso8601 | null",
    last_successful_poll_at: "iso8601 | null",
    no_progress_window_seconds: 7200,
    last_auth_error_at: "iso8601 | null",
    auth_broken_started_at: "iso8601 | null",
    auth_blind_seconds_accumulated: 0.0,
    token_refreshed_at: "iso8601 | null",
    token_refresh_count: 0,
    token_refresh_configured: true,

    // ----- mid-run-error visibility (sticky across the wipe) -----
    // When the daemon decides to auto-retry the documented Spark
    // statement transient, it wipes task.completed_at, task.status_detail,
    // and sets task.status="Running" so the dashboard stops showing
    // terminal. These retry-trigger fields preserve the error text + a seq
    // watermark so the dashboard can render an amber strip explaining
    // WHY the auto-retry pill is incrementing. Cleared by the poller on
    // the first fresh assistant message past last_retry_message_seq, or
    // carried into terminal.last_retry_trigger_error on exit.
    //
    // last_trigger_error is redacted+truncated (≤500 chars) before
    // persistence so credential-shaped substrings and storage/file paths
    // don't leak into state.js. The dashboard renders via textContent —
    // never innerHTML.
    last_trigger_error: "string | null",
    last_trigger_error_at: "iso8601 | null",
    last_trigger_error_signature: "sha256-prefix | null",
    pending_retry_signature: "sha256-prefix | null",
    last_retry_message_seq: "number | null"
  },

  // Mirrored from terminal.json by the poller's finally block. Browsers
  // cannot fetch sibling JSON over file://, so the dashboard reads exit
  // reason from here. Absent until the poller exits.
  terminal: {
    status: "Created" | "Running" | "Cancelling" | "Completed" | "Failed" | "Cancelled" | "Canceled" | "Unknown",
    reason: "terminal_status" | "max_runtime" | "max_auto_retries" | "no_progress_window" | "retry_signature_repeat" | "no_token_at_startup" | "run_post_failed_<HTTP>" | "crash" | "signal" | "unknown",
    exit_code: 0,
    task_id: "uuid",
    environment: "prod | msit | null",


    workspace_id: "guid | null",
    workspace_name: "string | null",
    lakehouse_id: "guid | null",
    lakehouse_name: "string | null",
    capacity_id: "guid | null",
    session_id: "guid | null",
    auto_retries_total: 0,
    auto_retries_exhausted: false,
    token_refresh_count: 0,
    last_error_message: "string | null",
    last_retry_trigger_error: "string | null",     // last sticky retry trigger (may equal last_error_message)
    last_retry_trigger_error_at: "iso8601 | null",
    operation_id: "guid | null",
    completed_at: "iso8601 | null",
    exited_at: "iso8601"
  }
};
```

### `terminal.json` (sibling file)

The poller writes a standalone `terminal.json` next to `state.js` on
exit. The agent reads this file on re-engage to report why the poller
stopped instead of treating silence as failure. The dashboard reads the
same payload from `state.terminal` (above) because `file://` does not
allow `fetch`. Schema is identical to `state.terminal`.

When the poller starts and finds a prior `terminal.json` in the
directory, it renames it to `terminal.<UTC-ts>.<time_ns>.<pid>.json` so a
resumed poller does not inherit a ghost exit decision. Use a
`terminal.*.json` glob when searching archived exit markers.

> **Artifacts contract — strict.** Each `artifacts.*` slot is **`null`
> until the orchestrator confirms the artifact has been produced** —
> meaning the workspace publish or lakehouse write succeeded and the
> path is verifiable. Do **not** populate the slot with a planned path
> at run start; the planned name belongs in `intake.user_outcome`,
> not in `artifacts`. Putting a planned path in `artifacts` causes the
> dashboard to lie to the user about what already exists.

## What the skill writes when

| Lifecycle event | File | Action |
|---|---|---|
| Run started | `dashboard.html` | Write once from `assets/dashboard.html` |
| Run started | `state.js`, `state.json` | Initial write per the *Initial-seed checklist* below — `schema_version`, `task.*`, `intake.*`, `spec`, agent-authored one-sentence `summary`, empty `messages`, `artifacts: { notebook: null, table: null }` |
| Run started | (browser) | Open `dashboard.html` with platform-appropriate command |
| Each poll cycle | `state.js`, `state.json` | Overwrite with merged snapshot |
| Each poll cycle | `messages.ndjson` | Append any new messages discovered this cycle |
| Poller exit (terminal status, `max_runtime`, `max_auto_retries`, `no_progress_window`, `retry_signature_repeat`, `no_token_at_startup`, `run_post_failed_<HTTP>`, `crash`, `signal`) | `terminal.json`, `state.js`, `state.json` | Write a final terminal payload with exact `terminal.reason`, mirror it into `state.terminal`, and preserve the latest task/artifact snapshot |

Writes to `state.js` and `state.json` must be atomic: write to a
temp file in the same directory, then rename, so the browser never
reads a half-written state.

### Initial-seed checklist (read before writing the first state file)

The seed write at run start **must** include every field below, at the
exact path shown:

**Top-level**
- `schema_version: 1` (integer literal `1` — not a string, not omitted).
  The dashboard checks this and shows a red mismatch banner if it's
  missing or any other value.

**`task` (object)** — every key is required at seed time, even if its
value is `null`:
- `task.id` — the generated UUID for the task (matches
  `./.dataprojects/<task-id>/`).
- `task.environment` — the resolved environment string (`prod`, `msit`).
  Not returned by the task GET
  API; the skill is the only source.


- `task.workspace_id` — from URL parse.
- `task.workspace_name` — fetched with `GET /v1/workspaces/{workspaceId}`,
  field `displayName`. Never blank, never `(unknown)`, never the GUID.
- `task.lakehouse_id` — from URL parse.
- `task.lakehouse_name` — fetched with `GET
  /v1/workspaces/{workspaceId}/lakehouses/{lakehouseId}`, field
  `displayName`. Never blank, never `(unknown)`, never the GUID.
- `task.created_at` — ISO 8601, the moment the skill called `PUT
  /tasks/{taskId}`.
- `task.started_at` — ISO 8601 if the task is already `Running`,
  otherwise `null`.
- `task.last_polled_at` — ISO 8601 of the seed write itself; the
  poller will advance it on every cycle.
- `task.status` — usually `"Created"` or `"Running"` at seed time.
- `task.status_detail` — short phase string (e.g. `"Spark session
  acquiring"`) or `null`.

**`intake` (object)** — required at seed time:
- `intake.project_type` — the classified task type
  (`"Exploration" | "Transformative ingest" | "Additive" | "Mutative" |
  "Schema migration" | "Unclear"`).
- `intake.classification_confidence` — `"high"`, `"medium"`, or
  `"low"`.
- `intake.answers` — an array of
  `{ id, question, answer, recommended, scope }` objects, one per
  question that was rendered (or auto-accepted from the recommendations
  card). `id` is the canonical question key (`"Question 1"`,
  `"Question 1a"`, …) per the schema example above.
- `intake.user_outcome` — the user's verbatim instruction string (task instructions plus any additional guidance from the "Anything else I should know?" prompt, when the user provided extra context).

**`spec` (string)** — the rendered `## Operational constraints` block,
verbatim. Same string that was appended to the task instruction sent
to the orchestrator.

**`summary` (string, required)** — **one single plain-English sentence**
describing what this task does, authored by the agent from the user's
instruction and shown under the task ID in the dashboard header. This
is the canonical task-summary field; the dashboard does **not** derive
one from `intake.user_outcome`. If `summary` is missing, the dashboard
falls back to `"<task type> task"`.

Rules for writing `summary`:
- One complete sentence, ≤180 chars. No markdown, no bullets, no line breaks.
- Start with the verb describing the work ("Ingest", "Clone", "Transform",
  "Migrate", "Validate"). Mention the source(s) and the destination
  in human terms (lakehouse names, folder names, table names — not GUIDs).
- Do **not** quote the user's instruction verbatim. Compose a clean
  summary from it. Example user instruction "There's a folder called
  Invoice with xlsx files, ingest them into the Invoice table…" should
  become `summary: "Ingest Invoice folder xlsx files into the Invoice
  table in sales_lakehouse."`.
- On resume (when re-seeding a recovered state), preserve whatever
  `summary` was previously written. Do not regenerate it unless the user
  has materially changed the instruction.

**`messages` (array)** — `[]` at seed time.

**`artifacts` (object)** — `{ notebook: null, table: null }` at seed
time. Each slot stays `null` until the orchestrator confirms the
artifact has been produced (workspace publish or lakehouse write
verifiable). Do **not** seed planned paths — those belong in
`intake.user_outcome`, not in `artifacts`.

**Case convention:** snake_case throughout. The backend API returns
`workspaceId`/`artifactId` in camelCase — the skill must transform
these into snake_case (`workspace_id`/`lakehouse_id`) before writing.
Do not pass camelCase keys through.

`schema_version` lets the HTML refuse to render incompatible state,
which becomes important once we ship dashboard updates that change
field names. As a defense in depth, `scripts/dashboard-poller.py`
`write_state` defensively sets `state.setdefault("schema_version", 1)`
on every write, so a missing-version seed self-heals on the next
poll cycle. The same defense does **not** apply to the rest of the
shape — a seed that puts fields at the wrong nesting level will
result in empty dashboard panels until the agent corrects the file.

## Open contract

After the initial write, the skill opens `dashboard.html` in the user's
default browser:

| Platform | Command |
|---|---|
| macOS | `open <path>` |
| Linux | `xdg-open <path>` |
| Windows | `start "" <path>` |

If the open command fails (return code non-zero, command not found),
the skill prints the absolute path so the user can click it manually
and continues. A failed open must never block the run.

The skill must also print the dashboard URL in chat so users who closed
the tab or are on a remote machine can reach it.

## Refresh contract

The dashboard auto-reloads itself every 10 seconds while the poller is active.
Refresh is gated by `state.terminal`, not raw `task.status`, because task status
can transiently flip during auto-recovery. When `state.terminal.reason` is
present, the page renders the stopped banner and switches to a slow reload path
so an already-open tab can observe a respawned poller clearing `state.terminal`.
The user can pause auto-refresh manually via a header toggle.

Auto-refresh is a full page reload, not a partial update, so refreshed
`state.js` always matches the rendered page.

## Sensitive data

`state.js` and `state.json` must contain **no auth tokens, no MWC
tokens, no bearer headers, and no tenant credentials**. The skill holds
those in process memory only. The dashboard files are written with
default user permissions and are readable by anyone with shell access
to the user's machine — treat them as audit logs, not secrets.

## Out of scope for this reference

- Cross-task index (one HTML listing all `./.dataprojects/*/`).
- Server-side polling (we use a static file + `<script>` load).
- Any browser-initiated mutation (start, cancel, retry).
- Streaming via SSE / WebSockets.
- Theme switcher.
