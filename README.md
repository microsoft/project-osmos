# Project Osmos for Fabric - Copilot plugin

Agent plugin to use **Project Osmos** in Microsoft Fabric from your favorite AI coding assistant.

This repository ships the `project-osmos` domain skill plus session-start hooks that keep the installed plugin fresh in GitHub Copilot CLI and Claude Code.

## What Project Osmos does

Project Osmos is Fabric's AI-powered data engineering workflow. You describe a data engineering task in natural language (for example, *"join Orders with Customers and compute monthly revenue"*, or set up a medallion architecture that flows data from **bronze → silver → gold**) and an AI agent in Microsoft Fabric autonomously:

- Spins up a Spark session in your workspace.
- Figures out how to meet the objectives you lay out in the task.
- Creates/updates tables.
- Creates/updates and tests notebooks that it generates to transform data.


The `project-osmos` skill starts a Project Osmos task from Copilot on your local machine. It creates a SparkCore task, posts your instruction as a message, triggers `POST /run`, then spawns a local dashboard poller to track progress. The heavy lifting — LLM reasoning, Spark execution on a Spark cluster, OneLake reads and writes — happens server-side inside Fabric.

In short, the local skill is a thin control plane that drives the remote agent lifecycle; the agent itself runs entirely within Fabric's compute and storage boundary.

## Audience

Users with Project Osmos access who want to automate Fabric data engineering workflows.


## Prerequisites

