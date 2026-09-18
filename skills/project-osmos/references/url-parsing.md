# Fabric URL intake and task links
Use the intake-parsing sections only when the user chooses **Provide a Lakehouse URL**. Workspace/Lakehouse names and Fabric page context are separate valid context paths owned by `SKILL.md`; do not redirect those paths here or require a URL.

[Task page URL construction](#task-page-url-construction) applies after every task starts, regardless of how its workspace and Lakehouse were selected.

## Ask for the Lakehouse URL
Prompt the user with:
> Open Fabric in your browser, navigate to the Lakehouse where you want the Project Osmos run to be stored, copy the full URL from the address bar, and paste it here.

Run the parser below. When both IDs are valid and the host is supported, use the parsed context directly. Do not add a second confirmation step for values derived from the URL the user just supplied.

## Path patterns
Parse the URL first, then apply these patterns to `urlsplit(...).path` only. Never search the raw URL, query, or fragment for IDs.
```text
UUID = [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}
workspace = ^/groups/(?P<ws>{UUID})(?:/|$)
lakehouse = ^/groups/(?P<ws>{UUID})/lakehouses/(?P<lh>{UUID})(?:/|$)
```
- `ws` → workspace ID
- `lh` → Lakehouse ID when the path is Lakehouse-scoped
- Both GUIDs are 36 characters with the standard `8-4-4-4-12` hyphen layout.
- If the path begins with `/groups/<workspace-id>/lakehouses/` but the Lakehouse segment is not a strict UUID, reject the URL rather than treating it as workspace-only.

### Supported URL shapes
| Shape | Example | Yields |
|---|---|---|
| Lakehouse home | `https://app.fabric.microsoft.com/groups/<ws>/lakehouses/<lh>?experience=power-bi` | workspace + lakehouse |
| Lakehouse explorer with table path | `https://app.fabric.microsoft.com/groups/<ws>/lakehouses/<lh>/tables/Invoice` | workspace + lakehouse |
| SQL endpoint of the same lakehouse | `https://app.fabric.microsoft.com/groups/<ws>/sqlendpoints/<sql>` | workspace only — return to the context choices |
| Notebook | `https://app.fabric.microsoft.com/groups/<ws>/synapsenotebooks/<nb>` | workspace only — return to the context choices |
| Workspace home | `https://app.fabric.microsoft.com/groups/<ws>/list` | workspace only — return to the context choices |

If the Lakehouse pattern matches and the host is supported, proceed. If only the workspace pattern matches, return to the context choices in `SKILL.md` with that workspace as the candidate instead of requiring another URL.

If neither path pattern matches, treat the URL as malformed and ask the user to repaste it or choose the workspace/Lakehouse names path.

## Supported URL hosts
Accept only HTTPS URLs for the public Fabric browser hosts below, with no
credentials and either the default port or port 443. Validate this before
authentication or task creation so the later task-link launch uses the same
portal policy. Ask for corrected context when validation fails.

| Host | Notes |
|---|---|
| `app.fabric.microsoft.com` | Fabric portal host. |
| `app.powerbi.com` | Power BI portal host. |

If the host is not supported, ask the user to repaste a Lakehouse URL from the public Fabric portal or choose the workspace/Lakehouse names path.


## Validated context

IDs are always UUIDs. A supported host plus valid workspace and Lakehouse UUIDs is sufficient to continue. If parsing or validation fails, let the user repaste the URL or choose the workspace/Lakehouse names path.

## Pseudocode

Path regexes:

```python
import re
from urllib.parse import urlsplit

UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
WORKSPACE_PATH_RE = re.compile(rf"^/groups/(?P<ws>{UUID_RE})(?:/|$)", re.I)
LAKEHOUSE_PATH_RE = re.compile(
    rf"^/groups/(?P<ws>{UUID_RE})/lakehouses/(?P<lh>{UUID_RE})(?:/|$)", re.I
)
```

Supported host check:

```python
SUPPORTED_HOSTS = {
    "app.fabric.microsoft.com",
    "app.powerbi.com",
}
```


Parser:
```python
def parse_fabric_url(url: str):
    value = url.strip()
    if any(character.isspace() or character == "\\" for character in value):
        return None
    normalized = value if re.match(r"^[a-z][a-z0-9+.-]*://", value, re.I) else f"https://{value}"
    try:
        parts = urlsplit(normalized)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or parts.username is not None:
        return None
    host = parts.netloc.lower()
    if parts.hostname in {"app.fabric.microsoft.com", "app.powerbi.com"}:
        if parts.scheme != "https" or port not in {None, 443}:
            return None
        host = parts.hostname
    workspace_match = WORKSPACE_PATH_RE.match(parts.path)
    if not workspace_match:
        return None
    lakehouse_match = LAKEHOUSE_PATH_RE.match(parts.path)
    lakehouse_prefix = f"/groups/{workspace_match.group('ws')}/lakehouses/".lower()
    if parts.path.lower().startswith(lakehouse_prefix) and not lakehouse_match:
        return None
    if host not in SUPPORTED_HOSTS:
        return None
```


Parser return:
```python
    return {
        "workspace_id": workspace_match.group("ws"),
        "lakehouse_id": lakehouse_match.group("lh") if lakehouse_match else None,
        "host":         host,
    }
```

Use this inline parser in the agent's intake step; no separate script is required. An unsupported host or invalid path is rejected. A valid workspace-only path returns `lakehouse_id: None` to the context choices in `SKILL.md`; do not proceed to auth or task creation until a Lakehouse is selected.

## Task page URL construction

Use this flow after every task starts. All users receive the Fabric task link;
no workspace or tenant enrollment signal is required.

Run `scripts/launch-task-page.py`; do not reimplement the URL or browser logic
inline. When a Fabric page or Lakehouse URL is available, pass it as
`--source-url` so the helper preserves the environment and all unowned query
tokens while replacing the task selection. Without a source URL, production
uses `https://app.fabric.microsoft.com`; private environments must pass a
trusted `--portal-base-url` instead of guessing a host. Production accepts only
the supported HTTPS public portal hosts (default port or 443), without URL
credentials. Private source/base URLs must already have been validated against
the active environment's trusted portal context by the caller.
Pass the environment token from routing, not a guessed label. Production
spelling is case-insensitive; `production` is also normalized to `prod`.

```text
<scheme>://<netloc>/groups/<workspace_id>/lakehouses/<lakehouse_id>?<query>
```

`<query>` is the original pasted query string, transformed as follows:

- **Swap `selectedPath`** — remove any existing `selectedPath=...` and
  append `selectedPath=ProjectOsmos%2F<task-id>`. This is the only
  per-task change (percent-encode the slash as `%2F`).
- **Force `projectOsmosUX=1`** — replace any existing `projectOsmosUX`
  value and add it if absent, so the Lakehouse task page renders.
- **Preserve everything else verbatim** — keep each remaining parameter
  exactly as pasted (`experience=power-bi`, other
  flags). Do **not** decode/re-encode values; a round-trip through a
  query parser could re-encode already-encoded
  slashes and can change the URL the user relies on.

Rebuild the path from the validated `workspace_id` / `lakehouse_id` so any
table or sub-path in the pasted URL (e.g. `/tables/Invoice`) is dropped,
and preserve the original scheme and netloc.

Print `task_page_url` as `Task page` in the run card and surface it in chat.
The helper attempts to open it in the default browser unless `--no-open` is
needed. Browser opening is bounded to three seconds; a failed or timed-out
launch is non-fatal: print the warning
and URL and continue starting the headless recovery poller. The Fabric link is
the only browser target; no local HTML fallback is created or opened.
Opening is best-effort: the timeout bounds the helper's wait and stops its
direct browser controller, not every descendant an OS or custom launcher may
start. The helper does not manage the browser's process tree.
The browser subprocess environment excludes `MWC_TOKEN`, `PBI_TOKEN`, and
`BEARER` (case-insensitively), while retaining normal settings such as `BROWSER`
and `DISPLAY`. The caller's environment is unchanged.
If URL validation fails (exit 2), report the error and task ID, leave
`task_page_url` unset, and start the recovery poller anyway. Correct the portal
context and rerun this helper for the same task; never recreate the task or
substitute a production host for missing private context.

Use `PYTHON_RUNNER` selected by [Python helper runtime](python-helper-runtime.md):

```bash
"${PYTHON_RUNNER[@]}" skills/project-osmos/scripts/launch-task-page.py \
  --environment prod \
  --workspace-id <workspace-id> \
  --lakehouse-id <lakehouse-id> \
  --task-id <task-id> \
  --source-url <optional-fabric-page-or-lakehouse-url>
```

The JSON response contains `task_page_url`, a non-fatal `warning`, and one
structured `telemetry` object. The telemetry includes CLI origin, task-created
state, launch result, fallback use, workspace ID, task ID,
and environment. It never includes prompt or instruction content.
The object is local structured output, not an automatic telemetry upload.
`--no-open` reports `not_attempted`, without a failure warning or fallback.
