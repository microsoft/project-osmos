from __future__ import annotations

import unittest
from unittest import mock

from build import check_version_bump


def manifest(version: str) -> dict[str, object]:
    return {
        "metadata": {"version": version},
        "plugins": [{"name": "project-osmos", "version": version}],
    }


class VersionBumpTests(unittest.TestCase):
    def test_version_skip_is_rejected_by_default(self) -> None:
        issues = check_version_bump.check_version_bump(
            manifest("0.4.12"),
            manifest("0.4.16"),
        )

        self.assertEqual(
            [
                check_version_bump.ISSUE_INVALID_INCREMENT,
                check_version_bump.ISSUE_INVALID_INCREMENT,
            ],
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_is_allowed_for_catch_up_publication(self) -> None:
        issues = check_version_bump.check_version_bump(
            manifest("0.4.12"),
            manifest("0.4.16"),
            allow_version_skip=True,
        )

        self.assertEqual([], issues)

    def test_version_skip_override_still_rejects_rollback(self) -> None:
        issues = check_version_bump.check_version_bump(
            manifest("0.4.16"),
            manifest("0.4.12"),
            allow_version_skip=True,
        )

        self.assertEqual(
            [
                check_version_bump.ISSUE_ROLLBACK,
                check_version_bump.ISSUE_ROLLBACK,
            ],
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_override_still_rejects_unchanged_versions(self) -> None:
        issues = check_version_bump.check_version_bump(
            manifest("0.4.16"),
            manifest("0.4.16"),
            allow_version_skip=True,
        )

        self.assertEqual(
            [
                check_version_bump.ISSUE_UNCHANGED,
                check_version_bump.ISSUE_UNCHANGED,
            ],
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_override_still_rejects_preview_major(self) -> None:
        with mock.patch.object(check_version_bump, "PREVIEW_RELEASE", True):
            issues = check_version_bump.check_version_bump(
                manifest("0.4.16"),
                manifest("1.0.0"),
                allow_version_skip=True,
            )

        self.assertEqual(
            [
                check_version_bump.ISSUE_PREVIEW_MAJOR,
                check_version_bump.ISSUE_PREVIEW_MAJOR,
            ],
            [issue_type for issue_type, _ in issues],
        )

    def test_version_skip_override_still_rejects_malformed_versions(self) -> None:
        with self.assertRaisesRegex(
            check_version_bump.VersionBumpError,
            "current marketplace metadata.version must use MAJOR.MINOR.PATCH semver",
        ):
            check_version_bump.check_version_bump(
                manifest("0.4.16"),
                manifest("invalid"),
                allow_version_skip=True,
            )


if __name__ == "__main__":
    unittest.main()
