# Spawning the dashboard poller daemon

The skill spawns [`scripts/dashboard-poller.py`](../scripts/dashboard-poller.py) as a detached background process so the LLM agent does not remain in a polling loop. See [SKILL.md → Operating contract](../SKILL.md).

## Spawn pattern

After the task is `Running` and the CLI summary table has been printed (the dashboard + poller steps in `SKILL.md`), follow these sub-steps.

### Required environment variables

Set these from [`auth-and-routing.md`](auth-and-routing.md) and [`environment-routing.md`](environment-routing.md):

| Variable | Source |
| --- | --- |
| `MWC_TOKEN` | fresh initial MWC token |
| `TENANT_ID` | workspace home tenant for the bearer token |
| `GENERATEMWC_URL` | resolved `generatemwctoken` endpoint |
| `CAPACITY_ID` | workspace capacity object ID |
| `WORKSPACE_ID` | Fabric workspace object ID |
| `LAKEHOUSE_ID` | default Spark-session lakehouse object ID |
| `TASKS_BASE` | SparkCore task base URL |
| `TASK_ID` | Project Osmos task ID |

Guard them first and export the values needed by the refresh recipe:

```bash
: "${MWC_TOKEN:?set MWC_TOKEN before spawning the poller}"
: "${TENANT_ID:?set TENANT_ID before composing REFRESH_CMD}"
: "${GENERATEMWC_URL:?set GENERATEMWC_URL before composing REFRESH_CMD}"
: "${CAPACITY_ID:?set CAPACITY_ID before composing REFRESH_CMD}"
: "${WORKSPACE_ID:?set WORKSPACE_ID before composing REFRESH_CMD}"
: "${LAKEHOUSE_ID:?set LAKEHOUSE_ID before composing REFRESH_CMD}"
: "${TASKS_BASE:?set TASKS_BASE before spawning the poller}"
: "${TASK_ID:?set TASK_ID before spawning the poller}"
export TENANT_ID GENERATEMWC_URL CAPACITY_ID WORKSPACE_ID LAKEHOUSE_ID
```

### Step 1 — stash the initial MWC token

Write the initial MWC token to a 0600 file the daemon can read, then remove token-bearing variables before spawning. Tokens never go into `argv` or dashboard state.

```bash
TOKEN_FILE="$(mktemp)"; chmod 600 "$TOKEN_FILE"
printf '%s' "$MWC_TOKEN" > "$TOKEN_FILE"
unset MWC_TOKEN PBI_TOKEN BEARER
```

### Step 2 — compose the token refresh recipe

The daemon invokes this command near the ~1.5h expiry or after any auth-class 4xx. Stdout must be the fresh raw bearer token — no JSON wrapper or surrounding whitespace.

Keep the Power BI bearer token out of `argv` and the environment: do the `az` call and `generatemwctoken` POST inside one Python process, using `urllib` headers held in memory instead of `curl -H "Authorization: Bearer ..."`. The poller supplies `/dev/null` as stdin so detached macOS daemons can spawn Python-based tools such as `az` without inheriting an interactive TTY.

```bash
REFRESH_SCRIPT="$(mktemp)"; chmod 700 "$REFRESH_SCRIPT"
cat > "$REFRESH_SCRIPT" <<'PY'
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

tenant = os.environ["TENANT_ID"]
url = os.environ["GENERATEMWC_URL"]
payload = {
    "capacityObjectId": os.environ["CAPACITY_ID"],
    "workloadType": "SparkCore",
    "workspaceObjectId": os.environ["WORKSPACE_ID"],
    "artifactObjectIds": [os.environ["LAKEHOUSE_ID"]],
}

bearer = subprocess.check_output(
    [
        "az", "account", "get-access-token",
        "--tenant", tenant,
        "--resource", "https://analysis.windows.net/powerbi/api",
        "--query", "accessToken",
        "-o", "tsv",
    ],
    text=True,
).strip()
if not bearer:
    sys.exit("az returned an empty Power BI bearer token")

request = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
except urllib.error.HTTPError as e:
    sys.exit(f"generatemwctoken HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
except urllib.error.URLError as e:
    sys.exit(f"generatemwctoken request failed: {e}")

data = json.loads(body.decode("utf-8"))
token = data.get("Token") or data.get("token") or ""
if not token:
    sys.exit("no token in generatemwctoken response")
sys.stdout.write(token)
PY
REFRESH_CMD="python3 $REFRESH_SCRIPT"
```

### Step 3 — spawn the poller, fully detached

The bash tool **must** use `mode="async"` with `detach: true` for this step. A sync session kills the process group on exit and `nohup` alone does not prevent that.

