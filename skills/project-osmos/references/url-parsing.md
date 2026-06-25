# Parsing Fabric URLs to extract IDs
Ask for the Lakehouse browser URL and parse workspace ID, Lakehouse ID, and environment from it. Do not ask for environment, workspace ID, or lakehouse ID separately during startup; direct IDs are not enough because the URL host determines environment. If the user pasted IDs instead of a URL, ask them to paste the Lakehouse URL.

## Required path: ask for the Lakehouse URL
Prompt the user with:
> Open Fabric in your browser, navigate to the Lakehouse where you want the Project Osmos run to be stored, copy the full URL from the address bar, and paste it here.

Run the parser below. Echo the parsed environment and **both parsed IDs in full** (no ellipsis — the user needs to verify the full GUIDs character-by-character) and require explicit user confirmation before doing anything else, including before rendering the intake recommendations card. Shortened (`85a394cb-…dda8`) GUIDs are only acceptable in the post-launch `Project Osmos started 🚀` summary table, never during pre-flight verification.

## Regex
Apply against the pasted URL, case-insensitive:
```text
/groups/(?P<ws>[0-9a-f-]{36})(?:/lakehouses/(?P<lh>[0-9a-f-]{36}))?
```
- `ws` → workspace ID
- `lh` → Lakehouse ID, required for a start flow
- Both GUIDs are 36 characters with the standard `8-4-4-4-12` hyphen layout.

### Supported URL shapes
| Shape | Example | Yields |
|---|---|---|
| Lakehouse home | `https://app.fabric.microsoft.com/groups/<ws>/lakehouses/<lh>?experience=power-bi` | workspace + lakehouse |
| Lakehouse explorer with table path | `https://app.fabric.microsoft.com/groups/<ws>/lakehouses/<lh>/tables/Invoice` | workspace + lakehouse |
| SQL endpoint of the same lakehouse | `https://app.fabric.microsoft.com/groups/<ws>/sqlendpoints/<sql>` | workspace only — ask user to also paste the Lakehouse URL |
| Notebook | `https://app.fabric.microsoft.com/groups/<ws>/synapsenotebooks/<nb>` | workspace only — ask user to also paste the Lakehouse URL |
| Workspace home | `https://app.fabric.microsoft.com/groups/<ws>/list` | workspace only — ask user to also paste the Lakehouse URL |

If the regex matches both groups and the host maps to an environment, proceed to confirmation. If it matches only the workspace, prompt:
> I read workspace `<ws-short>` from that URL but no Lakehouse. Please open the specific Lakehouse you want Spark to attach to and paste *that* URL.

If the regex matches nothing, or if the user pasted bare GUIDs instead of a URL, treat it as malformed for startup and ask the user to repaste the Lakehouse browser URL.

## Environment from the URL host
Map the URL host to the target environment. Do not offer `change-env`; changing environments requires a different Lakehouse URL because workspace and lakehouse IDs are environment-scoped.

| Host | Environment | Notes |
|---|---|---|
| `app.fabric.microsoft.com` | `prod` | Production Fabric portal host. |
| `app.powerbi.com` | `prod` | Production Power BI portal host. |
| `msit.powerbi.com` | `msit` | MSIT environment, Power BI portal host. |
| `msit.fabric.microsoft.com` | `msit` | MSIT environment, Fabric portal host. |


If the host cannot be mapped to a supported environment, ask the user to repaste a Lakehouse URL from the correct Fabric portal for that environment.

## Confirmation before any API call

IDs are always UUIDs and the environment can be different. Echo the parsed values in this exact shape and require explicit `yes` before proceeding:

```text
Parsed from your URL:
  Workspace ID:  85a394cb-0000-4000-8000-00000000dda8
  Lakehouse ID:  3852746b-0000-4000-8000-00000000b928
  Environment:   prod (from host app.fabric.microsoft.com)

Use these? (yes / no / repaste)
```

`repaste` re-runs the prompt. `no` cancels the start flow unless the user provides a new Lakehouse URL.

## Pseudocode

URL regex:

```python
import re

URL_RE = re.compile(
    r"/groups/(?P<ws>[0-9a-f-]{36})(?:/lakehouses/(?P<lh>[0-9a-f-]{36}))?",
    re.I,
)
```

Host map:

```python
HOST_ENV = {
    "app.fabric.microsoft.com":     "prod",
    "app.powerbi.com":              "prod",
    "msit.powerbi.com":            "msit",
    "msit.fabric.microsoft.com":   "msit",
}
```


Parser:
```python
def parse_fabric_url(url: str):
    m = URL_RE.search(url)
    if not m:
        return None
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url, flags=re.I).split("/", 1)[0].lower()
    env = HOST_ENV.get(host)
```


Parser return:
```python
    return {
        "workspace_id": m.group("ws"),
        "lakehouse_id": m.group("lh"),    # may be None
        "host":         host,
        "environment":  env,
    }
```
Use this inline parser in the agent's intake step; no separate script is required. If `lakehouse_id` or `environment` is `None`, do not proceed to auth or API calls; prompt for a complete Lakehouse URL from a supported Fabric portal.
