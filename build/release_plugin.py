# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Publish one immutable repository release listing each plugin's own version."""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def run(root: Path, *args: str) -> str:
    return subprocess.check_output(args, cwd=root, text=True, encoding="utf-8").strip()


def tag_commit(root: Path, tag: str) -> str | None:
    ref = f"refs/tags/{tag}"
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", ref],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode == 2:
        return None
    if result.returncode:
        raise RuntimeError(f"Cannot inspect release tag: {result.stderr.strip()}")
    run(root, "git", "fetch", "--no-tags", "origin", f"{ref}:{ref}")
    return run(root, "git", "rev-parse", f"{ref}^{{commit}}")


def release_notes(manifest: dict, migration_note: str) -> str:
    lines = ["## Included plugins", "", "| Plugin | Version |", "| --- | --- |"]
    lines.extend(f"| `{plugin['name']}` | `{plugin['version']}` |" for plugin in manifest["plugins"])
    return "\n".join([*lines, "", migration_note, ""])


def publish(root: Path, commit: str, migration_note: str) -> None:
    commit = run(root, "git", "rev-parse", f"{commit}^{{commit}}")
    if run(root, "git", "rev-parse", "HEAD") != commit:
        raise RuntimeError("Release commit must match the checked-out HEAD")
    if run(root, "git", "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Release checkout must be clean")
    manifest = json.loads((root / ".github/plugin/marketplace.json").read_text(encoding="utf-8"))
    tag = f"v{manifest['metadata']['version']}"
    target = tag_commit(root, tag)
    if target is not None and target != commit:
        raise RuntimeError(f"Release tag {tag} points to {target}, expected {commit}; use a new version")
    releases = run(root, "gh", "api", "--paginate", "repos/{owner}/{repo}/releases", "--jq", ".[].tag_name")
    if tag in releases.splitlines():
        if target is None:
            raise RuntimeError(f"Release {tag} exists without its Git tag")
        print(f"Release {tag} already exists at {commit}")
        return
    if target is None:
        run(root, "git", "tag", tag, commit)
        run(root, "git", "push", "origin", f"refs/tags/{tag}")
    with tempfile.TemporaryDirectory(prefix="plugin-release-") as temporary:
        notes = Path(temporary) / "notes.md"
        notes.write_text(release_notes(manifest, migration_note), encoding="utf-8")
        run(root, "gh", "release", "create", tag, "--verify-tag", "--title", tag, "--notes-file", str(notes))
    if tag_commit(root, tag) != commit:
        raise RuntimeError(f"Release tag {tag} no longer points to {commit}")
    print(f"Published {tag} at {commit}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--migration-note", required=True)
    args = parser.parse_args()
    publish(Path(__file__).resolve().parents[1], args.commit, args.migration_note)


if __name__ == "__main__":
    main()
