# Task lifecycle

Use this lifecycle after resolving the base task URL and auth header. Writes use string role values; reads must defensively normalize numeric/stringified-numeric values seen in deployed routes.

Examples assume `BASE` is the task base URL and `MWC_TOKEN` is available to the shell. Public Fabric routes use `mwctoken`.


```bash
export BASE="https://{sparkcore-workload-host}/webapi/capacities/{capacityId}/workloads/SparkCore/SparkCoreService/direct/v1/workspaces/{workspaceId}/artifacts/{lakehouseId}/aichat"
```

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `PUT` | `/{taskId}` | Create or update a task |
| `GET` | `/{taskId}` | Get task status and run details |
| `DELETE` | `/{taskId}` | Delete a task |
| `GET` | `/` | List tasks for this artifact |
| `POST` | `/{taskId}/messages` | Add conversation messages |
| `GET` | `/{taskId}/messages` | Get the conversation and assistant progress |
| `POST` | `/{taskId}/run` | Start the AI agent |
| `POST` | `/{taskId}/cancel` | Cancel a running task |

## Cancel and delete safety gates

Do not treat cancel and delete as synonyms. Use these confirmation gates before calling either endpoint.

### Delete a task

`DELETE /{taskId}` is unrecoverable. Before deleting, warn the user:

```text
Deleting this Osmos task is unrecoverable. This removes the task and its conversation from the service. Do you absolutely want to delete it?

To continue, enter the exact task ID: <task-id>
```

Proceed only if the user re-enters the exact task ID. If the entered value differs in any way, do not call `DELETE`; report that deletion was not confirmed.

### Cancel the current run

`POST /{taskId}/cancel` cancels only the current run. The task is not permanently lost, and the user can come back later and continue the same task with new instructions. Before canceling, ask for yes/no confirmation:

```text
Canceling this Osmos task stops the current run only. The task and its history remain available, and you can continue it later with new instructions.

Are you sure you want to cancel the current run? Reply yes or no.
```

Proceed only on an explicit yes. Do not require task ID re-entry for cancel, because the action is recoverable.

## Create task

Generate a UUID for `taskId`. The service rejects `instruction` values over
10,000 characters. Follow the handoff measurement and
[oversized instruction fallback](oversized-instructions.md) before calling
this endpoint. The `instruction` in the create request and initial user message
must be identical.

```json
{
  "displayName": "Short task description",
  "instruction": "Full user instruction"
}
```

```bash
TASK_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

curl -s -X PUT \
  "$BASE/$TASK_ID" \
  -H "Authorization: mwctoken $MWC_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "displayName": "Task description",
    "instruction": "Full user instruction goes here"
  }'
```

If `POST /run` later returns 400 with an instruction-related error, this `PUT` omitted `instruction`.

## Add user message

Use a unique message ID and UTC timestamp. For writes, send string role values:

| Role | Meaning |
| --- | --- |
| `"User"` | User-authored message |
| `"Assistant"` | Assistant-authored message |

```bash
MSG_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

curl -s -X POST \
  "$BASE/$TASK_ID/messages" \
  -H "Authorization: mwctoken $MWC_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{
    \"messages\": [{
      \"id\": \"$MSG_ID\",
      \"role\": \"User\",
      \"content\": \"Full user instruction goes here\",
      \"timestamp\": \"$NOW\",
      \"metadata\": {}
    }]
  }"
```

Observed success is `204 No Content`; do not expect JSON. Add multiple messages before running only with unique `id` values.

### `metadata` schema constraint

SparkCore-direct `POST /messages` rejects **any nested object inside `metadata`** with misleading `HTTP 400 {"message":"Request body is required."}`. The body is valid JSON; deserialization fails because `metadata` is declared roughly as `Dict[str, str]`, and the global exception handler emits generic empty-body wording.

Accepted shapes today (`204`):
- `metadata: {}`
- `metadata` field omitted entirely
- `metadata: { "author_name": "user@contoso.com", "author_source": "copilot-cli" }` (flat string values)

