# Spawning the dashboard poller daemon

The skill spawns [`scripts/dashboard-poller.py`](../scripts/dashboard-poller.py) as a detached background process so the LLM conversation does not remain in a polling loop.

## Spawn pattern

After the task is running and the CLI summary table has been printed:

1. Write the initial task authorization token to a user-only temporary file.
2. Remove token-bearing environment variables before spawning the daemon.
3. Start the poller as a detached process.
4. Confirm `poller.pid` exists and tail one log line.

## Required arguments

| Argument | Meaning |
| --- | --- |
| `--base-url` | Project Osmos task base URL. |
| `--task-id` | Project Osmos task ID. |
| `--state-dir` | `./.dataprojects/<task-id>` directory. |
| `--token-file` | File containing the initial authorization token. |
| `--auth-scheme` | Authorization scheme, usually `Bearer`. |
| `--token-refresh-cmd` | Optional command that prints a fresh raw token. |

## Spawn example

```bash
TOKEN_FILE="$(mktemp)"
chmod 600 "$TOKEN_FILE"
printf '%s' "$PROJECT_OSMOS_TOKEN" > "$TOKEN_FILE"
unset PROJECT_OSMOS_TOKEN

nohup env python3 skills/project-osmos/scripts/dashboard-poller.py \
  --base-url "$TASKS_BASE" \
  --task-id "$TASK_ID" \
  --state-dir ".dataprojects/$TASK_ID" \
  --token-file "$TOKEN_FILE" \
  --auth-scheme "Bearer" \
  --interval 60 \
  --fast-interval 15 \
  --max-interval 180 \
  --max-runtime 86400 \
  --token-refresh-cmd "$REFRESH_CMD" \
  --token-refresh-interval 2700 \
  --token-refresh-timeout 60 \
  --max-auto-retries 10 \
  --retry-backoff-seconds "30,60,120" \
  --no-progress-window-seconds 7200 \
  >> ".dataprojects/$TASK_ID/poller.log" 2>&1 &
echo $! > ".dataprojects/$TASK_ID/poller.pid"
```

Use the shell tool's detached mode for the spawn step so the process survives after the shell exits.

## Cadence

- Fast phase: 15 seconds for the first 90 seconds after spawn.
- Base interval: 60 seconds once warm.
- Idle backoff: exponential up to `--max-interval` after consecutive idle polls.
- Snap back: reset to base on any new message or status change.
- Terminal: exit once the task reaches a terminal status and no recovery is in flight.
- Hard cap: `--max-runtime` to avoid runaway daemons.

## Automatic handling

- Token expiry: proactive refresh on `--token-refresh-interval`; reactive refresh on authorization-class failures when `--token-refresh-cmd` is configured.
- Retryable execution transient: bounded retry on the same task ID when the task reports `Run failed while executing statements on the Spark session. Please retry.`
- Exit reason capture: write `terminal.json` once for terminal status, retry exhaustion, no-progress timeout, missing token, run-post failure, crash, signal, or unknown exit.

## What the daemon writes

In `./.dataprojects/<task-id>/`:

- `state.js`
- `state.json`
- `messages.ndjson`
- `poller.log`
- `poller.pid`
- `terminal.json`
- archived `terminal.*.json` files from prior pollers

## Resume

On re-engage, read `terminal.json` first. If it exists, report its `reason` and ask before respawning. If `terminal.json` is absent and the recorded PID is not alive, treat it as an ungraceful stop and respawn against the same task ID and dashboard directory.
