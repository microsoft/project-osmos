from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build import release_plugin


class ReleasePluginTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir()
        self.remote = Path(self.temporary.name) / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        self.git("init", "-q")
        self.git("config", "user.name", "Release test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", str(self.remote))
        manifest = self.root / ".github/plugin/marketplace.json"
        manifest.parent.mkdir(parents=True)
        self.manifest = {
            "metadata": {"version": "1.0.1"},
            "plugins": [{"name": "legacy", "version": "1.0.0"}, {"name": "companion", "version": "1.0.1"}],
        }
        manifest.write_text(json.dumps(self.manifest))
        self.git("add", ".github/plugin/marketplace.json")
        self.git("commit", "-qm", "Fixture")
        self.commit = self.git("rev-parse", "HEAD")
        self.releases = set()
        self.created_notes = []
        original = release_plugin.run

        def run(root, *args):
            if args[0] != "gh":
                return original(root, *args)
            if args[1] == "api":
                return "\n".join(sorted(self.releases))
            self.assertEqual(("release", "create", "v1.0.1"), args[1:4])
            self.assertIn("--verify-tag", args)
            self.created_notes.append(Path(args[-1]).read_text())
            self.releases.add(args[3])
            return ""

        self.addCleanup(mock.patch.stopall)
        mock.patch.object(release_plugin, "run", side_effect=run).start()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def test_first_release_and_same_commit_rerun(self):
        for _ in range(2):
            release_plugin.publish(self.root, self.commit, "Use the successor.")
        self.assertEqual(1, len(self.created_notes))
        self.assertIn("| `legacy` | `1.0.0` |", self.created_notes[0])
        self.assertIn("| `companion` | `1.0.1` |", self.created_notes[0])
        self.assertEqual(self.commit, release_plugin.tag_commit(self.root, "v1.0.1"))

    def test_existing_annotated_tag_is_peeled_and_release_can_resume(self):
        self.git("tag", "-a", "v1.0.1", "-m", "Annotated release")
        self.git("push", "origin", "refs/tags/v1.0.1")
        release_plugin.publish(self.root, self.commit, "Use the successor.")
        self.assertEqual(1, len(self.created_notes))

    def test_existing_tag_on_different_commit_is_never_moved(self):
        self.git("tag", "v1.0.1")
        self.git("push", "origin", "refs/tags/v1.0.1")
        self.git("commit", "--allow-empty", "-qm", "Another commit")
        with self.assertRaisesRegex(RuntimeError, "use a new version"):
            release_plugin.publish(self.root, self.git("rev-parse", "HEAD"), "Migration")
        self.assertEqual(self.commit, release_plugin.tag_commit(self.root, "v1.0.1"))
        self.assertEqual([], self.created_notes)

    def test_github_failure_does_not_create_a_tag(self):
        original = release_plugin.run
        def fail_api(root, *args):
            if args[0] == "gh":
                raise subprocess.CalledProcessError(1, args, stderr="API unavailable")
            return original(root, *args)
        with mock.patch.object(release_plugin, "run", side_effect=fail_api):
            with self.assertRaises(subprocess.CalledProcessError):
                release_plugin.publish(self.root, self.commit, "Migration")
        self.assertIsNone(release_plugin.tag_commit(self.root, "v1.0.1"))

    def test_missing_remote_is_not_mistaken_for_missing_tag(self):
        self.git("remote", "set-url", "origin", str(self.remote / "missing"))
        with self.assertRaisesRegex(RuntimeError, "Cannot inspect release tag"):
            release_plugin.publish(self.root, self.commit, "Migration")
        self.assertEqual([], self.created_notes)

    def test_failed_release_creation_can_resume_from_the_existing_tag(self):
        original = release_plugin.run
        def fail_creation(root, *args):
            if args[:3] == ("gh", "release", "create"):
                raise subprocess.CalledProcessError(1, args, stderr="API unavailable")
            return original(root, *args)
        with mock.patch.object(release_plugin, "run", side_effect=fail_creation):
            with self.assertRaises(subprocess.CalledProcessError):
                release_plugin.publish(self.root, self.commit, "Migration")
        self.assertEqual(self.commit, release_plugin.tag_commit(self.root, "v1.0.1"))
        release_plugin.publish(self.root, self.commit, "Migration")
        self.assertEqual(1, len(self.created_notes))

    def test_dirty_checkout_cannot_be_released(self):
        (self.root / "uncommitted.txt").write_text("Not in the release commit")
        with self.assertRaisesRegex(RuntimeError, "must be clean"):
            release_plugin.publish(self.root, self.commit, "Migration")

    def test_notes_only_include_plugins_present_in_the_manifest(self):
        public = {**self.manifest, "plugins": self.manifest["plugins"][:1]}
        notes = release_plugin.release_notes(public, "Use the successor.")
        self.assertIn("legacy", notes)
        self.assertNotIn("companion", notes)


if __name__ == "__main__":
    unittest.main()
