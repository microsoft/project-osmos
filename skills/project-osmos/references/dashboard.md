# Status dashboard

Operational reference read by the `project-osmos` skill at runtime. Defines the on-disk layout, the `window.__STATE` schema, and the open/refresh contract for the local HTML status dashboard. The dashboard is a per-task, browser-loadable, read-only view for observability while a long-running Project Osmos task is in flight; it cannot start, cancel, or modify a task.

## On-disk layout

For each task the skill maintains a directory in the user's working directory:

```text
./.dataprojects/<task-id>/
├── dashboard.html
├── state.js
├── state.json
├── messages.ndjson
├── poller.pid
├── poller.log
├── terminal.json
└── terminal.<UTC-ts>.<time_ns>.<pid>.json
```

The skill must use the user's current working directory, not a temp directory and not the user's home. This keeps each task dashboard co-located with task context and easy to delete. The repository `.gitignore` excludes `.dataprojects/`.

If the directory for a given task ID already exists, reuse it and overwrite `state.js` / `state.json`; append to `messages.ndjson`.

## `window.__STATE` schema

`state.js` is a single statement assigning to a global:

```js
window.__STATE = {
  schema_version: 1,
  task: {
    id: "uuid",
    workspace_id: "guid",
    workspace_name: "string",
    lakehouse_id: "guid",
    lakehouse_name: "string",
    created_at: "iso8601",
    started_at: "iso8601 | null",
    last_polled_at: "iso8601",
    status: "Created | Running | Cancelling | Completed | Failed | Cancelled | Canceled",
    status_detail: "string | null",
    operation_id: "guid | null",
    session_id: "guid | null",
    capacity_id: "guid | null"
  },
  intake: {
    project_type: "Exploration | Transformative ingest | Additive | Mutative | Schema migration | Unclear",
    classification_confidence: "high | medium | low",
    answers: [],
    user_outcome: "verbatim user instruction"
  },
  spec: "rendered operational constraints block",
  summary: "one plain-English sentence describing the task",
  messages: [
    {
      ts: "iso8601",
      role: "assistant | user",
      text: "string",
      seq: 0,
      repeats: 1,
      last_seen_ts: "iso8601",
      collapsed_ids: ["message-id"]
    }
  ],
  artifacts: {
    notebook: { workspace_path: "string", url: "string | null" } | null,
    table: { lakehouse_path: "string", url: "string | null" } | null
  },
  recovery: {
    auth_status: "ok | broken",
    auto_retries_total: 0,
    auto_retries_max: 10,
    auto_retries_exhausted: false,
    last_retry_at: "iso8601 | null",
    last_progress_at: "iso8601 | null",
    last_successful_poll_at: "iso8601 | null",
    no_progress_window_seconds: 7200,
    token_refreshed_at: "iso8601 | null",
    token_refresh_count: 0,
    token_refresh_configured: true,
    last_trigger_error: "string | null",
    last_trigger_error_at: "iso8601 | null"
  },
  terminal: {
    status: "Completed | Failed | Cancelled | Canceled | Unknown",
    reason: "terminal_status | max_runtime | max_auto_retries | no_progress_window | retry_signature_repeat | no_token_at_startup | run_post_failed_<HTTP> | crash | signal | unknown",
    exit_code: 0,
    task_id: "uuid",
    workspace_id: "guid | null",
    workspace_name: "string | null",
    lakehouse_id: "guid | null",
    lakehouse_name: "string | null",
    capacity_id: "guid | null",
    session_id: "guid | null",
    operation_id: "guid | null",
    token_refresh_count: 0,
    last_error_message: "string | null",
    completed_at: "iso8601 | null",
    exited_at: "iso8601"
  }
};
```

## Write rules

- Writes to `state.js` and `state.json` must be atomic: write a temp file in the same directory, then rename.
- Do not persist tokens, authorization headers, tenant credentials, or certificate payloads.
- `artifacts.*` values stay `null` until the task confirms that the artifact was produced and the path is verifiable.
- The dashboard renders message text using safe text APIs, not HTML injection.

## Initial seed checklist

At run start, seed:

- `schema_version`
- complete `task` object with known IDs, names, status, and null run IDs
- intake answers and rendered operational constraints
- one-sentence summary
- empty `messages`
- `artifacts: { notebook: null, table: null }`

After seeding, copy `assets/dashboard.html` into the task directory, write `state.js` and `state.json`, then spawn the poller.
