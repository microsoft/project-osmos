# Project Osmos for Microsoft Fabric

Install Project Osmos in GitHub Copilot CLI, Codex, or Claude Code and use natural language to run data engineering tasks in Microsoft Fabric.

## What Project Osmos does

Project Osmos is an AI-powered data engineering workflow for Fabric. Describe the outcome you want, and the agent can:

- Explore data in your Lakehouse.
- Create and test Fabric notebooks.
- Clean, join, aggregate, and validate data.
- Create or update Delta tables and workspace artifacts.
- Run longer workflows while you monitor progress from a local dashboard.

The plugin on your machine starts and monitors the task. Agent reasoning, Spark execution, and OneLake data access run inside Microsoft Fabric.

## Before you start

You need:

| Requirement | Details |
| --- | --- |
| Project Osmos access | Project Osmos must be enabled for your account. |
| Fabric workspace | The workspace must be assigned to Fabric capacity and contain a Lakehouse. |
| Workspace permissions | Contributor or higher on the target workspace. |
| Fabric Copilot setting | **User can use Copilot and other features powered by Azure OpenAI** must be enabled for the tenant or workspace. |
| Azure CLI | Install Azure CLI and sign in with an identity that can access the workspace. Guest users may optionally supply the workspace's resource tenant ID. |
| Python 3.11+ | Use an existing compatible interpreter. Project Osmos helpers use only the standard library and do not install packages or modify local environments. |
| AI coding client | Install GitHub Copilot CLI, Codex, or Claude Code. |

## Install

Use the commands for your preferred client.

### GitHub Copilot CLI

```bash
copilot plugin marketplace add microsoft/project-osmos
copilot plugin install project-osmos@project-osmos
```

### Codex

```bash
codex plugin marketplace add microsoft/project-osmos
codex plugin add project-osmos@project-osmos
```

### Claude Code

```bash
claude plugin marketplace add microsoft/project-osmos
claude plugin install project-osmos@project-osmos
```

Restart the client after the first installation. In Claude Code, you can instead run `/reload-plugins`.

## Create your first task

### 1. Sign in to Azure

Sign in with the Azure CLI:

```bash
az login --allow-no-subscriptions
```

Verify Power BI token acquisition without printing the token:

```bash
az account get-access-token \
  --resource https://analysis.windows.net/powerbi/api \
  --output none
```

Project Osmos uses this current session by default. If a guest or cross-tenant session cannot access the workspace, provide the Microsoft Entra tenant ID that owns the workspace when prompted.

### 2. Start your client

| Client | Command |
| --- | --- |
| GitHub Copilot CLI | `copilot` |
| Codex | `codex` |
| Claude Code | `claude` |

### 3. Ask for Project Osmos

Use a prompt that names Project Osmos and describes the goal:

```text
Use Project Osmos to transform data in my Fabric lakehouse.
```

The skill asks for:

1. Which Fabric workspace and Lakehouse to use. It can reuse Microsoft Fabric page context, resolve names with Microsoft Fabric Skills, or parse a Lakehouse browser URL.
2. Your complete data engineering instruction.
3. Any optional constraints or additional context.
4. Review of the recommended operating settings before the run starts.

The skill asks for a resource tenant ID only if the current Azure CLI session cannot access the workspace.

### 4. Describe the outcome

Be specific about source data, transformations, outputs, and validation. For example:

```text
Load Orders and Customers from my lakehouse, remove Orders rows with missing
customer IDs, join the tables, calculate monthly revenue by customer segment,
write the result as a Delta table, and validate the source and output row counts.
```

Another example:

```text
Create a sales sample CSV in a workspace folder, create a matching Delta table,
and build and test a notebook that ingests the CSV into the table.
```

### 5. Monitor the run

Project Osmos runs in Fabric and complex tasks can take up to a day. After the task starts, the plugin displays the task ID and creates a local dashboard under:

```text
./.dataprojects/<task-id>/
```

You can close the terminal or shut down your machine without stopping the Fabric task. When you return, reopen your client and ask it to resume the existing Project Osmos task. Include the task ID if the client cannot identify the previous run.

## Update the plugin

Copilot CLI and Claude Code include a startup update check. Codex updates configured Git marketplaces in the background. You can also update manually.

### GitHub Copilot CLI

```bash
copilot plugin marketplace update project-osmos
copilot plugin update project-osmos@project-osmos
```

### Codex

```bash
codex plugin marketplace upgrade project-osmos
```

### Claude Code

```bash
claude plugin marketplace update project-osmos
claude plugin update project-osmos@project-osmos
```

Restart the client after an update so the new skill content is loaded.

## Troubleshooting

| Issue | What to do |
| --- | --- |
| Project Osmos is not available after installation | Restart the client, then run the install commands again and check for an installation error. |
| Azure authentication fails | Run `az login --allow-no-subscriptions` and retry. For a guest or cross-tenant workspace, sign in with `az login --tenant <resource-tenant-id> --allow-no-subscriptions`. |
| Workspace or capacity lookup fails | Confirm the Lakehouse URL is correct, the workspace has Fabric capacity, and your Azure identity can access it. |
| Lakehouse lookup or task creation fails | Confirm the workspace and Lakehouse names, choose the intended match if discovery is ambiguous, or provide the complete Lakehouse browser URL. |
| The task runs for a long time | Spark startup, planning, and complex transformations can take time. Continue monitoring the existing task rather than creating another one. |
| The local dashboard or poller stopped | Resume the existing task with the same task ID. Do not restart intake or create a duplicate task. |
| The installed plugin appears outdated | Run the manual update command for your client, restart it, and retry. |

## Repository contents

- `skills/project-osmos/` contains the Project Osmos skill and operational references.
- The client marketplace manifests make the same plugin available to Copilot CLI, Codex, and Claude Code.
- Copilot CLI uses `hooks.json` for its startup update check; Claude Code carries its native startup hook in its marketplace manifest.
- `.github/workflows/` validates and publishes the plugin.

Maintainer and contribution details are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Privacy, support, and security

- Read [PRIVACY.md](PRIVACY.md) for privacy and telemetry information.
- For general feedback, contact [project-osmos@microsoft.com](mailto:project-osmos@microsoft.com).
- Report security vulnerabilities through [SECURITY.md](SECURITY.md).
- Do not post tokens, tenant details, workspace or Lakehouse IDs, certificate material, or private data in issues or logs.

This project is licensed under the [MIT License](LICENSE) and follows the [Microsoft Open Source Code of Conduct](CODE_OF_CONDUCT.md).

Microsoft, Microsoft Fabric, GitHub Copilot, OneLake, and Azure may be trademarks or registered trademarks of Microsoft Corporation. See the [Microsoft Trademark and Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks).
