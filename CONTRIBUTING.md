# Contributing

Project Osmos is published as an open source package so users can inspect the plugin, install it, and file issues. This repository is not currently seeking broad external feature contributions. If you want to propose a change, open an issue first so maintainers can confirm whether the contribution is appropriate for the project.

## Code of Conduct and CLA

This project follows the [Microsoft Open Source Code of Conduct](CODE_OF_CONDUCT.md).

Most contributions require agreement to the Microsoft Contributor License Agreement (CLA). When you submit a pull request, a CLA bot will determine whether you need to provide a CLA and decorate the PR appropriately.

## Contribution expectations

- Do not include secrets, tokens, tenant-private details, certificate material, workspace-private data, or personal paths in issues, pull requests, logs, or skill content.
- Keep reports focused on public Project Osmos behavior and public documentation.
- Use [SECURITY.md](SECURITY.md) for vulnerability reporting instead of public issues.
- Respect Microsoft trademarks and third-party license notices.

## Marketplace manifest contract

The repository intentionally includes three regular marketplace JSON files because Copilot CLI, Claude Code, and Codex discover different paths:

- `.github/plugin/marketplace.json` is canonical.
- `.claude-plugin/marketplace.json` must match the canonical file after replacing only `plugins[0].hooks` with the native inline Claude `SessionStart` hook.
- `.agents/plugins/marketplace.json` must match the canonical file after removing only `plugins[0].hooks`.

Current Copilot CLI and Codex releases can also discover the Claude marketplace path, but the repository intentionally uses each client's native path instead of depending on that cross-client fallback. Copilot references its root `hooks.json`. Claude uses an inline native hook because Claude Code 2.1.218 rejects file-path and array hook forms in marketplace entries. Codex omits hooks because it upgrades configured Git marketplaces and refreshes installed plugin caches at startup. Do not add Claude's default `hooks/hooks.json`, which Codex can auto-discover, or reference the Copilot hook file from Codex.

Copilot CLI 1.0.74-3 accepts marketplace `hooks` as either a string or an object, so an inline object validates and installs without an error. Runtime inspection and sentinel testing show that plugin hook registration receives the installed plugin directory, not the inline object, and discovers physical hook files instead. Keep Copilot's `"hooks": "./hooks.json"` reference until a later release explicitly supports inline marketplace-hook execution and passes an end-to-end sentinel test.

Do not replace the mirrors with Git symlinks. On machines without Git symlink support, including some Windows configurations, Git can check out a symlink as a plain-text target path; clients then try to parse that text as JSON and installation fails. Pull requests into `main` and `public` run `python build/validate_plugin.py --check` to enforce regular files and synchronization.

