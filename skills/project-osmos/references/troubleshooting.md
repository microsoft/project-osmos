# Troubleshooting

| Situation | Handling |
| --- | --- |
| Task status is failed | Read the task run details and report the error with task/run identifiers. |
| Message post returns no body | This can be expected for successful writes; do not require JSON. |
| Run request requires a body | Retry with an explicit empty body. |
| Run request reports the task is already active | Poll status and messages before deciding. If the task is running or acquiring a run, treat it as already in flight. |
| Run request returns an instruction error | The task was created without the full instruction; update the task with the complete instruction before running. |
| Running with no session ID | This can be valid during Spark session acquisition. Continue polling. |
| Workspace has no capacity | Stop and ask the user to assign or provision Fabric capacity before creating or running a task. |
| Authorization fails | Ask the user to refresh Azure CLI sign-in, then reacquire the task authorization token and resume the same task. |

## Retryable Spark statement transient

This error marks a retryable execution transient:

```text
Run failed while executing statements on the Spark session. Please retry.
```

Treat it as a retryable task execution limitation, not automatically as a user-code failure. The poller handles this case without agent involvement by retrying the same task ID with bounded backoff and preserving dashboard state.

## Token expiry during long runs

The poller supports proactive and reactive token refresh when a refresh command is configured. If refresh fails, it marks authorization as broken in state and stops advancing `last_polled_at` so dashboard freshness remains honest.

On re-engage:

1. Read `terminal.json` first when present.
2. If authorization is broken, reacquire a fresh token and respawn the poller for the same task ID.
3. Do not create a new task just because polling stopped; reuse the existing task and dashboard directory.