Rejected shape today (`400`):
- `metadata: { "author": { "name": "user@contoso.com", "source": "copilot-cli" } }` (nested object)

`scripts/post-user-message.py` emits flat keys so author attribution survives round-trip. The poller reassembles `entry.author = { name, source }` for the dashboard renderer regardless of server-returned shape, so both work if the service later accepts nested metadata.

## Start run

```bash
curl -s -X POST \
  "$BASE/$TASK_ID/run" \
  -H "Authorization: mwctoken $MWC_TOKEN" \
  -H 'Content-Length: 0'
```

Some front-door paths return `411 Length Required` without an explicit empty body; `Content-Length: 0` avoids that.

## Monitor progress

Poll both endpoints; task status alone does not show agent progress:

```bash
# 1. Conversation (assistant progress)
curl -s "$BASE/$TASK_ID/messages" \
  -H "Authorization: mwctoken $MWC_TOKEN"

# 2. Task status and run details
curl -s "$BASE/$TASK_ID" \
  -H "Authorization: mwctoken $MWC_TOKEN"
```

Track unseen assistant messages by `id` and normalize inbound `role` values before filtering. Accept `"Assistant"`, `1`, and stringified numeric `"1"` as assistant progress because deployed rings have emitted enum strings and numeric forms. Relay meaningful new assistant content while the task runs.

### Status values

Expected `task.status` string values are `Created`, `Running`, `Cancelling`, `Cancelled`, `Completed`, and `Failed`.

Expected message `role` string values are `User`, `Assistant`, and `System`.

For outbound writes, use the string values above. For inbound reads, keep defensive compatibility: some deployed routes have returned numeric or stringified-numeric status/role values even though the canonical task API values are strings. The poller normalizes both forms so wire-shape drift does not break the dashboard.


Even with string enums, derive terminal states from `runDetails.completedAt` and `runDetails.errorMessage` rather than `task.status` alone. The poller transiently flips `task.status` back to `Running` while auto-retrying the documented Spark statement transient (clearing `completedAt` and `status_detail`), so use `completedAt + errorMessage` to decide whether a run is truly done.

### Startup behavior

- Spark session acquisition can take several minutes.
- Running status with a null `runDetails.sessionId` can be valid while the backend acquires a session.
- Do not assume the run is dead just because no session ID appears immediately.
- Once `runDetails.sessionId` is set and the task later fails with `Run failed while executing statements on the Spark session. Please retry.`, session acquisition succeeded and statement execution failed. See `troubleshooting.md` for the retry recipe.

### Repetitive progress is expected

The orchestrator runs many experiments: it tries multiple approaches and revisits discovery to compare results and converge on the best one, so a run legitimately takes time. Repeated or similar-looking assistant messages are normal exploration, not a stuck loop. Do not assume the run is looping, and do not cancel or re-run the task on that basis. Keep polling and relay a one-line summary of where the run is.

### Polling pattern for LLM harnesses

An LLM inside a harness should not block synchronously between polls. Use a background loop that:

1. Sleeps for the requested interval (defaulting to `runDetails.pollingIntervalSeconds`, typically `5`).
2. Fetches `GET /{taskId}/messages`.
3. Diffs against previously seen assistant message IDs.
4. Prints any new assistant messages so they are relayed to the user.
5. Fetches `GET /{taskId}` to detect terminal state.
6. Exits when the task is no longer running or `runDetails.errorMessage` is set.

`scripts/poll-data-project-task.py` implements this pattern with `--mwc-token-env`, `--auth-scheme`, and `--poll-interval` flags. Prefer it over ad-hoc shell loops.

## Continue a task

For a user-authored follow-up, continue the same task ID so service-side conversation history and backend checkpoints remain available. Never create a replacement task or rerun intake. This is especially important for elicitation: by the time the user answers a question, the run that asked it will often already be terminal.

