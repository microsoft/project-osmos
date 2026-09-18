# Task state and audit

The headless recovery poller maintains durable local context for CLI resume,
diagnostics, and accepted-intake provenance. Fabric task details are the browser
view; no local HTML or JavaScript state file is generated.

## On-disk layout

Keep task records under the user's current working directory, not a temporary
directory or the user's home:

```text
./.dataprojects/<task-id>/
  state.json
  messages.ndjson
  poller.pid
  poller.log
  terminal.json
  terminal.<UTC-ts>.<time_ns>.<pid>.json
```

`state.json` is the local resume snapshot, not authority for current service
status. `messages.ndjson` is an append-only audit trail including tool/system
messages. `poller.pid` is removed on clean exit; `poller.log` records diagnostics.
The poller archives an old `terminal.json` before a new process starts.

For an existing task, reuse its directory without reseeding or truncating its
history. Legacy local display files may be left untouched, but do not open,
link to, regenerate, or depend on them. Preserve existing JSON state and audit
records during upgrades.

## Initial-seed checklist

Before starting the poller, write `state.json` atomically using a temporary file
in the same directory and rename. Use snake_case; map API `workspaceId` and
`artifactId` to `workspace_id` and `lakehouse_id`.

| Top-level field | Required content |
| --- | --- |
| `schema_version` | Integer `1`; preserves the existing resume format. |
| `task` | Identity, routing context, and initial status described below. |
| `intake` | Accepted contract and decision provenance described below. |
| `spec` | Exact rendered `## Execution plan` block; its SHA-256 must equal `intake.contract_sha256`. |
| `summary` | One agent-authored sentence, at most 180 characters, describing the outcome in human terms. Do not quote the user's instruction verbatim. Preserve on resume unless the outcome changes. |
| `messages` | Empty array at seed time. |
| `artifacts` | `{ "notebook": null, "table": null }`. |

### Task identity and status

| Field within `task` | Source |
| --- | --- |
| `id` | Generated task UUID, matching the directory name. |
| `workspace_id`, `lakehouse_id` | Validated context. The Lakehouse is the Spark session default, not an implied source/destination boundary. |
| `workspace_name`, `lakehouse_name` | Service-resolved `displayName`; never blank, `(unknown)`, or a substituted GUID. |
| `capacity_id` | Resolved workspace capacity ID. |
| `task_page_url` | Canonical link from [Task page URL construction](url-parsing.md#task-page-url-construction). Seed as `null` before launch, then save the returned URL before spawning the poller. |
| `created_at` | ISO timestamp of task creation. |
| `started_at` | ISO timestamp when running, or `null`. |
| `last_polled_at` | ISO timestamp of the seed; subsequently advanced only after successful observation. |
| `status` | Normalized task status, usually `Created` or `Running` at seed. |
| `status_detail` | Short phase/error text, or `null`. |
| `operation_id`, `session_id` | Service run identifiers when available, otherwise `null`. |

Keep the original non-secret routing context from the authentication helper
available for resume. Do not infer an API route from a browser link.


### Accepted intake

| Field within `intake` | Required content |
| --- | --- |
| `contract_version` | `2` |
| `contract_sha256` | SHA-256 of the exact `spec` string. |
| `accepted_at` | ISO timestamp when intake reconciliation passed. |
| `project_type` | Exploration, Transformative ingest, Additive, Mutative, Schema migration, or Unclear. |
| `classification_confidence` | `high`, `medium`, or `low`. |
| `answers` | One entry per rendered or accepted question: `id`, `question`, `answer`, `executable_meaning`, `recommended_answer`, `selection_source`, `why`, `scope`, and `parameters`. |
| `user_outcome` | Complete verbatim user instruction and any additional guidance. |
| `handoff_mode` | `inline` or `onelake_reference`. |
| `instruction_path` | Uploaded `Files/...` path for a reference handoff; otherwise `null`. |

Question IDs and labels follow [Operational intake](intake-questionnaire.md).
`selection_source` is `explicit_user_requirement`, `discovered_fact`,
`task_type_fallback`, or `user_override`. Preserve reasons, scoped targets, key
columns, source globs, mutation limits, and other dependent parameters here
without bloating the dispatched execution plan.

For inline handoffs, send the verbatim user outcome followed by `spec` in both
task creation and the initial message. For OneLake-reference handoffs, keep the
exact handoff in the uploaded file and use the same bootstrap reference for
both requests.

### Messages and artifacts

The poller normalizes user/assistant messages into `messages` entries with
`id`, `seq`, `ts`, `role`, and `text`, plus `author` metadata when available.
Repeated text can carry `repeats`, `last_seen_ts`, and `collapsed_ids` so resume
does not double-count it. Tool/system messages remain audit-only in
`messages.ndjson`; all roles are de-duplicated there by message ID across
restarts.

**Only report artifacts that actually exist.** `artifacts.notebook` stays
`null` until workspace publication succeeds and its path is verifiable; then
record `workspace_path` and optional `url`. `artifacts.table` stays `null`
until the Lakehouse write succeeds and is verifiable; then record
`lakehouse_path` and optional `url`. Planned paths belong in the accepted
outcome, not in the produced-artifact record.

## Poller-owned recovery and terminal state

The poller updates `state.json` after each cycle without discarding intake,
summary, or artifact context. It adds a `recovery` object containing:

- Authentication status (`auth_status`), refresh configuration/count/timestamps,
  last successful observation, and time spent unable to observe because of auth.
- Retry totals/maximum/exhaustion, error signatures, retry timestamps, and the
  no-progress window. These enforce bounded same-task recovery.
- `possible_elicitation_loop`, `elicitation_loop_count`,
  `elicitation_loop_text`, and detection time. Repeated clarification intent
  is not genuine assistant progress.
- Sticky `last_trigger_error`, its timestamp/signature, pending retry signature,
  and message sequence watermark. The cause survives a transient status reset
  and clears only after fresh assistant progress; persisted error text is
  redacted and truncated.

On exit it writes `terminal.json` and mirrors it into `state.terminal`:
status, exact exit reason/code/time, task/workspace/Lakehouse/capacity IDs and
names, operation/session IDs, completion time, retry totals/exhaustion,
refresh count, and the last error/retry-trigger details. Reasons distinguish
service completion from `max_runtime`, `max_auto_retries`,
`no_progress_window`, `retry_signature_repeat`, `no_token_at_startup`,
`run_post_failed_<HTTP>`, `crash`, and `signal`.

Read the terminal marker first on re-engage, then the snapshot. A stopped
poller does not mean the remote task stopped. Fetch live status before writes
or claims about current service state. Follow [Task lifecycle](task-lifecycle.md)
for continuation and [Recovery poller](dashboard-poller.md) for restart.

## Sensitive data

State and audit files must contain no auth tokens, bearer headers, or tenant
credentials. Token files are separate and private. Task links and identifiers,
user instructions, and conversation history are sensitive operational data:
keep them local and redact before sharing. The launch helper's local structured
`telemetry` output includes workspace/task IDs for correlation, but performs no
upload. Never include instructions or conversation history in telemetry.
