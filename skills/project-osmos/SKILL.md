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

### Local Python helper runtime

- Before running any bundled Python helper, follow [Python helper runtime](references/python-helper-runtime.md). Reuse one compatible existing Python 3.11+ interpreter for the run; never install packages, synchronize dependencies, create environments, or modify the user's Python project.

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
2. **Validate Lakehouse context.** Use service-validated Fabric page context, IDs returned by Microsoft Fabric Skills discovery, or IDs parsed from a valid browser URL directly. Validate supplied portal URLs against [URL parsing](references/url-parsing.md) before authentication or task creation (public URLs require supported HTTPS hosts). Ask for corrected input only when the selected method cannot resolve a workspace and Lakehouse or provides an invalid portal URL.
3. **Resolve names and optional resource tenant.** Use the current Azure CLI session by default. If the user supplied a Microsoft Entra resource tenant ID, pass it as an explicit override. Ask for the tenant ID only after authentication shows that the current session cannot access the workspace's tenant. Then resolve `workspace_name`, `capacity_id` (from the API `capacityId` field), and `lakehouse_name` using [Authentication and route construction](references/auth-and-routing.md). Surface lookup failures; do not fall back to `(unknown)` or substitute GUIDs.
4. **Collect the outcome.** Reuse a supplied outcome verbatim. Otherwise ask **What do you want to accomplish?** After context resolution, ask one optional "Anything else I should know?" prompt. Use `ask_user` with the first choice `"No, nothing else"` and freeform enabled so the user can either skip quickly or type extra context. Keep the user's complete outcome and guidance verbatim. Never start from an unsubmitted draft; acceptance in the intake step is the authorization to create and start the task.
5. **Run intake and compile the handoff contract.** Follow
   [Operational intake questionnaire](references/intake-questionnaire.md):
   extract explicit requirements before applying task-type fallbacks, derive
   Questions 1–5 per resource/write target, collect every dependent value, and
   run the pre-dispatch contradiction check against the complete user outcome.
   Do not create or run the task while a key, source scope, target state,
   artifact path/name, approval gate, mutation limit, or conflict remains
   unresolved. Compose the instruction with the verbatim `## User outcome`
   first and the self-contained `## Execution plan` immediately below it.
   Send the exact same composed
   instruction in `PUT /{taskId}` and the initial user message; never send bare
   option labels without their executable meanings. Keep the handoff compact:
   preserve the user outcome verbatim, include only selected execution-critical
   semantics, omit unselected options/rationales/`n/a` fields, and cap generated
   operational text at 2,500 characters. The service limit is 10,000
   characters; target 9,500 or fewer. Before `PUT`, run
   `"${PYTHON_RUNNER[@]}" skills/project-osmos/scripts/check-instruction-length.py --path
   <instruction-file> --limit 9500`. If the complete handoff does not fit,
   preserve it exactly using the
   [oversized instruction fallback](references/oversized-instructions.md);
   never truncate, paraphrase, or ask the user to shorten it.
6. **Authenticate and construct the task route.** Resolve the SparkCore task host and MWC token with [Authentication and route construction](references/auth-and-routing.md), using the optional resource tenant override when one was supplied.


7. **Create and run one task.** Use one generated task ID for any oversized-instruction upload, create, message, run, retries, and follow-ups. Follow [Task lifecycle](references/task-lifecycle.md) for endpoint shapes and response handling.
8. **Persist task and recovery context.**
   - Create `./.dataprojects/<task-id>/` and seed `state.json` from [Task state and audit](references/task-state.md). Preserve the accepted intake contract, route identifiers, and confirmed artifacts for CLI resume.
   - Use snake_case and never persist tokens, bearer headers, tenant credentials, or camelCase API keys.
