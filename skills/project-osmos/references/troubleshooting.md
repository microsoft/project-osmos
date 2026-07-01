# Troubleshooting

| Situation | Handling |
| --- | --- |
| Task status is failed | Read `runDetails.errorMessage` and report it with task/run identifiers. |
| `POST /messages` returns 204 | This is expected for deployed routes; do not parse a body. |
| `POST /messages` returns 500 | OneLake may be inaccessible or the Lakehouse is unreachable. Refresh the MWC token, verify workspace/Lakehouse IDs, and retry. |
| `POST /run` returns 411 | Retry with `Content-Length: 0` or an explicit empty body. |
| `POST /run` returns 409 | Poll status and messages before deciding. If the task is `Running` or acquiring a new run, treat it as already in flight; otherwise report that the task is in a state that cannot be run. |
| `POST /run` returns 400 with instruction error | The task was created without `instruction`; re-`PUT` the task with the full instruction. |
| Running with no session ID | This can be valid during Spark session acquisition. Continue polling. |
| Agent looks stuck in a loop / repeats discovery | Expected: Osmos runs many experiments and revisits steps to converge on the best one, so it takes time and progress can look repetitive. Do not assume it is looping; do not cancel or re-run. Keep polling and relay progress. |
| Workspace has no capacity | Stop and ask the user to assign/provision Fabric capacity before creating or running a task. |
| `generatemwctoken` returns `HTTP 403` with an empty body | The bearer token's tenant does not match the workspace's home tenant. Re-acquire the token with `az account get-access-token --tenant <tenant-id> --resource https://analysis.windows.net/powerbi/api`, and `az login --tenant <tenant-id>` if needed. |
| `generatemwctoken` returns `HTTP 403` with `Tenant not authorized for cluster` | Run `scripts/resolve-auth-and-routing.py` or `scripts/resolve-auth-and-routing.ps1`. The helper reads the routed home cluster from Fabric response headers and retries token exchange there. Do not hand-edit hosts, workload types, token audiences, or capacity SKUs. |


## Retryable Spark statement timeout

This exact error message marks the documented retryable transient:

```text
Run failed while executing statements on the Spark session. Please retry.
```

Treat it as a Spark statement/token timeout limitation for long-running Project Osmos tasks, not a user-code failure. The orchestrator checkpoints `agent_state.json` after each completed search step and re-hydrates that partial state on retry, so re-running the same task resumes from the last persisted step.

### What the daemon does — automatically

`scripts/dashboard-poller.py` handles this case end-to-end without agent involvement:

- Match the normalized error string on `runDetails.errorMessage` (primary) or the latest assistant message appended this poll cycle (fallback).
- Auto-retry each unique error signature (sha256 of `operationId|completedAt|err`) at most once via `POST /{taskId}/run` on the same task ID. Hard cap `--max-auto-retries`; time-based safety net `--no-progress-window-seconds`. If `operationId` is absent, the signature degrades to `sha256("|completedAt|err")` but still dedups correctly within a single run.


- Use a small fixed retry backoff schedule, then a flat tail (`--retry-backoff-seconds`). Run `python3 skills/project-osmos/scripts/dashboard-poller.py --help` for exact defaults to avoid doc/script drift.
- Treat HTTP 409 from `POST /run` as retry success only when the follow-up task poll shows the run is already in flight (`Running` / acquiring). If the task is not runnable, report the 409 as a retry failure. Auth-class errors trigger one token refresh and one re-POST only when `--token-refresh-cmd` is configured; otherwise the poller enters `auth_status: "broken"` and waits for respawn with fresh credentials.
- On giving up, write `terminal.json` with reason `max_auto_retries`, `no_progress_window`, `retry_signature_repeat`, or `run_post_failed_<HTTP>` so the agent can report exactly why on re-engage.

### What the agent does — on re-engage

The agent does **not** manually `POST /run` for this error. If the poller is still running, polling will pick up the next state. If the poller has exited (`./.dataprojects/<task-id>/poller.pid` is gone), read `./.dataprojects/<task-id>/terminal.json` and report the `reason` field verbatim, plus `last_error_message`, `auto_retries_total`, and run identifiers (`task_id`, `operation_id`, `session_id`, `capacity_id`, `workspace_id`, `lakehouse_id`) when present. `session_id` is best-effort because some routes do not return it in `runDetails`.

If the user explicitly asks to keep trying after the daemon exhausted its budget, re-spawn the poller with `python3 skills/project-osmos/scripts/dashboard-poller.py` against the same task ID (per the resume guardrail in `SKILL.md`); the counters reset and another `--max-auto-retries` budget is available. Do **not** create a new task; that discards the checkpointed agent state.

## MWC token expiry mid-run

The MWC token typically expires after ~1.5h. `dashboard-poller.py` auto-refreshes:

- **Proactive**: refresh on a fixed cadence (`--token-refresh-interval`) by running `--token-refresh-cmd` and validating the new token with a cheap `GET /{taskId}` before swapping.
- **Reactive**: when `--token-refresh-cmd` is configured, refresh on any auth-class 4xx (401, 403, or 400 with an auth-related body) and immediately retry the failed call.
- **Auth broken**: if refresh keeps failing, or no refresh command is configured when the token is rejected, enter `auth_status: "broken"` and **stop advancing `last_polled_at`** (so the dashboard's freshness signal stays honest). With `--token-refresh-cmd`, retry refresh on bounded exponential backoff; without one, respawn the poller with a fresh readable initial token/refresh recipe.

Default cadence and backoff values live in `python3 skills/project-osmos/scripts/dashboard-poller.py --help` rather than this doc so changing a default updates one place.

The agent does not need to manage tokens during a normal run. On re-engage, if `state.recovery.auth_status === "broken"`, first check `state.recovery.token_refresh_configured`. If true, ask the user to verify the `--token-refresh-cmd` recipe and re-spawn the poller with a corrected one. If false, there is no refresh recipe to fix; ask for a fresh readable initial token (`--token-file` or `MWC_TOKEN`) and optionally add a refresh command for later expiry. The task itself is unaffected — only the client's view of it is stale.
