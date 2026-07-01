# Authentication and route construction

Build the direct SparkCore task route after parsing and confirming the user's Lakehouse browser URL.

## Public Fabric route

Use a Power BI bearer token, workspace capacity lookup, MWC token generation, and a capacity-scoped SparkCore route.

Public hosts:
| Purpose | Host |
| --- | --- |
| Workspace metadata and capacity lookup | `https://api.fabric.microsoft.com` |
| MWC token exchange | `https://api.fabric.microsoft.com/metadata/v201606/generatemwctoken` |

> **Use `TargetUriHost` for SparkCore:** The `generatemwctoken` response includes a `TargetUriHost` field that is the routed SparkCore host for that capacity. Use it directly as the workload host instead of guessing a generic hostname.

### Token and route steps

1. Authenticate Azure CLI **for the same tenant the workspace's capacity lives in**: `az login --tenant <tenant-id>`. Do not rely on the default subscription from `az account show`; `generatemwctoken` is gated by the workspace's home tenant, and a token from a different tenant returns a silent `HTTP 403` (empty body).
2. Get a Power BI bearer token for that tenant: `az account get-access-token --tenant <tenant-id> --resource https://analysis.windows.net/powerbi/api`.
3. Call the workspace metadata endpoint and capture the API `capacityId` field. Use it as the route/token capacity ID, and persist it in dashboard state as `capacity_id`.
4. Call the public Fabric `generatemwctoken` endpoint with:
   - `capacityObjectId`
   - `workloadType` set to `SparkCore`
   - `workspaceObjectId`
   - `artifactObjectIds` containing the lakehouse ID
5. If token generation succeeds, use the returned token in the task route.

Do not guess or substitute another token-exchange host. Use the tested helper scripts below to perform this same flow. They capture the routed home cluster from Fabric response headers and retry `generatemwctoken` there only for the specific `Tenant not authorized for cluster` response. `TargetUriHost` is still used only after token generation succeeds, as the SparkCore workload host for later task calls.

### Tested auth helper scripts

The helpers write `routing.json`, a private `mwc-token` file, `env.sh` for Bash, and `env.ps1` for PowerShell. Use the generated environment file for the unchanged task lifecycle and dashboard poller flow.

```bash
python3 skills/project-osmos/scripts/resolve-auth-and-routing.py \
  --tenant-id <tenant-id> \
  --workspace-id <workspace-id> \
  --lakehouse-id <lakehouse-id> \
  --output-dir .dataprojects/auth
source .dataprojects/auth/env.sh
```

```powershell
pwsh -NoProfile -File skills/project-osmos/scripts/resolve-auth-and-routing.ps1 `
  -TenantId <tenant-id> `
  -WorkspaceId <workspace-id> `
  -LakehouseId <lakehouse-id> `
  -OutputDir .dataprojects/auth
. .dataprojects/auth/env.ps1
```

Direct route shape:
```text
${TASKS_BASE}
```
Public Fabric routes normally use:
```text
Authorization: mwctoken <contents of TOKEN_FILE>
```

## Secret handling

- Prefer token environment variables over command-line token arguments.
- Do not print bearer tokens, MWC tokens, certificate payloads, or tenant secrets.
- Redact auth headers from any logs copied into issues or PRs.
