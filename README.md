# Project Osmos for Microsoft Fabric

Project Osmos is a GitHub Copilot CLI plugin for Microsoft Fabric data engineering workflows. It helps start and monitor long-running Project Osmos tasks from your local CLI while the work runs in Fabric.

## Install

Install from the public marketplace repository:

```bash
copilot plugin marketplace add microsoft/project-osmos
copilot plugin install project-osmos@project-osmos
```

In Copilot CLI, you can use the equivalent slash commands:

```text
/plugin marketplace add microsoft/project-osmos
/plugin install project-osmos@project-osmos
```

If Claude Code plugin support is enabled for this repository, install with:

```bash
claude plugin marketplace add microsoft/project-osmos
claude plugin install project-osmos@project-osmos
```

## Use Project Osmos

1. Sign in with Azure CLI:

   ```bash
   az login
   ```

2. Start Copilot CLI:

   ```bash
   copilot
   ```

3. Ask Copilot to use Project Osmos:

   ```text
   Use Project Osmos to transform data in my Fabric lakehouse.
   ```

The skill asks for the Fabric Lakehouse browser URL, confirms the workspace and Lakehouse IDs parsed from that URL, asks for the task instruction, collects operational constraints, starts the Project Osmos run, and creates a local dashboard under `./.dataprojects/<task-id>/`.

## Writing a good instruction

Describe the desired outcome in one complete instruction. Include:

- **Data sources**: table names, file paths, or OneLake locations.
- **Transformations**: cleaning, joins, filters, aggregations, or enrichment.
- **Outputs**: new or updated tables, notebooks, files, or summaries.
- **Validations**: row counts, null checks, schema checks, or business rules.

Example:

```text
Load the Orders table from my lakehouse, remove rows with missing customer IDs, join to Customers, write a monthly segment revenue Delta table, and validate row counts plus negative revenue checks.
```

## Auto-update behavior

This plugin includes a session-start hook that refreshes the `project-osmos` marketplace catalog and updates `project-osmos@project-osmos` for future sessions. The hook is fail-open: update failures do not block normal CLI use.

## Repository contents

| Path | Purpose |
| --- | --- |
| `.github/plugin/marketplace.json` | Public marketplace manifest for `project-osmos@project-osmos`. |
| `.claude-plugin/marketplace.json` | Optional Claude Code marketplace symlink to the same manifest. |
| `hooks.json` | Plugin auto-update hooks. |
| `skills/project-osmos/` | Project Osmos skill, references, helper scripts, and dashboard asset. |
| `build/validate_plugin.py` | Public manifest validator used by release workflows. |
| `build/check_version_bump.py` | Public version bump checker used by pull request workflows. |

## Support and security

Use GitHub issues in this repository for product feedback and non-security bugs if issues are enabled. Do not include tokens, credentials, tenant-private data, workspace-private data, or customer data in issues, pull requests, logs, or screenshots.

Report security vulnerabilities through Microsoft Security Response Center: https://msrc.microsoft.com/create-report.
