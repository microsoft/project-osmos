#!/usr/bin/env python3
"""Ensure marketplace and plugin versions increment relative to a base Git ref."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MARKETPLACE_PATH = Path(".github/plugin/marketplace.json")
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PUBLISH_WARNING = (
    "Marketplace and plugin versions were not bumped. Unless .github/plugin/marketplace.json "
    "metadata.version and plugin entry version are bumped, the package and changes will not be published."
)
PREVIEW_RELEASE = True
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


def workflow_escape(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def workflow_escape_property(value: str) -> str:
    return workflow_escape(value).replace(":", "%3A").replace(",", "%2C")


def print_warning(message: str) -> None:
    warning_file = workflow_escape_property(DEFAULT_MARKETPLACE_PATH.as_posix())
    title = workflow_escape_property("Marketplace version not bumped")
    print(f"::warning file={warning_file},line=1,title={title}::{workflow_escape(message)}")


def write_step_summary(message: str, issues: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    details = "\n".join(f"- {issue}" for issue in issues)
    summary = (
        "## Marketplace version not bumped\n\n"
        f"{message}\n\n"
        "### Comparison details\n\n"
        f"{details}\n"
    )
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(summary)


def write_github_outputs(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return

    with open(output_path, "a", encoding="utf-8") as handle:
        for name, value in values.items():
            handle.write(f"{name}={value.replace(chr(10), ' ')}\n")


def require_incremented(
    current_version: tuple[int, int, int],
    base_version: tuple[int, int, int],
    label: str,
    issues: list[Issue],
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


def check_version_bump(base_manifest: dict[str, Any], current_manifest: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []

    base_metadata = metadata_version(base_manifest, "base marketplace")
    current_metadata = metadata_version(current_manifest, "current marketplace")
    require_incremented(current_metadata, base_metadata, "metadata.version", issues)

    base_plugins = plugin_versions(base_manifest, "base marketplace")
    current_plugins = plugin_versions(current_manifest, "current marketplace")

    for plugin_name, base_version in base_plugins.items():
        current_plugin_name, current_version = resolve_current_plugin_version(plugin_name, base_plugins, current_plugins)
        if current_version is None:
            issues.append(
                (
                    ISSUE_INVALID_INCREMENT,
                    f"plugin {plugin_name!r} is missing from the current marketplace manifest",
                )
            )
            continue
        if current_plugin_name == plugin_name:
            label = f"plugins[{plugin_name!r}].version"
        else:
            label = f"plugins[{plugin_name!r} -> {current_plugin_name!r}].version"
        require_incremented(current_version, base_version, label, issues)

    return issues


def manifest_versions_unchanged(base_manifest: dict[str, Any], current_manifest: dict[str, Any]) -> bool:
    return (
        metadata_version(base_manifest, "base marketplace") == metadata_version(current_manifest, "current marketplace")
        and plugin_versions(base_manifest, "base marketplace") == plugin_versions(current_manifest, "current marketplace")
    )


def issue_messages(issues: list[Issue]) -> list[str]:
    return [message for _, message in issues]


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
        help="emit a GitHub Actions warning instead of failing when versions were not changed",
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
        issues = check_version_bump(base_manifest, current_manifest)
        versions_unchanged = manifest_versions_unchanged(base_manifest, current_manifest)
    except VersionBumpError as exc:
        print(exc, file=sys.stderr)
        return 1

    if issues:
        messages = issue_messages(issues)
        is_unchanged_warning = args.warning_only and versions_unchanged and all(
            issue_type == ISSUE_UNCHANGED for issue_type, _ in issues
        )
        if is_unchanged_warning:
            message = f"{PUBLISH_WARNING} {'; '.join(messages)}"
            print_warning(message)
            write_step_summary(message, messages)
            write_github_outputs({"version_bumped": "false", "warning_message": message})
            return 0

        for issue in messages:
            print(issue, file=sys.stderr)
        return 1

    if args.warning_only:
        write_github_outputs({"version_bumped": "true", "warning_message": ""})

    print("Marketplace metadata.version and plugin versions were incremented.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