9. **Launch the task view and print the run card.**
   - For every user, follow [Task page URL construction](references/url-parsing.md#task-page-url-construction) and run `scripts/launch-task-page.py` with the environment, workspace, Lakehouse, and task IDs. No enrollment signal is required. Pass the available Fabric page/Lakehouse URL as `--source-url`; if none is available, production uses the canonical Fabric portal and a private environment must supply its trusted portal base URL. Print `task_page_url` as `Task page`, surface it as a clickable Fabric link in chat, and save it in `state.json` before starting the poller. The helper's JSON contains prompt-free structured telemetry for task creation, launch result, URL fallback, workspace, task, and environment.
   - A browser launch result of `failed` or `timed_out` is non-fatal (opening is bounded to three seconds). Print the helper's warning and canonical URL; the remote task continues and the recovery poller must still start. `--no-open` reports `not_attempted` without a failure warning. Never substitute a local HTML path for the Fabric link.
   - If the helper cannot build a URL (exit 2), print the error and task ID, leave `task_page_url` unset, set the run card's `Task page` value to `Unavailable (URL validation failed)`, and start recovery anyway; never print an empty link or literal `<task_page_url>`. Correct the validated portal context and rerun the helper for the same task; never recreate it or guess a private portal host.

   | Field | Value |
   | --- | --- |
   | Task ID | `<task-id>` |
   | Workspace | `<workspace_name> (<workspace_id-short>)` |
   | Spark session lakehouse | `<lakehouse_name> (<lakehouse_id-short>)` |
   | Operation | `<operation_id>` |
   | Task page | `<task_page_url>` (clickable Fabric link) |
   | Status | `<status> (<short_phase>)` |

   Use all listed rows rather than inventing a reduced summary.
10. **Start headless monitoring and recovery.**
   - For every task, spawn `scripts/dashboard-poller.py` using [Spawning the recovery poller](references/dashboard-poller.md), confirm `poller.pid`, tail one log line, then hand off. Do not poll inside the LLM conversation.
   - The retained script name is legacy; it runs without a local UI. Token refresh, automatic recovery, audit capture, and clarification-loop detection do not depend on either browser page being open. Local recovery requires the process and machine to remain running and authenticated; stopping it does not cancel the remote task.
   - Use Fabric for visual progress. Continue this skill's conversation and control operations through the CLI task APIs, not browser automation.
11. **Mediate follow-ups.** Continue the existing task; never create a replacement.
   - Read `./.dataprojects/<task-id>/terminal.json` first when present, then `state.json`, so the prior poller outcome and task route are understood before any write.
   - Re-resolve the existing task route and acquire fresh authentication as needed using [Authentication and route construction](references/auth-and-routing.md). Fetch live task status before deciding whether a run is active; local state is context, not authority.
   - Post the full user-authored message first with `scripts/post-user-message.py --output json`. The helper preserves flat author metadata, normalizes string, numeric, and stringified-numeric statuses, and also considers `runDetails.completedAt` and `runDetails.errorMessage`. Do not invent a raw message POST, truncate the user's text, or post Copilot/UI chatter.
   - Elicitation responses commonly arrive after the run that asked the question has become terminal; treat that as the normal continuation path. After the message succeeds, the helper always fetches live status again so the decision reflects the state after the user's answer was accepted.
   - If that post-message status is `Running` with no completion or error evidence, the helper does not call `/run`. Otherwise it calls `POST /{taskId}/run` exactly once on the same task ID. If that request returns HTTP 409, it performs one live status read and accepts the conflict only when a run is now active; it never sends a second run request.
   - When the JSON result has `poller_restart_required: true`, ensure a poller is running with fresh auth against the existing state directory as described in [Spawning the recovery poller](references/dashboard-poller.md). Reuse a healthy existing process; do not launch duplicate recovery workers. A newly started poller archives the prior terminal marker.
   - Surface status lookup, message-post, run-start, authentication, and poller-start failures explicitly. Do not report a successful continuation unless every required step completed.


12. **Report authoritative status.** Read `terminal.json` first when present, then `state.json` for local recovery context. Fetch live task status and messages when reporting current service state; distinguish a stopped poller from a stopped task. Quote returned status/error fields and identifiers instead of guessing, and include the Fabric task link when the user needs to view progress.

## Non-negotiables

- Hand off the user's full scope as a single Osmos task. Do not decompose, stage, or split the work into multiple tasks — even a large outcome like "build me a medallion architecture" should be sent in full as one `instruction`. Osmos does its own planning, search, and sequencing; pre-chopping the work degrades results.
- Repetitive-looking discovery passes are expected when Osmos is running
  different experiments, tool calls, or validation steps. Verbatim-identical
  or semantically equivalent clarification questions are different: if the
  same question is asked three times without intervening non-elicitation
  assistant progress, treat the run as an elicitation loop. Surface the
  repeated question and the conflicting contract fields; do not keep waiting,
  auto-answer, restart, or describe it as normal experimentation. Tool and
  system messages remain audit-only and are not interpreted as progress.
- Only a gate explicitly listed under `Approval gates` may pause for user
  approval. `fail if target already populated` is a terminal policy, not an
  approval gate; a later confirmation does not override it. If Osmos asks
  whether an undeclared gate exists, report a handoff-contract failure instead
  of repeatedly forwarding the question.
- Before canceling or deleting a task, follow the confirmation gates in [Task lifecycle](references/task-lifecycle.md). Delete is unrecoverable and requires exact task ID re-entry; cancel only stops the current run and requires yes/no confirmation.
- The Lakehouse ID is only the Spark session's default lakehouse. It is not automatically a source, destination, or scope boundary. Label it "Default lakehouse for the Spark session".
- Poll messages for progress; task status alone is not enough.
- Let the headless poller own message de-duplication, `tool` / `system` filtering, token refresh, terminal markers, and the documented Spark statement transient retry. Do not manually `POST /run` for that transient while the poller is alive.
- Pass `--token-refresh-cmd` to every local poller to prevent expiring auth. The refresh command must print the raw token only.

- If local polling stalls, resume the existing task and state directory through the CLI route. Never re-run intake or create a new task.
- A user-authored follow-up is the continuation request for that same task. Follow the ordered status → message → optional run → poller sequence above.
- If workspace-folder artifact publishing fails, fail loudly; do not silently fall back to Lakehouse Files.
- Report row counts and mutation counts as the literal `count()` / SQL output captured in the messages stream.
- Treat tokens, tenant details, workspace IDs, and lakehouse IDs as sensitive operational data.

## References

- [URL parsing](references/url-parsing.md) — optional URL intake and Fabric URL validation
- [Operational intake questionnaire](references/intake-questionnaire.md) — task types, recommendations card, Questions 1-8, skip logic, rendered handoff
- [Authentication and route construction](references/auth-and-routing.md) — authentication flow and task base URL
- [Task lifecycle](references/task-lifecycle.md) — task/message/run endpoints, statuses, response shapes
- [Task state and audit](references/task-state.md) — durable intake, messages, artifacts, and recovery context
- [Spawning the recovery poller](references/dashboard-poller.md) — headless poller, token refresh, retry, resume, cleanup
- [Environment routing](references/environment-routing.md) — Fabric environment and API host selection
- [Python helper runtime](references/python-helper-runtime.md) — reuse existing `uv`, virtual, Conda, or system Python without installing packages
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
