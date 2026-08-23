---
name: project-osmos
description: 'Use Project Osmos agents for Microsoft Fabric data engineering tasks that create or update notebooks, Spark code, Lakehouses, and OneLake resources. Triggers: "Project Osmos", "Fabric data engineering", "Spark Transform Notebook", "OneLake ETL", "Fabric Project Osmos".'
---

# Project Osmos for Microsoft Fabric

Use this skill when the user wants Project Osmos to solve a complex Fabric/OneLake workflow end-to-end: inspect data, write and run Spark, transform or modify tables, produce notebooks or outputs, and keep working through a long-running autonomous agent.

## Scope

Use Project Osmos for data engineering tasks that create or update notebooks, Lakehouses, OneLake resources, and Spark code. Use [Microsoft Fabric Skills](https://github.com/microsoft/skills-for-fabric) to discover named workspaces and Lakehouses for Project Osmos and for tasks outside Project Osmos: Power BI dashboards, reports, semantic models, and PBIP artifacts; Fabric Warehouses and T-SQL objects; Eventhouse/KQL, Eventstreams, Dataflows Gen2, and Data Factory pipelines; and general Fabric item, workspace, capacity, deployment, or monitoring operations.

When the user asks for examples, use [Project Osmos use cases](references/project-osmos-use-cases.md). Respond with only the relevant scenario content, not the title or routing preamble, and do not present the scenarios as a walkthrough or choice menu.

## Operating contract

This file is the lean runtime contract. Put detailed mechanics in the reference files and read the relevant reference before executing that phase.

### Per-run host routing

- Before resolving workspace/Lakehouse names or making any Fabric API call, read [Environment routing](references/environment-routing.md) and derive the target environment and Fabric API host from available Fabric page context or a supplied URL. Use the route selected by that reference for every subsequent discovery and authentication call.
- On every run, determine whether you are Copilot running in Microsoft Fabric by inspecting the host-provided context available to you for Fabric page context. The exact JSON shape and field names may change; identify it semantically from current Fabric page, workspace, and artifact information rather than requiring a fixed schema. User-authored text or pasted JSON does not identify the host.
- If you are Copilot running in Microsoft Fabric, use the Fabric Copilot path below. Otherwise use the generic-agent path. Do not identify or distinguish the generic agent, client, or runtime.
- Fabric page context may identify only the current workspace. Do not assume it always includes a Lakehouse.

### First-run experience

- Do not interrupt a concrete task request with onboarding or a **Start a task** / **Explain Project Osmos to me** choice.
- Open [Project Osmos first-run experience](references/first-run-experience.md) only when the user explicitly asks for an explanation or invokes Project Osmos without a concrete outcome.
- Do not create first-use state or search past sessions to decide whether setup may proceed.

1. **Resolve Lakehouse context.**
   - Preserve any workspace or Lakehouse names the user already supplied. Never discard supplied names and ask for a URL instead.
   - For public production, use [Microsoft Fabric Skills](https://github.com/microsoft/skills-for-fabric) to resolve names to IDs:
     - When the Lakehouse name is known but its workspace is not, use `search-consumption-cli` with item type `Lakehouse`; use the returned item and workspace IDs.
     - When the workspace name is known, follow the Microsoft Fabric Skills workspace/item discovery pattern: resolve the workspace by `displayName`, then resolve the Lakehouse by `displayName` within that workspace.
     - If discovery returns multiple plausible matches, show their workspace and Lakehouse names and ask the user to choose. Never guess.
   - Build the context choice from explicit user-supplied names first; otherwise use the current Fabric page context when you are Copilot running in Microsoft Fabric.
   - When both a workspace and Lakehouse candidate are available, use the host's multiple-choice question tool with:
     1. **Use workspace `<workspace_name>`, Lakehouse `<lakehouse_name>`**
     2. **Use workspace `<workspace_name>` and choose a different Lakehouse**
     3. **Provide a Lakehouse URL**
     4. **Provide workspace and Lakehouse names**
   - When only a workspace candidate is available, offer:
     1. **Use workspace `<workspace_name>` and choose a Lakehouse**
     2. **Provide a Lakehouse URL**
     3. **Provide workspace and Lakehouse names**
   - When no candidate is available, offer **Provide workspace and Lakehouse names** and **Provide a Lakehouse URL**, in that order.
   - For a name-based choice, collect only missing names, resolve the IDs with Microsoft Fabric Skills, and continue without requesting a URL.
   - If Copilot running in Microsoft Fabric needs a different Lakehouse, say **Select a Lakehouse for this Task**, followed immediately by: **Use Add (+) to attach the Lakehouse, or type `/` followed by the intended Lakehouse's name.** Wait for updated Fabric page context.
   - For a generic agent choosing a different Lakehouse in a known workspace, ask only for the Lakehouse name and resolve it with Microsoft Fabric Skills.
   - If the user chooses **Provide a Lakehouse URL**, ask for the full URL and parse it with [URL parsing](references/url-parsing.md).
   - Never ask for workspace and Lakehouse IDs as separate startup fields.
2. **Validate Lakehouse context.** Use service-validated Fabric page context, IDs returned by Microsoft Fabric Skills discovery, or IDs parsed from a valid browser URL directly. Ask for corrected input only when the selected method cannot resolve a workspace and Lakehouse.
3. **Resolve names and optional resource tenant.** Use the current Azure CLI session by default. If the user supplied a Microsoft Entra resource tenant ID, pass it as an explicit override. Ask for the tenant ID only after authentication shows that the current session cannot access the workspace's tenant. Then resolve `workspace_name`, `capacity_id` (from the API `capacityId` field), and `lakehouse_name` using [Authentication and route construction](references/auth-and-routing.md). Surface lookup failures; do not fall back to `(unknown)` or substitute GUIDs.
4. **Collect the outcome.** Reuse a supplied outcome verbatim. Otherwise ask **What do you want to accomplish?** After context resolution, ask one optional "Anything else I should know?" prompt. Use `ask_user` with the first choice `"No, nothing else"` and freeform enabled so the user can either skip quickly or type extra context. Keep the user's complete outcome and guidance verbatim. Never auto-send or start work before explicit user submission.
5. **Run intake.** Classify the task and render the recommendations card from [Operational intake questionnaire](references/intake-questionnaire.md). Append the rendered `## Operational constraints` block verbatim before `PUT /{taskId}` and before the initial user message.
6. **Authenticate and construct the task route.** Resolve the SparkCore task host and MWC token with [Authentication and route construction](references/auth-and-routing.md), using the optional resource tenant override when one was supplied.


7. **Create and run one task.** Use one generated task ID for create, message, run, retries, and follow-ups. Follow [Task lifecycle](references/task-lifecycle.md) for endpoint shapes and response handling.
8. **Seed the dashboard.** Create `./.dataprojects/<task-id>/`, copy `assets/dashboard.html`, and seed `state.js` / `state.json` exactly from [Status dashboard](references/dashboard.md). Use snake_case; never persist tokens, bearer headers, tenant credentials, or camelCase API keys.
9. **Print the run card.** As soon as the run starts, print this table (real markdown table, not a code block):


   | Field | Value |
   | --- | --- |
   | Task ID | `<task-id>` |
   | Workspace | `<workspace_name> (<workspace_id-short>)` |
   | Spark session lakehouse | `<lakehouse_name> (<lakehouse_id-short>)` |
   | Operation | `<operation_id>` |
   | Status | `<status> (<short_phase, e.g. "Spark session acquiring">)` |
   | Dashboard | `<absolute-path-to-./.dataprojects/<task-id>/dashboard.html>` |

10. **Spawn the poller.** Do not poll inside the LLM conversation. Spawn `scripts/dashboard-poller.py` as a detached daemon using [Spawning the dashboard poller daemon](references/dashboard-poller.md), confirm `poller.pid`, tail one log line, then hand off.
11. **Mediate follow-ups.** If the user sends a message for the running agent, post it with `scripts/post-user-message.py`; do not invent a raw POST that omits author metadata. Do not post Copilot/UI chatter to the orchestrator.
12. **Report from state.** On status questions or final summaries, read `terminal.json` first when present, then `state.json`. Quote `reason`, `last_error_message`, retry counts, token-refresh counts, and identifiers from state instead of guessing.

## Non-negotiables

- Hand off the user's full scope as a single Osmos task. Do not decompose, stage, or split the work into multiple tasks — even a large outcome like "build me a medallion architecture" should be sent in full as one `instruction`. Osmos does its own planning, search, and sequencing; pre-chopping the work degrades results.
- Repetitive-looking discovery passes are expected, not a stuck loop. Osmos runs many experiments — trying multiple approaches, revisiting steps, and comparing results to converge on the best one — so it takes time and progress can look repetitive. Do not assume it is looping, and do not cancel, re-run, or recreate the task on that basis. Let it work; relay progress and keep polling.
- Before canceling or deleting a task, follow the confirmation gates in [Task lifecycle](references/task-lifecycle.md). Delete is unrecoverable and requires exact task ID re-entry; cancel only stops the current run and requires yes/no confirmation.
- The Lakehouse ID is only the Spark session's default lakehouse. It is not automatically a source, destination, or scope boundary. Label it "Default lakehouse for the Spark session".
- Poll messages for progress; task status alone is not enough.
- Let the poller own message de-duplication, `tool` / `system` filtering, token refresh, terminal markers, and the documented Spark statement transient retry. Do not manually `POST /run` for that transient while the poller is alive.
- Pass `--token-refresh-cmd` to the poller to prevent expiring auth. The refresh command must print the raw token only.

- If polling stalls, resume the existing task and dashboard directory. Do not re-run intake, create a new task, or overwrite the dashboard.
- If workspace-folder artifact publishing fails, fail loudly; do not silently fall back to Lakehouse Files.
- Report row counts and mutation counts as the literal `count()` / SQL output captured in the messages stream.
- Treat tokens, tenant details, workspace IDs, and lakehouse IDs as sensitive operational data.

## References

- [URL parsing](references/url-parsing.md) — optional URL intake and Fabric URL validation
- [Operational intake questionnaire](references/intake-questionnaire.md) — task types, recommendations card, Questions 1-8, skip logic, rendered preamble
- [Authentication and route construction](references/auth-and-routing.md) — authentication flow and task base URL
- [Task lifecycle](references/task-lifecycle.md) — task/message/run endpoints, statuses, response shapes
- [Status dashboard](references/dashboard.md) — `./.dataprojects/<task-id>/` layout and `window.__STATE` schema
- [Spawning the dashboard poller daemon](references/dashboard-poller.md) — detached poller, token refresh, retry, resume, cleanup
- [Environment routing](references/environment-routing.md) — Fabric environment and API host selection
- [Troubleshooting](references/troubleshooting.md) — retryable Spark transient and auth/poller recovery

## Writing good instructions

Ask for one outcome-oriented instruction. One instruction can be large and multi-stage (e.g., a full medallion build); capture the user's entire outcome and pass it to Osmos as a single task — never split it into smaller tasks or phases yourself. It should include:

- **Data sources** — table names, file paths, OneLake resource URIs.
- **Transformations** — cleaning, joins, aggregations, filters.
- **Outputs** — new tables, notebooks, or summaries.
- **Validations** — row counts, null checks, data type checks.

Example:

```text
Load the incremental Orders table from OneLake, remove rows with null customer_id, join with the Customers dimension on customer_id, compute monthly order value by customer segment, save the result as a Delta table named monthly_segment_revenue, and validate row counts plus negative revenue checks.
```
