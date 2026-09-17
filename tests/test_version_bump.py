from __future__ import annotations

import os
import subprocess
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

    def test_version_skip_override_still_rejects_rollback(self) -> None:
        issues = check_version_bump.check_version_bump(
            manifest("0.4.16"), manifest("0.4.12"), allow_version_skip=True,
        )
        self.assertEqual(
            [check_version_bump.ISSUE_ROLLBACK] * 2,
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_override_still_rejects_unchanged_versions(self) -> None:
        issues = check_version_bump.check_version_bump(
            manifest("0.4.16"), manifest("0.4.16"), allow_version_skip=True,
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
