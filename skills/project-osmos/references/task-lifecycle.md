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

## Create task

Generate a UUID for `taskId`. Include the full user instruction; the agent reads it during run.

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

For follow-up instructions:

1. Add another user message with `role: "User"`.
2. Call `POST /run` again if the task is not already running.
3. Keep the same task ID so conversation history and backend checkpointing are preserved.

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
