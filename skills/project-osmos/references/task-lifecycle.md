# Task lifecycle

Use this lifecycle after resolving the Project Osmos task base URL and authorization header. Use one generated task ID for create, initial message, run, polling, retries, and follow-ups.

## Endpoints

Examples assume `BASE` is the task base URL and `TOKEN` is available without printing it.

| Method | Path | Description |
| --- | --- | --- |
| `PUT` | `/{taskId}` | Create or update a task. |
| `GET` | `/{taskId}` | Get task status and run details. |
| `DELETE` | `/{taskId}` | Delete a task. |
| `GET` | `/` | List tasks for this Lakehouse. |
| `POST` | `/{taskId}/messages` | Add conversation messages. |
| `GET` | `/{taskId}/messages` | Get conversation and assistant progress. |
| `POST` | `/{taskId}/run` | Start the task. |
| `POST` | `/{taskId}/cancel` | Cancel a running task. |

## Create task

Generate a UUID for `taskId`. Include the full user instruction and the rendered operational constraints.

```json
{
  "displayName": "Short task description",
  "instruction": "Full user instruction plus operational constraints"
}
```

If a later run request returns an instruction-related error, recreate or update the task with the full instruction before running.

## Add user message

Use a unique message ID and UTC timestamp. For writes, send string role values:

| Role | Meaning |
| --- | --- |
| `"User"` | User-authored message. |
| `"Assistant"` | Assistant-authored message. |

Use flat string metadata for author attribution:

```json
{
  "messages": [
    {
      "id": "message-uuid",
      "role": "User",
      "content": "Full user instruction goes here",
      "timestamp": "2026-01-01T00:00:00Z",
      "metadata": {
        "author_name": "user@example.com",
        "author_source": "copilot-cli"
      }
    }
  ]
}
```

Do not put nested objects inside `metadata`; flat string values are safest across service versions.

## Start run

Call `POST /{taskId}/run` with an explicit empty body when required by the front door.

## Monitor progress

Poll both endpoints; task status alone does not show agent progress:

1. `GET /{taskId}/messages`
2. `GET /{taskId}`

Track unseen assistant messages by `id` and normalize inbound role/status values defensively. Relay meaningful new assistant content while the task runs.

## Status values

Expected task status values are `Created`, `Running`, `Cancelling`, `Cancelled`, `Completed`, and `Failed`.

Expected message role values are `User`, `Assistant`, and `System`.

Even with string enums, derive terminal states from run details and completion fields rather than status alone. A retry can temporarily move a task back into a running state.

## Startup behavior

- Spark session acquisition can take several minutes.
- Running status with no session ID can be valid while the backend acquires a session.
- Do not assume the run is dead just because no session ID appears immediately.

## Continue a task

For follow-up instructions:

1. Add another user message with role `User`.
2. Call `POST /{taskId}/run` again if the task is not already running.
3. Keep the same task ID so conversation history and backend checkpointing are preserved.
