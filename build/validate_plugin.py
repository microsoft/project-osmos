# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Validate the Copilot CLI marketplace manifest for project-osmos."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE_JSON = REPO_ROOT / ".github" / "plugin" / "marketplace.json"
CLAUDE_MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
MARKETPLACE_SYMLINKS = [
    (CLAUDE_MARKETPLACE_JSON, "../.github/plugin/marketplace.json"),
]
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
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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

    if hooks_config.get("version") != 1:
        issues.append(f"{prefix} version must be 1")

    hooks = hooks_config.get("hooks")
    if not isinstance(hooks, dict):
        issues.append(f"{prefix} hooks must be an object")
        return issues

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

    for shell_key in ("bash", "powershell"):
        command = hook.get(shell_key)
        if not isinstance(command, str) or not command:
            issues.append(f"{prefix} sessionStart hook must define {shell_key}")
            continue
        for required in (
            "PROJECT_OSMOS_UPDATE_HOOK",
            "copilot plugin marketplace update project-osmos",
            "copilot plugin update project-osmos@project-osmos",
        ):
            if required not in command:
                issues.append(f"{prefix} {shell_key} command must include {required!r}")

    claude_session_start = hooks.get("SessionStart")
    if not isinstance(claude_session_start, list) or len(claude_session_start) != 1:
        issues.append(f"{prefix} hooks.SessionStart must contain exactly one Claude Code auto-update hook")
        return issues

    claude_group = claude_session_start[0]
    if not isinstance(claude_group, dict):
        issues.append(f"{prefix} SessionStart hook group must be an object")
        return issues
    if claude_group.get("matcher") != "startup|resume|clear":
        issues.append(f"{prefix} SessionStart matcher must be startup|resume|clear")

    claude_hooks = claude_group.get("hooks")
    if not isinstance(claude_hooks, list) or len(claude_hooks) != 1:
        issues.append(f"{prefix} SessionStart hook group must contain exactly one command hook")
        return issues

    claude_hook = claude_hooks[0]
    if not isinstance(claude_hook, dict):
        issues.append(f"{prefix} SessionStart command hook must be an object")
        return issues
    if claude_hook.get("type") != "command":
        issues.append(f"{prefix} SessionStart command hook type must be command")
    if claude_hook.get("timeout") != 120:
        issues.append(f"{prefix} SessionStart command hook timeout must be 120")

    claude_command = claude_hook.get("command")
    if not isinstance(claude_command, str) or not claude_command:
        issues.append(f"{prefix} SessionStart command hook must define command")
        return issues
    for required in (
        "PROJECT_OSMOS_CLAUDE_UPDATE_HOOK",
        "claude plugin marketplace update project-osmos",
        "claude plugin update project-osmos@project-osmos",
    ):
        if required not in claude_command:
            issues.append(f"{prefix} SessionStart command must include {required!r}")

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
    return issues


def validate_marketplace_symlinks() -> list[str]:
    issues: list[str] = []
    for path, expected_target in MARKETPLACE_SYMLINKS:
        if not path.is_symlink():
            issues.append(f"{format_repo_path(path)} must be a symlink to {expected_target}")
            continue
        actual_target = path.readlink()
        if actual_target.as_posix() != expected_target:
            issues.append(
                f"{format_repo_path(path)} must point to {expected_target}, not {actual_target.as_posix()}"
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="accepted for compatibility; validation is always read-only")
    parser.parse_args()

    if not MARKETPLACE_JSON.exists():
        print("No marketplace manifest found at .github/plugin/marketplace.json", file=sys.stderr)
        return 1
    if not CLAUDE_MARKETPLACE_JSON.exists():
        print("No Claude marketplace manifest found at .claude-plugin/marketplace.json", file=sys.stderr)
        return 1
    try:
        marketplace = load_json(MARKETPLACE_JSON)
    except (OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    issues = validate_marketplace(marketplace)
    issues.extend(validate_marketplace_symlinks())
    issues.extend(validate_forbidden_paths())

    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1

    print("Marketplace manifests are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
