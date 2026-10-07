# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Safeguards for retained packaging and safe task migration."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "project-osmos"
README = (ROOT / "README.md").read_text(encoding="utf-8")
MANIFEST = json.loads((ROOT / ".github/plugin/marketplace.json").read_text(encoding="utf-8"))
SUCCESSOR = MANIFEST["plugins"][0]["repository"].rsplit("/", 1)[0].removeprefix("https://github.com/") + "/skills-for-fabric"


class MigrationContractTests(unittest.TestCase):
    def test_readme_keeps_product_title_without_release_version(self):
        self.assertEqual("# Project Osmos for Microsoft Fabric", README.splitlines()[0])
        self.assertNotRegex(README, r"\b\d+\.\d+\.\d+\b")

    def test_old_skill_is_absent(self):
        self.assertFalse(SKILL_ROOT.exists())
        self.assertFalse((ROOT / "plugins").exists())
        self.assertEqual(["project-osmos"], [p["name"] for p in MANIFEST["plugins"]])

    def test_identity_version_and_composition(self):
        self.assertEqual("project-osmos", MANIFEST["name"])
        self.assertRegex(MANIFEST["metadata"]["version"], r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
        plugin = MANIFEST["plugins"][0]
        self.assertRegex(plugin["version"], r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
        self.assertEqual("./", plugin["source"])
        expected_skills = ["./skills/project-osmos-migration"]
        for name in (".github/plugin/marketplace.json", ".claude-plugin/marketplace.json",
                     ".agents/plugins/marketplace.json"):
            native = json.loads((ROOT / name).read_text(encoding="utf-8"))
            self.assertEqual(1, len(native["plugins"]))
            self.assertEqual(MANIFEST["metadata"]["version"], native["metadata"]["version"])
            self.assertEqual(plugin["version"], native["plugins"][0]["version"])
            self.assertEqual(expected_skills, native["plugins"][0]["skills"])
        self.assertEqual({Path(skill).name for skill in expected_skills},
                         {path.name for path in (ROOT / "skills").iterdir()})
        if expected_skills == ["./skills/project-osmos-migration"]:
            root = ROOT / "skills/project-osmos-migration"
            self.assertEqual({"SKILL.md"}, {
                path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
            })
            for field in ("keywords", "tags", "category"):
                self.assertNotIn(field, plugin)

    def test_composition_accepts_future_independent_versions(self):
        original_read = Path.read_text
        for catalog_version, plugin_version in (("1.0.1", "1.0.0"), ("1.0.1", "1.0.1")):
            with self.subTest(catalog=catalog_version, plugin=plugin_version):
                candidate = copy.deepcopy(MANIFEST)
                candidate["metadata"]["version"] = catalog_version
                candidate["plugins"][0]["version"] = plugin_version
                def read_text(path, *args, catalog_version=catalog_version, plugin_version=plugin_version, **kwargs):
                    text = original_read(path, *args, **kwargs)
                    if path.name == "marketplace.json":
                        native = json.loads(text)
                        native["metadata"]["version"] = catalog_version
                        native["plugins"][0]["version"] = plugin_version
                        return json.dumps(native)
                    return text
                with patch.dict(MANIFEST, candidate), patch.object(Path, "read_text", read_text):
                    self.test_identity_version_and_composition()

    def test_composition_rejects_invalid_and_unsynchronized_versions(self):
        for target in ("metadata", "plugin"):
            candidate = copy.deepcopy(MANIFEST)
            entry = candidate["metadata"] if target == "metadata" else candidate["plugins"][0]
            mismatched_version = f"{int(entry['version'].split('.')[0]) + 1}.0.0"
            for value in ("invalid", "01.0.0", mismatched_version):
                with self.subTest(target=target, value=value):
                    entry["version"] = value
                    with patch.dict(MANIFEST, candidate), self.assertRaises(AssertionError):
                        self.test_identity_version_and_composition()

    def test_handoff_preserves_scope_and_existing_tasks(self):
        for contract in (
            "Keep `.dataprojects`", "original task ID, route, and state path",
            "defer the package change", "does not cancel the remote task",
            "may already have replaced the scripts", "Do not assume SFF reads the old state schema",
            "Wait for permission", "installation scope", "actual ID",
            "Do not remove `fabric-skills`", "Verify SFF remains enabled",
            "unknown or conflicting same-name marketplace", "verify its Git remote",
            "Stop before loading, updating, or installing", "silently switch SFF distributions",
        ):
            self.assertIn(contract, " ".join(README.split()))

    def test_client_commands_and_consent(self):
        source = "/absolute/path/to/skills-for-fabric" if not SUCCESSOR.startswith("microsoft/") else SUCCESSOR
        for client, install, uninstall in (
            ("copilot", "install", "uninstall"), ("claude", "install", "uninstall"),
            ("codex", "add", "remove"),
        ):
            self.assertIn(f"{client} plugin marketplace add {source}", README)
            self.assertIn(f"{client} plugin {install} fabric-skills@fabric-collection", README)
            self.assertIn(f"{client} plugin {uninstall} project-osmos@project-osmos", README)
        self.assertIn("If removal is declined, leave the package unchanged", " ".join(README.split()))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Public users can remove", " ".join(readme.split()))
        self.assertIn("SFF is not installed automatically", readme)
        self.assertIn("best-effort", readme)

    def test_privacy_and_links(self):
        self.assertIn("this package has no telemetry setting",
                      (ROOT / "PRIVACY.md").read_text(encoding="utf-8"))
        paths = list(ROOT.glob("*.md")) + list((ROOT / "skills").rglob("*.md"))
        for path in paths:
            content = path.read_text(encoding="utf-8")
            self.assert_markdown_links(path, content)

    def assert_markdown_links(self, path, content=None):
        text = path.read_text(encoding="utf-8") if content is None else content
        text = re.sub(r"(?ms)^```.*?^```[^\n]*", "", text)
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            linked = (path.parent / unquote(url.path)).resolve() if url.path else path
            self.assertTrue(linked.exists(), f"{path}: missing target {target}")
            if url.fragment:
                headings = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", linked.read_text(encoding="utf-8"))
                anchors = {re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-") for heading in headings}
                self.assertIn(unquote(url.fragment), anchors, f"{path}: missing anchor {target}")

    def test_link_check_rejects_missing_file_and_readme_anchor(self):
        for target in ("absent-guide.md", "README.md#absent-heading"):
            with self.subTest(target=target), self.assertRaises(AssertionError):
                self.assert_markdown_links(ROOT / "README.md", f"[broken]({target})")

    def test_upgrade_distinguishes_local_sources_and_manual_skill_copies(self):
        text = " ".join(README.split())
        self.assertIn("does not update a local-directory marketplace", text)
        self.assertIn("does not remove a separately installed or manually copied skill", text)
        self.assertIn("Do not delete SFF's skill", text)
        self.assertIn("Only the public distribution contains the `project-osmos-migration`", text)

    def test_readme_covers_discovery_update_scope_and_blocked_handoff(self):
        text = " ".join(README.split())
        for contract in (
            "copilot skill list --json", "claude plugin details <installed-id>",
            "codex plugin list --json", "actual loaded skill path",
            "do not install duplicate bundles", "existing scope", "--scope user|project|local",
            "substitute marketplace `fabric-collection`", "or the exact installed alias",
            "git pull --ff-only", "codex plugin add fabric-skills@fabric-collection",
            "Stop on dirty/diverged checkout or build failure", "Restart/reload after changes",
            "If declined, blocked or awaiting reload, retain the request and task context",
            "Installation is not data-task completion or permission to run one",
            "inspect only the supplied task's process/state, not token files",
            "stops only the verified local worker", "--keep-data",
        ):
            self.assertIn(contract, text)


class CompanionValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("validator", ROOT / "build/validate_plugin.py")
        cls.validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.validator)

    def test_companion_contract_is_valid(self):
        self.assertEqual([], self.validator.validate_companion())

    def test_marketplace_and_plugin_versions_are_independent(self):
        manifest = json.loads((ROOT / ".github/plugin/marketplace.json").read_text(encoding="utf-8"))
        manifest["metadata"]["version"] = "1.2.0"
        self.assertEqual([], self.validator.validate_marketplace(manifest))

    def test_validator_rejects_nested_retired_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            retired = root / "skills" / "project-osmos" / "scripts"
            retired.mkdir(parents=True)
            (retired / "old.py").touch()
            with patch.object(self.validator, "REPO_ROOT", root):
                # Copy docs to exercise the absence check rather than missing-resource errors.
                import shutil
                for name in ("README.md", ".github/workflows/release-plugin.yml"):
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / name, target)
                issues = self.validator.validate_companion()
        self.assertIn("remove the retired standalone skill tree", issues)

    def test_validator_rejects_old_skill_declaration(self):
        plugin = dict(MANIFEST["plugins"][0], skills=[(Path("skills") / "project-osmos").as_posix()])
        self.assertTrue(self.validator.validate_plugin_entry(MANIFEST["name"], plugin))

    def test_validator_rejects_second_plugin(self):
        manifest = json.loads(json.dumps(MANIFEST))
        manifest["plugins"].append(dict(manifest["plugins"][0], name="another-package"))
        self.assertTrue(self.validator.validate_marketplace(manifest))

    def test_validator_rejects_missing_wrong_or_mixed_successor_sources(self):
        original = Path.read_text
        for filename in ("README.md", "release-plugin.yml"):
            for replacement in (
                "", "other-owner/skills-for-fabric", SUCCESSOR + " other-owner/skills-for-fabric",
                SUCCESSOR + "-fork", SUCCESSOR + ".backup", SUCCESSOR + "_copy",
                SUCCESSOR + " " + SUCCESSOR + "-fork",
            ):
                with self.subTest(file=filename, replacement=replacement):
                    def read_text(path, *args, _filename=filename, _replacement=replacement, **kwargs):
                        content = original(path, *args, **kwargs)
                        return content.replace(SUCCESSOR, _replacement) if path.name == _filename else content

                    with patch.object(Path, "read_text", read_text):
                        issues = self.validator.validate_companion()
                    self.assertTrue(any("successor source" in issue for issue in issues), issues)

    def test_validator_rejects_coordinated_repository_and_guidance_drift(self):
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            return original(path, *args, **kwargs).replace(
                MANIFEST["plugins"][0]["repository"], "https://github.com/other-owner/project-osmos",
            ).replace(SUCCESSOR, "other-owner/skills-for-fabric")

        with patch.object(Path, "read_text", read_text):
            issues = self.validator.validate_companion()
        self.assertTrue(any("companion repository" in issue for issue in issues), issues)

    def test_validator_accepts_exact_successor_links_and_git_clone_urls(self):
        for content in (
            SUCCESSOR, f"Use {SUCCESSOR}.",
            f"https://github.com/{SUCCESSOR}", f"https://github.com/{SUCCESSOR}.git",
            f"https://github.com/{SUCCESSOR}/tree/main#readme",
            f"ssh://git@github.com/{SUCCESSOR}.git", f"git@github.com:{SUCCESSOR}.git",
        ):
            with self.subTest(content=content):
                self.assertEqual([], self.validator.validate_successor_guidance(
                    MANIFEST["plugins"][0]["repository"], {"skill": content},
                ))

    def test_validator_rejects_wrong_url_authority_and_path_traversal(self):
        for url in (
            f"https://notgithub.com/{SUCCESSOR}",
            f"https://github.com.evil.example/{SUCCESSOR}",
            f"https://github.com@evil.example/{SUCCESSOR}",
            f"https://github.com:444/{SUCCESSOR}",
            f"https://github.com:invalid/{SUCCESSOR}",
            f"http://github.com/{SUCCESSOR}",
            f"https://github.com/{SUCCESSOR}/../../other-owner/other-repo",
            f"https://github.com/{SUCCESSOR}/%2e%2e/%2e%2e/other-owner/other-repo",
            f"https://github.com/{SUCCESSOR}/%5c..%5c..%5cother-repo",
            f"git@evil.example:{SUCCESSOR}.git",
        ):
            for content in (url, SUCCESSOR + " " + url):
                with self.subTest(content=content):
                    self.assertTrue(self.validator.validate_successor_guidance(
                        MANIFEST["plugins"][0]["repository"], {"skill": content},
                    ))

    def test_validator_rejects_missing_readme(self):
        original = Path.read_text
        def read_text(path, *args, **kwargs):
            if path.name == "README.md":
                raise FileNotFoundError(path)
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", read_text):
            self.assertTrue(self.validator.validate_companion())

    def test_readme_alone_must_identify_successor_bundle(self):
        original = Path.read_text
        def read_text(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            return text.replace("fabric-skills@fabric-collection", "") if path.name == "README.md" else text
        with patch.object(Path, "read_text", read_text):
            self.assertIn("README must identify the SFF replacement plugin", self.validator.validate_companion())

    def test_public_validator_rejects_discovery_metadata(self):
        with patch.object(self.validator, "EXPECTED_SKILLS", ["./skills/project-osmos-migration"]):
            for value in ([], ["task"], None, "task"):
                plugin = dict(MANIFEST["plugins"][0], skills=["./skills/project-osmos-migration"], keywords=value)
                self.assertTrue(any("keywords" in issue for issue in
                                    self.validator.validate_plugin_entry(MANIFEST["name"], plugin)))

    def test_public_skill_requires_only_guidance_with_discoverable_identity_and_source(self):
        import shutil
        source = ROOT / "skills/project-osmos-migration"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_root = root / "skills/project-osmos-migration"
            shutil.copytree(source, skill_root)
            with patch.object(self.validator, "REPO_ROOT", root):
                self.assertEqual([], self.validator.validate_public_migration_skill())
                for name, replacement in (
                    ("SKILL.md", ""),
                    ("SKILL.md", (source / "SKILL.md").read_text().replace(
                        "name: project-osmos-migration", "name: project-osmos")),
                    ("SKILL.md", (source / "SKILL.md").read_text().replace(
                        "name: project-osmos-migration", "name: project-osmos-migration-other")),
                    ("SKILL.md", (source / "SKILL.md").read_text().replace(
                        "microsoft/skills-for-fabric", "other/skills-for-fabric")),
                    ("SKILL.md", (source / "SKILL.md").read_text().replace(
                        "name: project-osmos-migration",
                        "name: project-osmos-migration\ndisable-model-invocation: true")),
                ):
                    with self.subTest(name=name, replacement=replacement):
                        (skill_root / name).write_text(replacement, encoding="utf-8")
                        self.assertTrue(self.validator.validate_public_migration_skill())
                        shutil.copyfile(source / name, skill_root / name)
                (skill_root / "runner.py").touch()
                self.assertTrue(self.validator.validate_public_migration_skill())


if __name__ == "__main__":
    unittest.main()
