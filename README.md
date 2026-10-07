# Project Osmos for Microsoft Fabric

Project Osmos is a data engineering agent for Microsoft Fabric. Use natural language
to explore Lakehouse data, build notebooks and run data engineering workflows.

The `project-osmos` skill now comes from
[Skills for Fabric (SFF)](https://github.com/microsoft/skills-for-fabric).
It replaces the standalone execution skill in
[`project-osmos@project-osmos`](https://github.com/microsoft/project-osmos).
The Osmos service is unchanged.


## Move to SFF

Install `fabric-skills@fabric-collection` using your client's commands below.
For new installations, use `microsoft/skills-for-fabric`.
Reuse a verified alias that already supplies `project-osmos`; do not install duplicate bundles.
Wait for permission before installing, updating, enabling or removing packages.
SFF is not installed automatically.

<details>
<summary>Check an existing installation first</summary>

Inspect installed plugins and loaded skills:
Copilot uses `copilot plugin list` and `copilot skill list --json`; Claude uses
`claude plugin list --json` and `claude plugin details <installed-id>`; Codex uses
`codex plugin list --json` and the interactive `/skills` selector.
Verify the marketplace source, enabled state, installation scope and actual loaded skill path.
For a local source, verify its Git remote. Stop before loading, updating, or installing through
an unknown or conflicting same-name marketplace; never silently switch SFF distributions.
If SFF lacks the skill, offer an update; if disabled, offer enabling in its controlling scope.

</details>


| Client | Register SFF marketplace | Install SFF |
| --- | --- | --- |
| Copilot CLI | `copilot plugin marketplace add microsoft/skills-for-fabric` | `copilot plugin install fabric-skills@fabric-collection` |
| Claude Code | `claude plugin marketplace add microsoft/skills-for-fabric` | `claude plugin install fabric-skills@fabric-collection` |
| Codex | `codex plugin marketplace add microsoft/skills-for-fabric` | `codex plugin add fabric-skills@fabric-collection` |

Use your client and existing scope, including Claude's `--scope user|project|local`.
Do not re-register an existing source or bypass organization policy. Restart/reload after changes
and verify `project-osmos` is enabled and loaded from SFF.

Try: `Tell me the names of the tables in this Lakehouse: <Lakehouse URL>.`
SFF handles prerequisites and task authorization. Installation is not data-task completion or permission to run one.
If declined, blocked or awaiting reload, retain the request and task context; report failures without secrets.

## Updating an older installation

Check [active recovery](#existing-tasks-and-legacy-recovery) first. With permission, use the actual ID and scope:

| Client | Refresh marketplace | Update plugin |
| --- | --- | --- |
| Copilot CLI | `copilot plugin marketplace update project-osmos` | `copilot plugin update project-osmos@project-osmos` |
| Claude Code | `claude plugin marketplace update project-osmos` | `claude plugin update project-osmos@project-osmos` |
| Codex | `codex plugin marketplace upgrade project-osmos` | Git marketplace upgrade refreshes the plugin. |

For SFF updates, substitute marketplace `fabric-collection` and `fabric-skills@fabric-collection`,
or the exact installed alias.

<details>
<summary>Local checkouts and automatic updates</summary>

A Git upgrade does not update a local-directory marketplace:
verify its remote/ref, update a clean checkout with `git pull --ff-only`, and rerun its documented build
before client refresh. Stop on dirty/diverged checkout or build failure; do not edit installed caches.
For local Codex SFF, refresh with `codex plugin add fabric-skills@fabric-collection` after rebuilding.

Copilot's root hook and Claude's inline `SessionStart` hook are best-effort; Codex uses native Git updates.
Offline, pinned, disabled-update and copied installs may retain old files; keep the user's update preferences.
Restart/reload and verify only SFF supplies `project-osmos`.
A plugin update does not remove a separately installed or manually copied skill.
Identify its exact loaded path and installation method; obtain consent to remove only that obsolete copy.
Do not delete SFF's skill or unrelated files.

</details>

## Existing tasks and legacy recovery

Keep `.dataprojects`, the original task ID, route, and state path.
Updating/removing the old package can break a live recovery worker's credential refresh.
Ask whether recovery is active and inspect only the supplied task's process/state, not token files.
If active, defer the package change until completion or obtain explicit consent for a controlled handoff
that stops only the verified local worker. Stopping it does not cancel the remote task.
An automatic update may already have replaced the scripts. Through SFF's authorized continuation flow,
verify the same remote task with fresh authentication. Do not assume SFF reads the old state schema.
Do not delete state, recreate/cancel tasks or promise uninterrupted recovery.

## Public package cleanup

Only the public distribution contains the `project-osmos-migration` guidance skill.
Ask it to "migrate my old standalone Osmos skill"; it guides setup, not task execution.
Public users can remove this plugin once SFF is verified usable and legacy recovery is safe:

| Client | Remove public plugin |
| --- | --- |
| Copilot CLI | `copilot plugin uninstall project-osmos@project-osmos` |
| Claude Code | `claude plugin uninstall project-osmos@project-osmos` |
| Codex | `codex plugin remove project-osmos@project-osmos` |

Get separate removal consent and use the actual ID/scope, including direct/path installs.
For Claude removal, use `--keep-data` if supported.
If removal is declined, leave the package unchanged. Do not remove `fabric-skills` or another SFF alias.
Verify SFF remains enabled. Never force-remove a shared marketplace; remove an unused registration only with consent.


## Privacy, support and security

See [PRIVACY.md](PRIVACY.md) for telemetry and [CONTRIBUTING.md](CONTRIBUTING.md) for contributions.
Send feedback to [project-osmos@microsoft.com](mailto:project-osmos@microsoft.com).
Report vulnerabilities through [SECURITY.md](SECURITY.md); never post credentials or tenant/workspace identifiers.
This project uses the [MIT License](LICENSE) and [Microsoft Open Source Code of Conduct](CODE_OF_CONDUCT.md).
Microsoft product names may be trademarks; see the
[Microsoft Trademark and Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks).
