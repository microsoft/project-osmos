---
name: project-osmos-migration
description: 'Migrate the retired standalone Project Osmos plugin to Microsoft Skills for Fabric. Triggers: migrate my old standalone Osmos skill; install the replacement for project-osmos@project-osmos; why did my standalone Osmos skill disappear? Use only for package migration or replacement installation, not ordinary Osmos data tasks, task status, or continuation.'
---

# Migrate the standalone Osmos plugin

Use the `project-osmos` skill in
[Microsoft Skills for Fabric](https://github.com/microsoft/skills-for-fabric)
for task execution. Install `fabric-skills@fabric-collection` when needed.
Read the [README installation and migration steps](../../README.md#move-to-sff)
before package changes, including its [active-task precautions](../../README.md#existing-tasks-and-legacy-recovery).

## Must

1. Inspect the actual client inventory, marketplace source, enabled state,
   installation scope, and loaded skill paths. For Copilot, use
   `copilot plugin list` and `copilot skill list --json`. For other clients,
   use their plugin inventory and skill selector. A matching plugin name or an
   empty cache alone proves neither provenance nor absence.
2. Verify SFF comes from `microsoft/skills-for-fabric`. For a local source,
   verify its Git remote and the actual loaded path. Reuse a verified enabled
   SFF bundle or alias that already provides `project-osmos`; do not install
   duplicates. On unknown or conflicting provenance, stop and explain it.
   Never overwrite a registration or silently switch distributions.
3. If SFF is missing, offer installation using the matching client below.
   Ask before installing, updating, enabling, or removing packages. Match the
   user's scope. If declined, blocked, or awaiting reload, preserve the original
   request and task context and stop. Never claim installation finished a data task.
4. Restart or reload after approved changes. Verify the enabled `project-osmos`
   skill's provider and loaded path belong to SFF, not this plugin or a leftover
   standalone copy. Report installation or discovery failures without secrets.
5. Preserve `.dataprojects`, original task IDs, routes, and state paths.
   Before updating or removing an old package, follow the guide's active
   recovery precautions. Defer changes while recovery is active unless the user
   approves a controlled handoff. Never recreate or cancel tasks, delete state,
   or assume SFF reads the old state schema.

## Install after consent

Run only the commands for the user's existing client and intended scope.
Do not install a different client as part of migration.

| Client | Register marketplace | Install plugin |
| --- | --- | --- |
| Copilot CLI | `copilot plugin marketplace add microsoft/skills-for-fabric` | `copilot plugin install fabric-skills@fabric-collection` |
| Claude Code | `claude plugin marketplace add microsoft/skills-for-fabric` | `claude plugin install fabric-skills@fabric-collection` |
| Codex | `codex plugin marketplace add microsoft/skills-for-fabric` | `codex plugin add fabric-skills@fabric-collection` |

If already registered or installed, use the migration guide's update or enable
path instead of registering again. An alias's update uses its actual installed
ID. Only offer removal of this public plugin after SFF is verified usable and
legacy recovery is safe. Removal needs separate consent.

## Prefer

- Report the verified SFF source, skill path, and any remaining setup blocker.
- Keep the user's original request for SFF's own intake and authorization gates.
- Leave this migration plugin installed if removal is unnecessary or declined.

## Avoid

- Running Fabric authentication, provisioning, data tasks, status calls, or
  continuation from this skill. Normal Osmos requests belong to SFF.
- Falling back to the retired standalone execution skill or its helpers.
- Automatic installation, package removal, shared-marketplace removal, or
  changing client update preferences.
- Treating migration consent as permission to execute a data task.

## Examples

- "Migrate my old standalone Osmos skill." Inspect inventory and provenance,
  check active recovery, then propose the required package changes for consent.
- "Install the replacement for project-osmos@project-osmos." Verify whether SFF
  already supplies its skill; if missing, offer the Microsoft bundle above.
- "Why did my standalone Osmos skill disappear?" Explain the 1.0.0 retirement
  and verify SFF discovery. Preserve existing task context; do not start a task.
