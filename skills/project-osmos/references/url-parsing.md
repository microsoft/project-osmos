# Parsing Fabric URLs to extract IDs
Use this reference only when the user chooses **Provide a Lakehouse URL**. Workspace/Lakehouse names and Fabric page context are separate valid context paths owned by `SKILL.md`; do not redirect those paths here or require a URL.

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
Accept only the public Fabric browser hosts below.

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
    normalized = value if "://" in value else f"https://{value}"
    parts = urlsplit(normalized)
    workspace_match = WORKSPACE_PATH_RE.match(parts.path)
    if not workspace_match:
        return None
    lakehouse_match = LAKEHOUSE_PATH_RE.match(parts.path)
    lakehouse_prefix = f"/groups/{workspace_match.group('ws')}/lakehouses/".lower()
    if parts.path.lower().startswith(lakehouse_prefix) and not lakehouse_match:
        return None
    host = parts.netloc.lower()
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

