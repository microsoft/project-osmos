---
name: project-osmos
description: >
  Project Osmos for Microsoft Fabric. Use for complex, long-running
  Fabric/OneLake data engineering workflows where the agent should write and run
  Spark code, transform or modify tables, and produce notebooks or outputs with
  a long-running autonomous Project Osmos task. Triggers: "Project Osmos",
  "Fabric data engineering", "Spark Transform Notebook", "OneLake ETL",
  "Fabric Project Osmos".
---

# Project Osmos for Microsoft Fabric

Use this skill when the user wants Project Osmos to solve a Fabric/OneLake workflow end-to-end: inspect data, write and run Spark, transform or modify tables, produce notebooks or outputs, and keep working through a long-running Fabric task.

## Operating contract

This file is the lean routing contract. Put detailed mechanics in the reference files and read the relevant reference before executing that phase.

1. **Lakehouse URL first.** Ask only for the Fabric Lakehouse browser URL. Parse workspace ID and default Spark-session Lakehouse ID with [URL parsing](references/url-parsing.md). Never ask for workspace or Lakehouse IDs as separate startup fields.
2. **Confirm before API calls.** Echo both parsed GUIDs in full. If the URL lacks a Lakehouse ID or uses an unsupported host, ask for a corrected Lakehouse URL.
3. **Resolve names.** Before seeding the dashboard, resolve `workspace_name`, `capacity_id`, and `lakehouse_name` using [Authentication and route construction](references/auth-and-routing.md). Surface lookup failures; do not fall back to `(unknown)` or substitute GUIDs.
4. **Collect the outcome.** After URL confirmation, ask for the task instructions, then one optional "Anything else I should know?" prompt. Keep the user's complete outcome and guidance verbatim.
5. **Run intake.** Classify the task and render the recommendations card from [Operational intake questionnaire](references/intake-questionnaire.md). Append the rendered `## Operational constraints` block verbatim before task creation and before the initial user message.
6. **Route and authenticate.** Resolve the public Project Osmos task endpoint and authorization flow with [Authentication and route construction](references/auth-and-routing.md).
7. **Create and run one task.** Use one generated task ID for create, message, run, retries, and follow-ups. Follow [Task lifecycle](references/task-lifecycle.md) for endpoint shapes and response handling.
8. **Seed the dashboard.** Create `./.dataprojects/<task-id>/`, copy `assets/dashboard.html`, and seed `state.js` / `state.json` exactly from [Status dashboard](references/dashboard.md). Use snake_case; never persist tokens, authorization headers, tenant credentials, or camelCase API keys.
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
11. **Mediate follow-ups.** If the user sends a message for the running task, post it with `scripts/post-user-message.py`; do not invent a raw request that omits author metadata.
12. **Report from state.** On status questions or final summaries, read `terminal.json` first when present, then `state.json`. Quote `reason`, `last_error_message`, retry counts, token-refresh counts, and identifiers from state instead of guessing.

## Non-negotiables

- The Lakehouse ID is only the Spark session's default lakehouse. It is not automatically a source, destination, or scope boundary. Label it "Default lakehouse for the Spark session".
- Poll messages for progress; task status alone is not enough.
- Let the poller own message de-duplication, `tool` / `system` filtering, token refresh, terminal markers, and documented transient retry handling.
- If polling stalls, resume the existing task and dashboard directory. Do not re-run intake, create a new task, or overwrite the dashboard.
- If workspace-folder artifact publishing fails, fail loudly; do not silently fall back to Lakehouse Files.
- Report row counts and mutation counts as the literal `count()` / SQL output captured in the messages stream.
- Treat tokens, tenant details, workspace IDs, and Lakehouse IDs as sensitive operational data.

## References

- [URL parsing](references/url-parsing.md) — URL-first intake
- [Operational intake questionnaire](references/intake-questionnaire.md) — task types, recommendations card, skip logic, rendered preamble
- [Authentication and route construction](references/auth-and-routing.md) — authorization flow and task base URL
- [Task lifecycle](references/task-lifecycle.md) — task/message/run endpoints, statuses, response shapes
- [Status dashboard](references/dashboard.md) — `./.dataprojects/<task-id>/` layout and `window.__STATE` schema
- [Spawning the dashboard poller daemon](references/dashboard-poller.md) — detached poller, token refresh, retry, resume, cleanup
- [Troubleshooting](references/troubleshooting.md) — auth/poller recovery and retryable transients

## Writing good instructions

Ask for one outcome-oriented instruction. It should include:

- **Data sources** — table names, file paths, OneLake resource URIs.
- **Transformations** — cleaning, joins, aggregations, filters.
- **Outputs** — new tables, notebooks, or summaries.
- **Validations** — row counts, null checks, data type checks.

Example:

```text
Load the incremental Orders table from OneLake, remove rows with null customer_id, join with the Customers dimension on customer_id, compute monthly order value by customer segment, save the result as a Delta table named monthly_segment_revenue, and validate row counts plus negative revenue checks.
```