```bash
nohup env -u MWC_TOKEN -u PBI_TOKEN -u BEARER python3 skills/project-osmos/scripts/dashboard-poller.py \
    --base-url                       "$TASKS_BASE" \
    --task-id                        "$TASK_ID" \
    --state-dir                      ".dataprojects/$TASK_ID" \
    --token-file                     "$TOKEN_FILE" \
    --auth-scheme                    "mwctoken" \
    --interval                       60 \
    --fast-interval                  15 \
    --max-interval                   180 \
    --max-runtime                    86400 \
    --token-refresh-cmd              "$REFRESH_CMD" \
    --token-refresh-interval         2700 \
    --token-refresh-timeout          60 \
    --max-auto-retries               10 \
    --retry-backoff-seconds          "30,60,120" \
    --no-progress-window-seconds     7200 \
    >> ".dataprojects/$TASK_ID/poller.log" 2>&1 &
echo $! > ".dataprojects/$TASK_ID/poller.pid"
```

### Step 4 — confirm the daemon started

Use `ps -p` to verify liveness. Do not use `kill -0`. Tail the log regardless so startup errors surface even if the process already exited.

```bash
sleep 2
read POLLER_PID < .dataprojects/$TASK_ID/poller.pid
if ps -p "$POLLER_PID" > /dev/null 2>&1; then
  echo "poller running (pid $POLLER_PID)"
else
  echo "poller not running"
fi
tail -1 ".dataprojects/$TASK_ID/poller.log"
```

> `--token-refresh-cmd` is **optional**. If omitted, the daemon will not auto-refresh and will enter `auth_status: "broken"` when the token expires. Always pass a recipe for production-shape runs with expiring auth.


## Cadence

- **Fast phase** — 15s for the first 90s after spawn so users see early activity.
- **Base interval** — 60s once warm.
- **Idle backoff** — exponential up to `--max-interval` (default 180s) after consecutive idle polls.
- **Snap back** — reset to base on any new message or status change.
- **Terminal** — exit 0 once status ∈ `{Completed, Failed, Cancelled}` and no auto-recovery is mid-flight.
- **Hard cap** — `--max-runtime` (default 24h) to avoid runaway daemons.

## Automatic handling

- **MWC token expiry** — proactive refresh every `--token-refresh-interval` (validated before swap); reactive refresh on any auth-class 4xx; `auth_broken` state when refresh fails (does **not** advance `last_polled_at`).
- **Documented Spark statement transient** — normalized phrase match on `runDetails.errorMessage`, error-signature dedup (sha256 of `operationId|completedAt|err`), `POST /{taskId}/run` on the same task ID with backoff `30/60/120` flat, hard cap `--max-auto-retries=10`, time-based give-up `--no-progress-window-seconds=7200`. If `operationId` is absent, the signature degrades to `sha256("|completedAt|err")` — still functional, just lower-entropy.


- **Exit reason capture** — single-write `terminal.json` covering every exit path (terminal status, `max_runtime`, `max_auto_retries`, `no_progress_window`, `retry_signature_repeat`, `no_token_at_startup`, `run_post_failed_<HTTP>`, `crash`, `signal`). Mirrored into `state.terminal` so the dashboard can render it (`file://` cannot fetch a sibling JSON).

See [troubleshooting.md](troubleshooting.md) for recovery semantics.

## What the daemon writes

In `./.dataprojects/<task-id>/`:

- `state.js` — `window.__STATE = { ... }` consumed by `dashboard.html`. Includes `recovery` block and (on exit) `terminal` mirror.
- `state.json` — same content as JSON; the source of truth for resume.
- `messages.ndjson` — append-only audit log (every message including `tool` and `system`).
- `poller.log` — stdout/stderr from the poller for debugging.
- `poller.pid` — current PID; deleted on clean exit.
- `terminal.json` — exit marker written exactly once on any termination path. The agent reads this on re-engage to learn why the daemon stopped. Prior `terminal.json` is archived to `terminal.<UTC-ts>.<time_ns>.<pid>.json` when a new poller starts; use `terminal.*.json` to find archived markers.

## Cleanup

The poller exits on terminal status. To kill it manually:

```bash
kill "$(cat .dataprojects/<task-id>/poller.pid)"
```

It honors `SIGTERM` and `SIGINT` for clean shutdown: the `pid` file is removed, a final log line is written, and `terminal.json` records an exit reason for re-engage.

## Resume

On re-engage, read `terminal.json` first. If it exists, the poller exited cleanly enough to record `reason` (including `signal`, `max_runtime`, and `no_progress_window`); report that reason and ask before respawning. If `terminal.json` is absent and the recorded PID is not alive, treat it as an ungraceful death (machine sleep, reboot, OOM, `kill -9`) and respawn.

Before respawning, re-acquire a fresh MWC token and recreate the `--token-refresh-cmd` recipe from the current environment setup. The spawn snippet above builds that command from a `mktemp` helper script, so the old argv may point at a deleted file after reboot or `/tmp` cleanup. Reuse the same non-secret arguments (`--base-url`, `--task-id`, `--state-dir`, cadences, retry limits), but do not blindly reuse stale token files or refresh-script paths. The on-disk `state.json` is the source of truth — the new poller picks up where the old one left off and de-dupes messages by `id`. See [SKILL.md → Non-negotiables](../SKILL.md).
