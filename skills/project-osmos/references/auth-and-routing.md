# Authentication and route construction

Build the direct SparkCore task route after parsing the environment from the user's Lakehouse browser URL.

## Production-shape environments

Use a Power BI bearer token, workspace capacity lookup, MWC token generation, and a capacity-scoped SparkCore route.

Public production-shape hosts:
| Purpose | Host |
| --- | --- |
| Production workspace metadata and capacity lookup | `https://api.fabric.microsoft.com` |
| MSIT workspace metadata and capacity lookup | `https://msitapi.fabric.microsoft.com` |
| Production MWC token exchange | `https://api.fabric.microsoft.com/metadata/v201606/generatemwctoken` |
| MSIT MWC token exchange | `https://msitapi.fabric.microsoft.com/metadata/v201606/generatemwctoken` or `https://wabi-msit-us-east2-redirect.analysis.windows.net/metadata/v201606/generatemwctoken` |

Use the production Fabric API host for `prod`; use the MSIT Fabric API or WABI redirect host for `msit`.


> **Fabric API fallback for MWC token exchange:** In production-shape environments, prefer the Fabric API host for `generatemwctoken`. For MSIT, the regional WABI redirect host and the Fabric API host use the same `/metadata/v201606/generatemwctoken` path; when WABI is unreachable, use the Fabric API host instead.
> **Use `TargetUriHost` for SparkCore:** The `generatemwctoken` response includes a `TargetUriHost` field that is the routed SparkCore host for that capacity. Use it directly as the workload host instead of guessing a generic hostname.

### Token and route steps

1. Authenticate Azure CLI **for the same tenant the workspace's capacity lives in**: `az login --tenant <tenant-id>`. Do not rely on the default subscription from `az account show`; `generatemwctoken` is gated by the workspace's home tenant, and a token from a different tenant returns a silent `HTTP 403` (empty body).
2. Get a Power BI bearer token for that tenant: `az account get-access-token --tenant <tenant-id> --resource https://analysis.windows.net/powerbi/api`.
3. Call the workspace metadata endpoint and capture the API `capacityId` field. Use it as the route/token capacity ID, and persist it in dashboard state as `capacity_id`.
4. Call `generatemwctoken` with:
   - `capacityObjectId`
   - `workloadType` set to `SparkCore`
   - `workspaceObjectId`
   - `artifactObjectIds` containing the lakehouse ID
5. Use the returned token in the task route.

#### Worked example

Set `FABRIC_API_HOST` to `https://api.fabric.microsoft.com` for production or `https://msitapi.fabric.microsoft.com` for MSIT. Keep tokens in environment variables, not on command lines.
```bash
# 1. Power BI bearer token (stored in env, not on the command line; pass --tenant explicitly)
export PBI_TOKEN=$(az account get-access-token \
  --tenant <tenant-id> \
  --resource https://analysis.windows.net/powerbi/api \
  --query accessToken -o tsv)

# 2. Resolve the workspace capacity ID and capture its displayName for the dashboard
curl -s \
  "$FABRIC_API_HOST/v1/workspaces/{workspaceId}" \
  -H "Authorization: Bearer $PBI_TOKEN"
# Response includes: { "id", "displayName" (→ workspace_name), "capacityId" (→ capacity_id), ... }

# 2b. Resolve the lakehouse displayName for the dashboard (separate call —
#     neither the workspace GET above nor the task GET return it)
curl -s \
  "$FABRIC_API_HOST/v1/workspaces/{workspaceId}/lakehouses/{lakehouseId}" \
  -H "Authorization: Bearer $PBI_TOKEN"
# Response includes: { "id", "displayName" (→ lakehouse_name), ... }

# 3. Exchange for a SparkCore MWC token
curl -s -X POST \
  "$FABRIC_API_HOST/metadata/v201606/generatemwctoken" \
  -H "Authorization: Bearer $PBI_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "capacityObjectId": "{capacityId}",
    "workloadType": "SparkCore",
    "workspaceObjectId": "{workspaceId}",
    "artifactObjectIds": ["{lakehouseId}"]
  }'
```
Capture the response `Token` value as `MWC_TOKEN` and `TargetUriHost` as `SPARKCORE_HOST` (do not echo token values):
```bash
export MWC_TOKEN="<token-from-generatemwctoken-response>"
export SPARKCORE_HOST="<TargetUriHost-from-generatemwctoken-response>"
```
Direct route shape:
```text
https://{SPARKCORE_HOST}/webapi/capacities/{capacityId}/workloads/SparkCore/SparkCoreService/direct/v1/workspaces/{workspaceId}/artifacts/{lakehouseId}/aichat
```
Production-shape routes normally use:
```text
Authorization: mwctoken {token}
```



## Secret handling

- Prefer token environment variables over command-line token arguments.
- Do not print bearer tokens, MWC tokens, certificate payloads, or tenant secrets.
- Redact auth headers from any logs copied into issues or PRs.
