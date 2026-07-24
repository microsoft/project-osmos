# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Validate Project Osmos marketplace manifests and client-native hooks."""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE_JSON = REPO_ROOT / ".github" / "plugin" / "marketplace.json"
CLAUDE_MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MARKETPLACE_JSON = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
FRONTMATTER_FIELD_PATTERN = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
UNSAFE_PLAIN_SCALAR_PATTERN = re.compile(r":(?:[ \t]|$)")
BLOCK_SCALAR_INDICATORS = {"|", "|-", "|+", ">", ">-", ">+"}
FORBIDDEN_PATHS = [
    REPO_ROOT / "plugin.json",
    REPO_ROOT / "package.json",
    REPO_ROOT / "plugins",
    REPO_ROOT / ".github" / "plugin" / "plugin.json",
    REPO_ROOT / ".claude-plugin" / "plugin.json",
    REPO_ROOT / ".codex-plugin",
    REPO_ROOT / "hooks" / "hooks.json",
]
COPILOT_BASH_COMMAND = (
    'if [ "${PROJECT_OSMOS_UPDATE_HOOK:-}" = "1" ]; then exit 0; fi; '
    "PROJECT_OSMOS_UPDATE_HOOK=1 copilot plugin marketplace update project-osmos >/dev/null 2>&1; "
    "PROJECT_OSMOS_UPDATE_HOOK=1 copilot plugin update project-osmos@project-osmos >/dev/null 2>&1 || true"
)
COPILOT_POWERSHELL_COMMAND = (
    "if ($env:PROJECT_OSMOS_UPDATE_HOOK -eq '1') { exit 0 }; "
    "$env:PROJECT_OSMOS_UPDATE_HOOK = '1'; "
    "copilot plugin marketplace update project-osmos *> $null; "
    "copilot plugin update project-osmos@project-osmos *> $null; exit 0"
)
CLAUDE_UPDATE_COMMAND = (
    'if [ "${PROJECT_OSMOS_CLAUDE_UPDATE_HOOK:-}" = "1" ]; then exit 0; fi; '
    "command -v claude >/dev/null 2>&1 || exit 0; "
    "PROJECT_OSMOS_CLAUDE_UPDATE_HOOK=1 claude plugin marketplace update project-osmos >/dev/null 2>&1 || true; "
    "PROJECT_OSMOS_CLAUDE_UPDATE_HOOK=1 claude plugin update project-osmos@project-osmos >/dev/null 2>&1 || true"
)
CLAUDE_HOOKS = {
    "SessionStart": [
        {
            "matcher": "startup|resume|clear",
            "hooks": [
                {
                    "type": "command",
                    "command": CLAUDE_UPDATE_COMMAND,
                    "timeout": 120,
                    "statusMessage": "Updating Project Osmos plugin",
                }
            ],
        }
    ]
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def first_plugin_entry(manifest: Any) -> dict[str, Any] | None:
    if not isinstance(manifest, dict):
        return None
    plugins = manifest.get("plugins")
    if not isinstance(plugins, list) or not plugins or not isinstance(plugins[0], dict):
        return None
    return plugins[0]


def string_list(
    value: Any,
    issues: list[str],
    name: str,
    key: str,
    *,
    allow_single: bool = False,
) -> list[str]:
    if value is None:
        return []
    if allow_single and isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value

    expected = "a string or list of strings" if allow_single else "a list of strings"
    issues.append(f"[{name}] {key} must be {expected}")
    return []


def resolve_repo_path(root: Path, ref: str) -> Path | None:
    ref_path = Path(ref[2:] if ref.startswith("./") else ref)
    if ref_path.is_absolute():
        return None

    resolved_path = (root / ref_path).resolve()
    try:
        resolved_path.relative_to(REPO_ROOT)
    except ValueError:
        return None
    return resolved_path


def format_repo_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def first_symlink_component(path: Path) -> Path | None:
    current = REPO_ROOT
    for part in path.relative_to(REPO_ROOT).parts:
        current /= part
        if current.is_symlink():
            return current
    return None


def validate_manifest_paths() -> list[str]:
    issues: list[str] = []
    for label, path in (
        ("Copilot", MARKETPLACE_JSON),
        ("Claude", CLAUDE_MARKETPLACE_JSON),
        ("Codex", CODEX_MARKETPLACE_JSON),
    ):
        symlink_component = first_symlink_component(path)
        if symlink_component is not None:
            issues.append(
                f"{format_repo_path(path)} must be a regular JSON file with no symlink path components; "
                f"{format_repo_path(symlink_component)} is a symlink and can become plain text on Windows"
            )
        elif not path.exists():
            issues.append(f"missing {label} marketplace manifest: {format_repo_path(path)}")
        elif not path.is_file():
            issues.append(f"{format_repo_path(path)} must be a regular JSON file")
    return issues


def validate_skill_frontmatter(skill_path: Path) -> list[str]:
    label = format_repo_path(skill_path)
    try:
        lines = skill_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"{label} must be readable: {exc}"]

    if not lines or lines[0] != "---":
        return [f"{label} must start with YAML frontmatter"]

    try:
        frontmatter_end = lines.index("---", 1)
    except ValueError:
        return [f"{label} must close YAML frontmatter with ---"]

    for line_number, line in enumerate(lines[1:frontmatter_end], start=2):
        match = FRONTMATTER_FIELD_PATTERN.fullmatch(line)
        if not match or match.group(1) != "description":
            continue

        value = match.group(2).strip()
        if not value:
            return [f"{label} line {line_number}: frontmatter description must not be empty"]
        if value in BLOCK_SCALAR_INDICATORS or value.startswith(("'", '"')):
            return []
        if UNSAFE_PLAIN_SCALAR_PATTERN.search(value):
            return [
                f"{label} line {line_number}: frontmatter description contains a colon followed by "
                "whitespace or the end of the value in an unquoted YAML scalar; quote the value or use a block scalar"
            ]
        return []

    return [f"{label} must define a frontmatter description"]


