# Authentication and route construction

Build the Project Osmos task route after parsing and confirming the user's Fabric Lakehouse URL.

## Required lookups

Before starting a task, resolve:

| Field | Why |
| --- | --- |
| `workspace_name` | Displayed in the run card and dashboard. |
| `lakehouse_name` | Displayed as the default Lakehouse for the Spark session. |
| `capacity_id` | Required for route construction and support handoff. |

Surface lookup failures directly. Do not substitute GUIDs for missing display names, and do not write `(unknown)` into dashboard state.

## Authorization

Use the user's Azure CLI identity to acquire an access token for Fabric APIs:

```bash
az account get-access-token \
  --resource https://analysis.windows.net/powerbi/api \
  --query accessToken \
  -o tsv
```

Keep tokens out of command-line arguments where possible. Prefer environment variables or temporary files with user-only permissions, and redact authorization headers from logs.

## Route construction

Use the public Fabric Project Osmos task endpoint available for the confirmed workspace, capacity, and Lakehouse. The skill should construct one task base URL and reuse it for task creation, messages, run, polling, retries, and follow-ups.

Store the resolved non-secret routing values in dashboard state:

- `workspace_id`
- `workspace_name`
- `lakehouse_id`
- `lakehouse_name`
- `capacity_id`
- `task_id`

Never persist bearer tokens, authorization headers, certificate payloads, or tenant-private authentication responses.

## Secret handling

- Prefer token environment variables or token files over command-line token arguments.
- Do not print bearer tokens or authorization headers.
- Redact tokens from copied logs.
- Treat tenant details, workspace IDs, Lakehouse IDs, and capacity IDs as sensitive operational data.
