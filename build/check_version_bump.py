# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Require release and changed-plugin version increments relative to a base Git ref."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MARKETPLACE_PATH = Path(".github/plugin/marketplace.json")
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PREVIEW_RELEASE = False
ISSUE_UNCHANGED = "unchanged"
ISSUE_ROLLBACK = "rollback"
ISSUE_PREVIEW_MAJOR = "preview_major"
ISSUE_INVALID_INCREMENT = "invalid_increment"
Issue = tuple[str, str]


class VersionBumpError(ValueError):
    """Raised when manifest versions cannot be compared."""


def load_json_text(content: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise VersionBumpError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise VersionBumpError(f"{label} must be a JSON object")
    return value


def load_current_manifest(path: Path) -> dict[str, Any]:
    try:
        return load_json_text(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise VersionBumpError(f"Unable to read {path}: {exc}") from exc


def load_base_manifest(base_ref: str, marketplace_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{marketplace_path.as_posix()}"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise VersionBumpError(f"Unable to read {marketplace_path} from {base_ref}{detail}")
    return load_json_text(result.stdout, f"{base_ref}:{marketplace_path}")


def parse_semver(value: Any, label: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not SEMVER_PATTERN.fullmatch(value):
        raise VersionBumpError(f"{label} must use MAJOR.MINOR.PATCH semver")
    return tuple(int(part) for part in value.split("."))


def metadata_version(manifest: dict[str, Any], label: str) -> tuple[int, int, int]:
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise VersionBumpError(f"{label} metadata must be an object")
    return parse_semver(metadata.get("version"), f"{label} metadata.version")


def plugin_versions(manifest: dict[str, Any], label: str) -> dict[str, tuple[int, int, int]]:
    plugins = manifest.get("plugins")
    if not isinstance(plugins, list):
        raise VersionBumpError(f"{label} plugins must be an array")

    versions: dict[str, tuple[int, int, int]] = {}
    for index, plugin in enumerate(plugins):
        if not isinstance(plugin, dict):
            raise VersionBumpError(f"{label} plugins[{index}] must be an object")
        name = plugin.get("name")
        if not isinstance(name, str) or not name:
            raise VersionBumpError(f"{label} plugins[{index}].name must be a non-empty string")
        if name in versions:
            raise VersionBumpError(f"{label} has duplicate plugin name {name!r}")
        versions[name] = parse_semver(plugin.get("version"), f"{label} plugins[{name!r}].version")
    return versions


def format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def is_preview_blocked_version(version: tuple[int, int, int]) -> bool:
    return PREVIEW_RELEASE and version[0] > 0


def next_increment_versions(base_version: tuple[int, int, int]) -> tuple[tuple[int, int, int], ...]:
    major, minor, patch = base_version
    candidates = (
        (major, minor, patch + 1),
        (major, minor + 1, 0),
        (major + 1, 0, 0),
    )
    return tuple(version for version in candidates if not is_preview_blocked_version(version))


def format_next_increment_versions(base_version: tuple[int, int, int]) -> str:
    return ", ".join(format_version(version) for version in next_increment_versions(base_version))


def require_incremented(
    current_version: tuple[int, int, int],
    base_version: tuple[int, int, int],
    label: str,
    issues: list[Issue],
    *,
    allow_version_skip: bool = False,
) -> None:
    if is_preview_blocked_version(current_version):
        issues.append(
            (
                ISSUE_PREVIEW_MAJOR,
                f"{label} must stay below 1.0.0 while PREVIEW_RELEASE is true; "
                f"current is {format_version(current_version)}",
            )
        )
        return

    if current_version == base_version:
        issues.append(
            (
                ISSUE_UNCHANGED,
                f"{label} must be incremented: base and current are both {format_version(base_version)}",
            )
        )
        return

    if current_version < base_version:
        issues.append(
            (
                ISSUE_ROLLBACK,
                f"{label} must not roll back: base is {format_version(base_version)}, "
                f"current is {format_version(current_version)}",
            )
        )
        return

    if allow_version_skip:
        return

    allowed_versions = next_increment_versions(base_version)
    if current_version not in allowed_versions:
        issues.append(
            (
                ISSUE_INVALID_INCREMENT,
                f"{label} must be the next patch, minor, or major version after "
                f"{format_version(base_version)}; allowed versions are "
                f"{format_next_increment_versions(base_version)}, current is {format_version(current_version)}",
            )
        )


def resolve_current_plugin_version(
    plugin_name: str,
    base_plugins: dict[str, tuple[int, int, int]],
    current_plugins: dict[str, tuple[int, int, int]],
) -> tuple[str | None, tuple[int, int, int] | None]:
    current_version = current_plugins.get(plugin_name)
    if current_version is not None:
        return plugin_name, current_version
    if len(base_plugins) == 1 and len(current_plugins) == 1:
        return next(iter(current_plugins.items()))
    return None, None


def changed_files(base_ref: str) -> set[str]:
    paths: set[str] = set()
    for command in (
        ["git", "diff", "--name-only", "--no-renames", "-z", base_ref, "--"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, check=False)
        if result.returncode:
            raise VersionBumpError(result.stderr.decode("utf-8", errors="replace").strip())
        paths.update(os.fsdecode(path) for path in result.stdout.split(b"\0") if path)
    return paths


def plugin_configuration(plugin: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plugin.items() if key != "version"}


def changed_client_plugins(base_ref: str, paths: set[str]) -> set[str]:
    changed: set[str] = set()
    for filename in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
        if filename not in paths:
            continue
        base = load_base_manifest(base_ref, Path(filename))
        current = load_current_manifest(REPO_ROOT / filename)
        plugin_versions(base, filename)
        plugin_versions(current, filename)
        before = {plugin["name"]: plugin_configuration(plugin) for plugin in base["plugins"]}
        for plugin in current["plugins"]:
            if before.get(plugin["name"]) != plugin_configuration(plugin):
                changed.add(plugin["name"])
    return changed


def plugin_owns_path(plugin: dict[str, Any], filename: str) -> bool:
    source = PurePosixPath(plugin.get("source", "./"))
    if source != PurePosixPath("."):
        return PurePosixPath(filename).is_relative_to(source)
    # The root package owns its declared assets, not nested plugin or tooling trees.
    roots = ["README.md", "CONTRIBUTING.md", "LICENSE", "NOTICE.md", "PRIVACY.md", "SECURITY.md", "CODE_OF_CONDUCT.md"]
    for key in ("skills", "agents"):
        roots.extend(value for value in plugin.get(key, []) if isinstance(value, str))
    for key in ("hooks", "mcpServers"):
        if isinstance(plugin.get(key), str):
            roots.append(plugin[key])
    return any(PurePosixPath(filename).is_relative_to(PurePosixPath(root)) for root in roots)


def check_version_bump(
    base_manifest: dict[str, Any],
    current_manifest: dict[str, Any],
    *,
    changed_paths: set[str] | None = None,
    client_changed_plugins: set[str] | None = None,
    allow_version_skip: bool = False,
) -> list[Issue]:
    issues: list[Issue] = []
    changed_paths = changed_paths or set()
    client_changed_plugins = client_changed_plugins or set()
    base_metadata = metadata_version(base_manifest, "base marketplace")
    current_metadata = metadata_version(current_manifest, "current marketplace")
    base_plugins = plugin_versions(base_manifest, "base marketplace")
    current_plugins = plugin_versions(current_manifest, "current marketplace")
    before = {plugin["name"]: plugin for plugin in base_manifest["plugins"]}
    after = {plugin["name"]: plugin for plugin in current_manifest["plugins"]}
    changed = set(client_changed_plugins)
    for name, plugin in after.items():
        previous = before.get(name)
        if previous is None or plugin_configuration(plugin) != plugin_configuration(previous):
            changed.add(name)
        if any(plugin_owns_path(plugin, path) or
               (previous is not None and plugin_owns_path(previous, path)) for path in changed_paths):
            changed.add(name)

    if base_manifest != current_manifest or changed:
        require_incremented(
            current_metadata, base_metadata, "metadata.version", issues,
            allow_version_skip=allow_version_skip,
        )
    matched_plugins: set[str] = set()
    for plugin_name, base_version in base_plugins.items():
        current_name, current_version = resolve_current_plugin_version(plugin_name, base_plugins, current_plugins)
        if current_name is None or current_version is None:
            continue
        matched_plugins.add(current_name)
        if current_version != base_version or current_name in changed:
            label = (f"plugins[{plugin_name!r}].version" if current_name == plugin_name
                     else f"plugins[{plugin_name!r} -> {current_name!r}].version")
            require_incremented(
                current_version, base_version, label, issues,
                allow_version_skip=allow_version_skip,
            )
    for name in current_plugins.keys() - matched_plugins:
        if is_preview_blocked_version(current_plugins[name]):
            issues.append((ISSUE_PREVIEW_MAJOR, f"plugins[{name!r}] must stay below 1.0.0 while PREVIEW_RELEASE is true"))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="Git ref for the PR base branch, for example origin/main")
    parser.add_argument(
        "--marketplace-path",
        type=Path,
        default=DEFAULT_MARKETPLACE_PATH,
        help="Path to the marketplace manifest relative to the repository root",
    )
    parser.add_argument(
        "--warning-only",
        action="store_true",
        help="deprecated compatibility flag; publishable changes without version bumps still fail",
    )
    parser.add_argument(
        "--allow-version-skip",
        action="store_true",
        help="allow any forward semver increment for a controlled catch-up publication",
    )
    args = parser.parse_args()

    marketplace_path = args.marketplace_path
    if marketplace_path.is_absolute():
        try:
            marketplace_path = marketplace_path.relative_to(REPO_ROOT)
        except ValueError as exc:
            raise SystemExit(f"--marketplace-path must stay inside the repository: {args.marketplace_path}") from exc

    try:
        base_manifest = load_base_manifest(args.base_ref, marketplace_path)
        current_manifest = load_current_manifest(REPO_ROOT / marketplace_path)
        paths = changed_files(args.base_ref)
        issues = check_version_bump(
            base_manifest, current_manifest, allow_version_skip=args.allow_version_skip,
            changed_paths=paths, client_changed_plugins=changed_client_plugins(args.base_ref, paths),
        )
    except VersionBumpError as exc:
        print(exc, file=sys.stderr)
        return 1

    if issues:
        for _, message in issues:
            print(message, file=sys.stderr)
        return 1

    print("Marketplace and changed-plugin version checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