def validate_plugin_entry(marketplace_name: str, plugin: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    name = plugin.get("name", "project-osmos")

    for key in ("name", "description", "version", "source", "repository", "license", "keywords", "skills", "hooks"):
        if key not in plugin:
            issues.append(f"[{marketplace_name}/{name}] missing required plugin field: {key}")

    if plugin.get("name") != "project-osmos":
        issues.append(f"[{marketplace_name}/{name}] plugin name must be project-osmos")

    version = plugin.get("version")
    if not isinstance(version, str) or not version:
        issues.append(f"[{marketplace_name}/{name}] version must be a non-empty string")
    elif not SEMVER_PATTERN.fullmatch(version):
        issues.append(f"[{marketplace_name}/{name}] version must use MAJOR.MINOR.PATCH semver")

    source = plugin.get("source")
    if source != "./":
        issues.append(f"[{marketplace_name}/{name}] source must be ./")
    else:
        source_path = resolve_repo_path(REPO_ROOT, source)
        if source_path != REPO_ROOT:
            issues.append(f"[{marketplace_name}/{name}] source must resolve to the repository root")

    string_list(plugin.get("keywords"), issues, f"{marketplace_name}/{name}", "keywords")

    for skill_ref in string_list(plugin.get("skills"), issues, f"{marketplace_name}/{name}", "skills", allow_single=True):
        skill_dir = resolve_repo_path(REPO_ROOT, skill_ref)
        if skill_dir is None:
            issues.append(f"[{marketplace_name}/{name}] skill path must stay within repository: {skill_ref}")
            continue
        if not skill_dir.is_dir():
            issues.append(f"[{marketplace_name}/{name}] missing skill directory: {format_repo_path(skill_dir)}")
        elif not (skill_dir / "SKILL.md").is_file():
            issues.append(f"[{marketplace_name}/{name}] missing SKILL.md: {format_repo_path(skill_dir / 'SKILL.md')}")
        else:
            issues.extend(validate_skill_frontmatter(skill_dir / "SKILL.md"))

    hooks_ref = plugin.get("hooks")
    if hooks_ref != "./hooks.json":
        issues.append(f"[{marketplace_name}/{name}] hooks must be ./hooks.json")
    else:
        hooks_path = resolve_repo_path(REPO_ROOT, hooks_ref)
        if hooks_path is None:
            issues.append(f"[{marketplace_name}/{name}] hooks path must stay within repository: {hooks_ref}")
        elif not hooks_path.is_file():
            issues.append(f"[{marketplace_name}/{name}] missing hooks file: {format_repo_path(hooks_path)}")
        else:
            issues.extend(validate_hooks_file(marketplace_name, name, hooks_path))

    agents = plugin.get("agents")
    if agents is not None and not isinstance(agents, list):
        issues.append(f"[{marketplace_name}/{name}] agents must be an array")

    mcp_servers = plugin.get("mcpServers")
    if mcp_servers is not None and not isinstance(mcp_servers, dict):
        issues.append(f"[{marketplace_name}/{name}] mcpServers must be an object")

    return issues


def validate_hooks_file(marketplace_name: str, plugin_name: str, hooks_path: Path) -> list[str]:
    issues: list[str] = []
    prefix = f"[{marketplace_name}/{plugin_name}] {format_repo_path(hooks_path)}"

    try:
        hooks_config = load_json(hooks_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{prefix} must be valid JSON: {exc}"]

    if not isinstance(hooks_config, dict):
        return [f"{prefix} must contain a JSON object"]

    if set(hooks_config) != {"version", "hooks"}:
        issues.append(f"{prefix} top level must contain only version and hooks")
    if hooks_config.get("version") != 1:
        issues.append(f"{prefix} version must be 1")

    hooks = hooks_config.get("hooks")
    if not isinstance(hooks, dict):
        issues.append(f"{prefix} hooks must be an object")
        return issues
    if set(hooks) != {"sessionStart"}:
        issues.append(f"{prefix} hooks must contain only the Copilot sessionStart event")

    session_start = hooks.get("sessionStart")
    if not isinstance(session_start, list) or len(session_start) != 1:
        issues.append(f"{prefix} hooks.sessionStart must contain exactly one auto-update hook")
        return issues

    hook = session_start[0]
    if not isinstance(hook, dict):
        issues.append(f"{prefix} sessionStart hook must be an object")
        return issues

    if hook.get("type") != "command":
        issues.append(f"{prefix} sessionStart hook type must be command")
    if hook.get("cwd") != ".":
        issues.append(f"{prefix} sessionStart hook cwd must be .")
    if hook.get("timeoutSec") != 120:
        issues.append(f"{prefix} sessionStart hook timeoutSec must be 120")
    if set(hook) != {"type", "bash", "powershell", "cwd", "timeoutSec", "comment"}:
        issues.append(f"{prefix} sessionStart hook fields do not match the Copilot command schema")
    if hook.get("comment") != "Updating Project Osmos plugin":
        issues.append(f"{prefix} sessionStart hook comment must be Updating Project Osmos plugin")

    if hook.get("bash") != COPILOT_BASH_COMMAND:
        issues.append(f"{prefix} bash command must match the Copilot auto-update command")
    if hook.get("powershell") != COPILOT_POWERSHELL_COMMAND:
        issues.append(f"{prefix} powershell command must match the Copilot auto-update command")

    return issues


def validate_marketplace(marketplace: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    marketplace_name = marketplace.get("name", "project-osmos")

    for key in ("name", "owner", "metadata", "plugins"):
        if key not in marketplace:
            issues.append(f"[{marketplace_name}] missing required marketplace field: {key}")

    if marketplace.get("name") != "project-osmos":
        issues.append(f"[{marketplace_name}] marketplace name must be project-osmos")

    owner = marketplace.get("owner")
    if not isinstance(owner, dict) or not isinstance(owner.get("name"), str) or not owner.get("name"):
        issues.append(f"[{marketplace_name}] owner.name must be a non-empty string")

    metadata = marketplace.get("metadata")
    metadata_version = None
    if not isinstance(metadata, dict):
        issues.append(f"[{marketplace_name}] metadata must be an object")
    else:
        metadata_version = metadata.get("version")
        if not isinstance(metadata_version, str) or not SEMVER_PATTERN.fullmatch(metadata_version):
            issues.append(f"[{marketplace_name}] metadata.version must use MAJOR.MINOR.PATCH semver")

    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1:
        issues.append(f"[{marketplace_name}] plugins must include exactly one project-osmos entry")
        return issues

    entry = plugins[0]
    if not isinstance(entry, dict):
        issues.append(f"[{marketplace_name}] plugin entry must be an object")
        return issues

    issues.extend(validate_plugin_entry(marketplace_name, entry))

    if metadata_version is not None and entry.get("version") != metadata_version:
        issues.append(f"[{marketplace_name}] metadata.version must match plugin entry version")

    return issues


def validate_forbidden_paths() -> list[str]:
    issues: list[str] = []
    for path in FORBIDDEN_PATHS:
        if path.exists():
            issues.append(f"remove unsupported plugin artifact: {format_repo_path(path)}")
    for path in REPO_ROOT.rglob("plugin.json"):
        if ".git" not in path.parts and path not in FORBIDDEN_PATHS:
            issues.append(f"remove unsupported plugin artifact: {format_repo_path(path)}")
    return issues


def validate_native_marketplace_manifests(marketplace: dict[str, Any]) -> list[str]:
    issues: list[str] = []

    claude_marketplace = copy.deepcopy(marketplace)
    claude_plugin = first_plugin_entry(claude_marketplace)
    if claude_plugin is not None:
        claude_plugin["hooks"] = CLAUDE_HOOKS

    codex_marketplace = copy.deepcopy(marketplace)
    codex_plugin = first_plugin_entry(codex_marketplace)
    if codex_plugin is not None:
        codex_plugin.pop("hooks", None)

    for label, path, expected in (
        ("Claude", CLAUDE_MARKETPLACE_JSON, claude_marketplace),
        ("Codex", CODEX_MARKETPLACE_JSON, codex_marketplace),
    ):
        try:
            actual = load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"{format_repo_path(path)} must be valid JSON: {exc}")
            continue
        actual_plugin = first_plugin_entry(actual)
        actual_hooks = actual_plugin.get("hooks") if actual_plugin is not None else None
        if label == "Claude":
            if isinstance(actual_hooks, str):
                issues.append(
                    f"{format_repo_path(path)} plugins[0].hooks must be an inline Claude hooks object, "
                    "not a file path"
                )
            elif actual_hooks != CLAUDE_HOOKS:
                issues.append(
                    f"{format_repo_path(path)} plugins[0].hooks must exactly match the native Claude "
                    "SessionStart auto-update hook"
                )
        if label == "Codex":
            if actual_plugin is not None and "hooks" in actual_plugin:
                issues.append(
                    f"{format_repo_path(path)} must not define plugins[0].hooks or reference hooks.json; "
                    "Codex does not support this repository's Copilot hooks.json schema and updates Git "
                    "marketplaces natively"
                )
        if actual != expected:
            issues.append(
                f"{format_repo_path(path)} must stay synchronized with .github/plugin/marketplace.json"
                + (
                    " after removing only plugins[0].hooks for Codex"
                    if label == "Codex"
                    else " after replacing only plugins[0].hooks with the native Claude inline hook"
                )
            )

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify all marketplace manifests are regular files and satisfy the synchronization contract",
    )
    parser.parse_args()

    path_issues = validate_manifest_paths()
    if path_issues:
        for issue in path_issues:
            print(issue, file=sys.stderr)
        return 1
    try:
        marketplace = load_json(MARKETPLACE_JSON)
    except (OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not isinstance(marketplace, dict):
        print(f"{format_repo_path(MARKETPLACE_JSON)} must contain a JSON object", file=sys.stderr)
        return 1

    issues = validate_marketplace(marketplace)
    issues.extend(validate_native_marketplace_manifests(marketplace))
    issues.extend(validate_forbidden_paths())

    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1

    print("Marketplace manifests are valid and synchronized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
