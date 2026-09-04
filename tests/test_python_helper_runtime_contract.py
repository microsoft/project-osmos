from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "project-osmos"
SKILL_PATH = SKILL_DIR / "SKILL.md"
RUNTIME_PATH = SKILL_DIR / "references" / "python-helper-runtime.md"
SCRIPTS_DIR = SKILL_DIR / "scripts"
RUNTIME_GUARD_PATH = SCRIPTS_DIR / "python_runtime.py"
POWERSHELL_WRAPPER_PATH = SCRIPTS_DIR / "resolve-auth-and-routing.ps1"


def load_runtime_guard():
    module_name = "project_osmos_python_runtime_test"
    spec = importlib.util.spec_from_file_location(module_name, RUNTIME_GUARD_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load runtime guard from {RUNTIME_GUARD_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


python_runtime = load_runtime_guard()


class PythonHelperRuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.runtime = RUNTIME_PATH.read_text(encoding="utf-8")

    def test_skill_delegates_runtime_details_without_repeating_them(self) -> None:
        self.assertIn("[Python helper runtime]", self.skill)
        self.assertIn("Python 3.11+", self.skill)
        self.assertIn("never install packages", self.skill)
        self.assertNotIn("existing `uv`-managed environment", self.skill)

    def test_runtime_covers_uv_and_local_environments(self) -> None:
        normalized_runtime = " ".join(self.runtime.split())
        required = (
            "require Python 3.11 or newer",
            "virtual environment or Conda environment is active",
            "`uv run --no-sync python`",
            "`--active`",
            "scan the existing `python` and `python3` executables across `PATH` in order",
            "deduplicate aliases to the same interpreter",
            "reuse it for every helper",
            "Do not invoke `uv run` unless the `uv` environment already exists",
            "Do not create `.venv`",
            "exits once with a message that names its path and version",
            "Do not add Python environment or package-install instructions",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, normalized_runtime)

    def test_runtime_guard_rejects_older_python_with_clear_message(self) -> None:
        self.assertEqual((3, 11), python_runtime.MINIMUM_PYTHON)
        with self.assertRaises(SystemExit) as error:
            python_runtime.require_supported_python(
                version_info=(3, 10, 14),
                executable="/usr/bin/python3",
            )
        message = str(error.exception)
        self.assertIn("require Python 3.11 or newer", message)
        self.assertIn("/usr/bin/python3 is Python 3.10.14", message)
        self.assertIn("No packages or environments were changed", message)

    def test_every_python_helper_enforces_the_shared_minimum(self) -> None:
        for path in SCRIPTS_DIR.glob("*.py"):
            if path == RUNTIME_GUARD_PATH:
                continue
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("from python_runtime import require_supported_python", content)
                self.assertIn("require_supported_python()", content)

    def test_helpers_parse_at_the_minimum_supported_version(self) -> None:
        for path in SCRIPTS_DIR.glob("*.py"):
            with self.subTest(path=path.name):
                ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                    feature_version=python_runtime.MINIMUM_PYTHON,
                )

    def test_helpers_import_only_standard_library_or_sibling_modules(self) -> None:
        sibling_modules = {
            path.stem.replace("-", "_") for path in SCRIPTS_DIR.glob("*.py")
        }
        unexpected: dict[str, set[str]] = {}

        for path in SCRIPTS_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".", maxsplit=1)[0])
            external = imports - sys.stdlib_module_names - sibling_modules
            if external:
                unexpected[path.name] = external

        self.assertEqual({}, unexpected)

    def test_powershell_wrapper_requires_a_compatible_existing_python(self) -> None:
        wrapper = POWERSHELL_WRAPPER_PATH.read_text(encoding="utf-8")
        self.assertIn("sys.version_info >= (3, 11)", wrapper)
        self.assertIn('@{ Name = "py"; PrefixArgs = @("-3") }', wrapper)
        self.assertIn('(Python $($probe.Version))', wrapper)
        self.assertIn("No packages or environments were changed", wrapper)
        self.assertNotIn("Install Python", wrapper)


if __name__ == "__main__":
    unittest.main()