| Requirement | How to get it |
| --- | --- |
| GitHub Copilot CLI | macOS: `brew install copilot-cli` &nbsp;·&nbsp; cross-platform: `npm install -g @github/copilot` |
| Azure CLI | macOS: `brew install azure-cli` &nbsp;·&nbsp; other platforms: see the [official install docs](https://learn.microsoft.com/cli/azure/install-azure-cli). |
| Fabric workspace with capacity | A workspace that contains a lakehouse. Open the Lakehouse in Fabric and copy the full browser URL. |
| Fabric Copilot setting | The Fabric setting **"User can use Copilot and other features powered by Azure OpenAI"** must be enabled for either the tenant or the target workspace. |
| Permissions | Contributor or higher on the target workspace. |

## Install

Choose the command style that matches where you want to install the plugin. GitHub README files do not render true interactive tabs, so these sections use collapsible groups.

<details open>
<summary><strong>Copilot CLI Install Terminal</strong></summary>

Run these commands from your shell:

```bash
copilot plugin marketplace add microsoft/project-osmos
copilot plugin install project-osmos@project-osmos
```

</details>

<details>
<summary><strong>Codex Install Terminal</strong></summary>

Run these commands from your shell:

```bash
codex plugin marketplace add microsoft/project-osmos
codex plugin add project-osmos@project-osmos
```

</details>

<details>
<summary><strong>Claude Code Install Terminal</strong></summary>

Run these commands from your shell:

```bash
claude plugin marketplace add microsoft/project-osmos
claude plugin install project-osmos@project-osmos
```

If Claude Code is already running, restart it or run `/reload-plugins`.

</details>

The marketplace manifest lives at `.github/plugin/marketplace.json`; its single plugin entry uses `source: "./"`, references canonical skills under `./skills/`, and ships `hooks.json` for automatic session-start updates. `.claude-plugin/marketplace.json` is a symlink to the same manifest for Claude Code plugin discovery.

After installation, the `project-osmos` skill is available to the client you installed it into and responds to natural-language prompts that mention Project Osmos, Fabric data engineering, Spark Transform Notebook, or OneLake ETL.


For contribution expectations, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Create your first Project Osmos task

### 1. Sign in to Azure

Open your favorite terminal and sign in to Azure. The skill uses your Azure CLI identity to call Fabric APIs.

```bash
az login
```

Confirm the expected tenant and account:

```bash
az account show
```

### 2. Launch GitHub Copilot CLI

```bash
copilot
```

### 3. Ask Copilot to start Project Osmos

Type a prompt inside Copilot CLI that mentions Project Osmos. The skill will ask for the Fabric Lakehouse browser URL first, parse the workspace ID and default Spark-session Lakehouse ID, then ask for your task instructions.

Copilot CLI prompt:

```text
Use Project Osmos to transform data in my Fabric lakehouse.
```

Provide a clear, full data engineering instruction. A simple example:

```text
create a table called "Test-Sales-Data" with fields for CustomerID, TransactionID, Amount and Date. Then create a folder in the workspace called sales-sheets and put a sample CSV file in it with data that aligns with Test-Sales-Data. Finally create a notebook that ingests data from the CSV file to the table.
```

### 4. Review operational intake

The skill classifies the task, recommends operational constraints, and asks you to accept or adjust them before it starts the run. Those constraints are appended to the instruction sent to the remote agent.

### 5. Wait for completion — or walk away

Project Osmos executes inside Fabric. Depending on task complexity and current load this can take **up to a day**. The skill prints a run card with the task ID and local dashboard path, then spawns a detached poller that writes `./.dataprojects/<task-id>/state.json`, `state.js`, and `poller.log`. You can safely close the terminal or shut your machine down — the task keeps running in Fabric.

When you come back, resume the same conversation:

```bash
copilot --resume
```

## What the skill always asks for

1. Fabric Lakehouse browser URL.
2. Full data engineering task instruction.
3. Optional extra guidance from the "Anything else I should know?" prompt.

Another example instruction you can adapt:

```text
Use Project Osmos to load the Orders table from my lakehouse, remove rows with missing customer IDs, join to Customers, write a monthly segment revenue Delta table, and validate row counts.
```

## Common issues

| Issue | What to do |
| --- | --- |
| Skill is not listed in `/skills` | Skill discovery may run before a first-time install completes. Re-run the marketplace install step from [Install](#install), then restart Copilot CLI. |
| Azure CLI token check fails | Run `az login`, confirm the expected tenant and account with `az account show`, then retry. |
| Capacity lookup fails | Confirm the workspace is assigned to a Fabric capacity and your Azure CLI identity can read workspace metadata. |
| Workspace lookup fails | Confirm the Lakehouse browser URL is correct and that your Azure CLI identity has access to the workspace. |
| Workspace has no capacity | Use a workspace already assigned to a Fabric capacity before running Project Osmos. |
| Lakehouse lookup or task creation fails | Confirm the Lakehouse URL points to a lakehouse in the same workspace being resolved. |
| `POST /run` returns an instruction-related error | The task was created without the instruction. Ask Copilot to recreate or update the task with the full instruction field before running. |
| Task remains running for several minutes | Keep polling. Spark session acquisition and agent planning can take several minutes. |
| Error: *Run failed while executing statements on the Spark session. Please retry.* | The dashboard poller auto-retries this documented transient on the same task ID. If the poller has exited, ask Copilot to read `terminal.json` before respawning it. |

## Privacy and telemetry

See [PRIVACY.md](PRIVACY.md) for the standalone privacy and telemetry notice.


## Updating the plugin

The installed plugin ships a Copilot CLI `sessionStart` hook that refreshes the `project-osmos` marketplace catalog and runs plugin update at the start of Copilot CLI sessions:

```text
copilot plugin marketplace update project-osmos
copilot plugin update project-osmos@project-osmos
```

The hook is fail-open: update failures are ignored so they do not block normal Copilot sessions after the hook returns. Updates affect subsequent sessions because skill content is loaded before the session-start hook runs. To update manually, run `/plugin update project-osmos@project-osmos` in Copilot CLI or `copilot plugin update project-osmos@project-osmos` from a shell.

For Claude Code, the same `hooks.json` also ships a `SessionStart` hook for `startup`, `resume`, and `clear` events. It runs `claude plugin marketplace update project-osmos` and `claude plugin update project-osmos@project-osmos`; Claude Code plugin updates may require restarting Claude Code or running `/reload-plugins`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `.github/plugin/marketplace.json` | Canonical Copilot CLI marketplace manifest for `project-osmos@project-osmos`. |
| `.claude-plugin/marketplace.json` | Symlink to the canonical manifest for Claude marketplace discovery. |
| `hooks.json` | Plugin hook configuration that refreshes the marketplace catalog and updates `project-osmos` at session start for Copilot CLI and Claude Code. |
| `skills/` | Canonical Agent Skills source referenced by the marketplace plugin entry as `./skills/<skill-name>`. |
| `build/validate_plugin.py` | Validates marketplace metadata, plugin references, and accidental nested plugin files or trees. |
| `build/check_version_bump.py` | Validates PR marketplace and plugin versions against the base branch. |
| `.github/workflows/` | Public plugin validation, version, release, and safety-review automation. |


The repository root is the marketplace repository and plugin source. Keep plugin composition in `.github/plugin/marketplace.json`, keep `.claude-plugin/marketplace.json` as a symlink to it, keep Copilot CLI and Claude Code plugin hooks in `hooks.json`, and keep skill source under `skills/`.

`build/validate_plugin.py` is a read-only repository maintenance helper, not a runtime dependency for users. It verifies the marketplace manifests, checks referenced skills exist, and fails if root `plugin.json`, `package.json`, or unsupported nested plugin manifests or plugin trees are reintroduced.


## Legal notices

This project follows the [Microsoft Open Source Code of Conduct](CODE_OF_CONDUCT.md). Contributions are subject to the Microsoft Contributor License Agreement.

Microsoft, Microsoft Fabric, GitHub Copilot, OneLake, Azure, and other Microsoft products and services may be trademarks or registered trademarks of Microsoft Corporation in the United States and other countries. This project does not grant rights to use Microsoft trademarks.

Public releases or changes involving privacy, telemetry, machine learning, AI, models, datasets, or service-side behavior may require additional approval before publication.


## Contributing and security


See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Do not include bearer or service tokens, tenant secrets, certificate material, workspace-private data, or personal paths in issues, PRs, logs, or skill content.
