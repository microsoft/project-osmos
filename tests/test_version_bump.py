from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build import check_version_bump


def manifest(version: str) -> dict[str, object]:
    return {
        "metadata": {"version": version},
        "plugins": [{"name": "project-osmos", "version": version}],
    }


class VersionBumpTests(unittest.TestCase):
    def test_version_skip_is_rejected_by_default(self) -> None:
        issues = check_version_bump.check_version_bump(manifest("0.4.12"), manifest("0.4.16"))
        self.assertEqual(
            [check_version_bump.ISSUE_INVALID_INCREMENT] * 2,
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_is_allowed_for_catch_up_publication(self) -> None:
        issues = check_version_bump.check_version_bump(
            manifest("0.4.12"), manifest("0.4.16"), allow_version_skip=True,
        )
        self.assertEqual([], issues)

    def test_sole_plugin_rename_preserves_version_protection(self):
        for allow_skip in (False, True):
            for version, expected in (
                ("1.0.0", check_version_bump.ISSUE_UNCHANGED),
                ("0.9.0", check_version_bump.ISSUE_ROLLBACK),
                ("1.0.3", None if allow_skip else check_version_bump.ISSUE_INVALID_INCREMENT),
                ("1.0.1", None),
            ):
                with self.subTest(allow_skip=allow_skip, version=version):
                    base = manifest("1.0.0")
                    current = manifest("1.0.1")
                    current["plugins"][0].update(name="renamed", version=version)
                    issues = check_version_bump.check_version_bump(
                        base, current, allow_version_skip=allow_skip,
                    )
                    self.assertEqual([] if expected is None else [expected],
                                     [kind for kind, _ in issues])

    def test_version_skip_override_still_rejects_rollback(self) -> None:
        issues = check_version_bump.check_version_bump(
            manifest("0.4.16"), manifest("0.4.12"), allow_version_skip=True,
        )
        self.assertEqual(
            [check_version_bump.ISSUE_ROLLBACK] * 2,
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_override_still_rejects_unversioned_content_changes(self) -> None:
        base = manifest("0.4.16")
        base["plugins"][0]["skills"] = ["./components/route-helper"]
        issues = check_version_bump.check_version_bump(
            base, copy.deepcopy(base), changed_paths={"components/route-helper/SKILL.md"},
            allow_version_skip=True,
        )
        self.assertEqual(
            [check_version_bump.ISSUE_UNCHANGED] * 2,
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_override_still_rejects_preview_major(self) -> None:
        with mock.patch.object(check_version_bump, "PREVIEW_RELEASE", True):
            issues = check_version_bump.check_version_bump(
                manifest("0.4.16"), manifest("1.0.0"), allow_version_skip=True,
            )
        self.assertEqual(
            [check_version_bump.ISSUE_PREVIEW_MAJOR] * 2,
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_override_still_rejects_malformed_versions(self) -> None:
        with self.assertRaisesRegex(
            check_version_bump.VersionBumpError,
            "current marketplace metadata.version must use MAJOR.MINOR.PATCH semver",
        ):
            check_version_bump.check_version_bump(
                manifest("0.4.16"), manifest("invalid"), allow_version_skip=True,
            )

    def test_independent_plugin_changes(self):
        base = {
            "metadata": {"version": "1.0.0"},
            "plugins": [
                {"name": "project-osmos", "version": "1.0.0", "source": "./",
                 "skills": ["./components/route-helper"], "hooks": "./hooks.json"},
                {"name": "companion", "version": "1.0.0", "source": "./extensions/companion",
                 "skills": ["./components/companion"]},
            ],
        }
        for changed, owner in (
            ("extensions/companion/components/companion/SKILL.md", 1),
            ("extensions/companion/new-helper.py", 1),
            ("components/route-helper/references/guide.md", 0),
            ("hooks.json", 0),
            ("README.md", 0),
            ("CONTRIBUTING.md", 0),
        ):
            with self.subTest(changed=changed):
                current = copy.deepcopy(base)
                current["metadata"]["version"] = "1.0.1"
                issues = check_version_bump.check_version_bump(base, current, changed_paths={changed})
                self.assertEqual(1, len(issues))
                self.assertIn(base["plugins"][owner]["name"], issues[0][1])
                current["plugins"][owner]["version"] = "1.0.1"
                self.assertEqual([], check_version_bump.check_version_bump(
                    base, current, changed_paths={changed},
                ))
                current["metadata"]["version"] = "1.0.0"
                self.assertEqual([check_version_bump.ISSUE_UNCHANGED], [
                    kind for kind, _ in check_version_bump.check_version_bump(
                        base, current, changed_paths={changed},
                    )
                ])
        self.assertEqual([], check_version_bump.check_version_bump(
            base, copy.deepcopy(base), changed_paths={"tests/test_something.py", "build/tool.py"},
        ))
        current = copy.deepcopy(base)
        current["plugins"][1]["description"] = "Changed package configuration"
        self.assertEqual(2, len(check_version_bump.check_version_bump(base, current)))
        current = copy.deepcopy(base)
        current["plugins"][1]["version"] = "0.9.0"
        self.assertIn(check_version_bump.ISSUE_ROLLBACK, [
            kind for kind, _ in check_version_bump.check_version_bump(base, current)
        ])

    def test_marketplace_only_change_does_not_bump_plugins(self):
        base = manifest("1.0.0")
        current = copy.deepcopy(base)
        current["metadata"]["description"] = "Updated catalog"
        self.assertEqual(1, len(check_version_bump.check_version_bump(base, current)))
        current["metadata"]["version"] = "1.0.1"
        self.assertEqual([], check_version_bump.check_version_bump(base, current))


    def test_new_plugin_and_removed_plugin_require_catalog_bump(self):
        base = manifest("1.0.0")
        current = copy.deepcopy(base)
        current["plugins"].append({"name": "companion", "version": "1.0.0"})
        self.assertEqual(1, len(check_version_bump.check_version_bump(base, current)))
        current["metadata"]["version"] = "1.0.1"
        self.assertEqual([], check_version_bump.check_version_bump(base, current))
        removed = copy.deepcopy(current)
        removed["metadata"]["version"] = "1.0.2"
        removed["plugins"].pop()
        self.assertEqual([], check_version_bump.check_version_bump(current, removed))

    def test_git_changes_include_deletions_renames_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(["git", "-C", temporary, *args], text=True).strip()
            git("init", "-q")
            git("config", "user.name", "Version test")
            git("config", "user.email", "test@example.invalid")
            (root / "old.txt").write_text("old")
            git("add", "old.txt")
            git("commit", "-qm", "Fixture")
            (root / "old.txt").rename(root / "new.txt")
            with mock.patch.object(check_version_bump, "REPO_ROOT", root):
                self.assertEqual({"old.txt", "new.txt"}, check_version_bump.changed_files("HEAD"))

    def test_client_specific_configuration_is_assigned_to_its_plugin(self):
        base = manifest("1.0.0")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / ".claude-plugin/marketplace.json"
            path.parent.mkdir()
            current = copy.deepcopy(base)
            current["plugins"][0]["hooks"] = {"SessionStart": []}
            path.write_text(json.dumps(current))
            with mock.patch.object(check_version_bump, "REPO_ROOT", root), mock.patch.object(
                check_version_bump, "load_base_manifest", return_value=base,
            ):
                self.assertEqual({"project-osmos"}, check_version_bump.changed_client_plugins(
                    "HEAD", {".claude-plugin/marketplace.json"},
                ))

    def test_cli_enforces_bumps_without_workflow_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                subprocess.run(["git", "-C", temporary, *args], check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.name", "Version test")
            git("config", "user.email", "test@example.invalid")
            script = root / "build/check_version_bump.py"
            script.parent.mkdir()
            script.write_text(Path(check_version_bump.__file__).read_text(encoding="utf-8"))
            current = manifest("1.0.0")
            current["plugins"][0]["skills"] = ["./components/route-helper"]
            for path in (".github/plugin/marketplace.json", ".claude-plugin/marketplace.json",
                         ".agents/plugins/marketplace.json"):
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(current))
            skill = root / "components/route-helper/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("Before")
            git("add", ".")
            git("commit", "-qm", "Fixture")
            skill.write_text("After")
            command = [sys.executable, "-S", str(script), "--base-ref", "HEAD"]
            for flags in ([], ["--warning-only"]):
                with self.subTest(flags=flags):
                    result = subprocess.run([*command, *flags], capture_output=True, text=True)
                    self.assertEqual(1, result.returncode)
                    self.assertIn("metadata.version must be incremented", result.stderr)
                    self.assertIn("plugins['project-osmos'].version must be incremented", result.stderr)
            current["metadata"]["version"] = "1.0.1"
            current["plugins"][0]["version"] = "1.0.1"
            for path in (".github/plugin/marketplace.json", ".claude-plugin/marketplace.json",
                         ".agents/plugins/marketplace.json"):
                (root / path).write_text(json.dumps(current))
            result = subprocess.run(
                command, capture_output=True, text=True,
                env={**os.environ, "GITHUB_OUTPUT": str(root / "absent/output")},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("Marketplace and changed-plugin version checks passed.", result.stdout)

    @unittest.skipIf(os.name == "nt", "Workflow runs in Bash on Ubuntu")
    def test_workflow_only_allows_same_repository_publication_branches(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/version-bump-check.yml").read_text()
        block = workflow.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
        script = "\n".join(line.removeprefix("          ") for line in block.splitlines())
        script = 'python() { printf "%s\\n" "$@"; }\n' + script
        for head_repo, base, head, allowed in (
            ("upstream/project", "main", "automation/publish-project-osmos-release", True),
            ("upstream/project", "public", "automation/sync-public-from-main-release", True),
            ("fork/project", "main", "automation/publish-project-osmos-release", False),
            ("upstream/project", "main", "feature/fix", False),
            ("upstream/project", "public", "automation/publish-project-osmos-release", False),
            ("upstream/project", "main", "automation/sync-public-from-main-release", False),
        ):
            with self.subTest(head_repo=head_repo, base=base, head=head):
                result = subprocess.run(
                    ["bash", "-eu", "-c", script],
                    env={
                        **os.environ, "BASE_REF": "base", "CURRENT_REPOSITORY": "upstream/project",
                        "HEAD_REPOSITORY": head_repo, "BASE_BRANCH": base, "HEAD_REF": head,
                    },
                    text=True, capture_output=True, check=True,
                )
                self.assertEqual(allowed, "--allow-version-skip" in result.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