Only continue an approval request when the task's reconciled `Operational
constraints` listed that gate explicitly. A safety policy such as `fail if
target already populated` is not a gate and cannot be overridden by posting
"proceed." If Osmos asks a generic question such as whether the original task
contains a gate even though the contract says `Approval gates: none`, post at
most one correction quoting that field. If the same intent appears again, rely
on the dashboard's elicitation-loop signal and surface a handoff-contract
failure instead of repeatedly posting answers or starting more runs.

Before continuing, read `./.dataprojects/<task-id>/terminal.json` first when present, then `state.json`. Re-resolve the existing route and acquire a fresh token as needed; a token file or refresh command left by an exited poller may be stale. Then use the helper as one ordered operation:

```bash
python3 skills/project-osmos/scripts/post-user-message.py \
  --base-url "$TASKS_BASE" \
  --task-id "$TASK_ID" \
  --token-file "$TOKEN_FILE" \
  --message "$FOLLOW_UP" \
  --auth-scheme "mwctoken" \
  --output json
```

The helper performs these steps:

1. Fetch `GET /{taskId}` and normalize the live status using the shared task-status contract.
2. Post the full user-authored message first with `role: "User"` and flat author metadata.
3. Always fetch live status again after the message post succeeds. This post-message read is the decision point and closes both races: the eliciting run may finish while the user answers, or another actor may already have started a run.
4. If the post-message task is `Running` and has neither `runDetails.completedAt` nor `runDetails.errorMessage`, do not call `/run`.
5. For `Completed`, `Failed`, `Cancelled`, or any other not-running state, call `POST /{taskId}/run` exactly once on the same task ID.

The message must succeed before the run request is attempted. If status lookup or message posting fails, no run is started. If the run request returns HTTP 409, fetch live status once: accept the conflict only when the task is now `Running`, and never send a second run request. For any other run failure, or a 409 without a live run, report that the message was posted but continuation did not start. The helper's JSON includes the before/after status decision, `run_start_attempted`, `run_started`, `run_active`, `run_start_outcome`, and `poller_restart_required`.

After `poller_restart_required: true`, respawn `dashboard-poller.py` with fresh authentication and the existing `./.dataprojects/<task-id>/` directory. Do not reseed or overwrite the directory. Poller startup archives the prior `terminal.json`, preserves `state.json` and message de-duplication state, and captures the new operation, assistant messages, and terminal result. Verify the new poller process and surface authentication or startup failures.


The deployed status map is `0=Created`, `1=Running`, `2=Cancelling`, `3=Cancelled`, `4=Completed`, and `5=Failed`. Both numeric values and stringified numerics use this map. A nominal `Running` status with a non-empty `completedAt` or `errorMessage` is treated as no longer running.

## Response shapes

Observed deployed task shape:

```json
{
  "id": "task-uuid",
  "artifactId": "lakehouse-uuid",
  "workspaceId": "workspace-uuid",
  "displayName": "Analyze sales data",
  "instruction": "Full instruction text",
  "status": "Running",
  "createdAt": "ISO-8601",
  "modifiedAt": "ISO-8601",
  "runDetails": {
    "operationId": "operation-uuid",
    "sessionId": "session-uuid",
    "startedAt": "ISO-8601",
    "completedAt": null,
    "errorMessage": null,
    "retryAfterSeconds": 5,
    "pollingIntervalSeconds": 5
  }
}
```

`runDetails.operationId` is present on public deployed routes. If a route omits `operationId`, expect it to be missing or `null`.


Observed deployed conversation shape:

```json
{
  "messages": [
    {
      "id": "msg-uuid",
      "role": "User",
      "content": "User instruction",
      "timestamp": "ISO-8601",
      "metadata": {}
    },
    {
      "id": "msg-uuid",
      "role": "Assistant",
      "content": "Assistant progress update",
      "timestamp": "ISO-8601",
      "metadata": {}
    }
  ]
}
```
