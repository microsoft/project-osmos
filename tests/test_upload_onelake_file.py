from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "project-osmos" / "scripts" / "upload-onelake-file.py"


def load_upload_module():
    module_name = "project_osmos_upload_onelake_file_test"
    original_runtime = sys.modules.get("python_runtime")
    try:
        with mock.patch.object(sys, "path", [str(SCRIPT_PATH.parent), *sys.path]):
            spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"could not load upload helper from {SCRIPT_PATH}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        if original_runtime is None:
            sys.modules.pop("python_runtime", None)
        else:
            sys.modules["python_runtime"] = original_runtime


uploader = load_upload_module()


class OneLakeUploadTests(unittest.TestCase):
    def test_destination_must_remain_under_files(self) -> None:
        for value in ("/Files/instruction.md", "Tables/instruction.md", "Files/../instruction.md"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                uploader.validated_destination(value)

    def test_upload_creates_directories_and_writes_exact_bytes(self) -> None:
        calls: list[
            tuple[str, str, bytes | None, tuple[int, ...], tuple[tuple[int, str], ...], float]
        ] = []

        def record_request(
            method: str,
            url: str,
            token: str,
            *,
            data: bytes | None = None,
            allowed_statuses: tuple[int, ...] = (200,),
            allowed_errors: tuple[tuple[int, str], ...] = (),
            timeout_seconds: float = uploader.DEFAULT_TIMEOUT_SECONDS,
        ) -> None:
            self.assertEqual("secret-token", token)
            calls.append((method, url, data, allowed_statuses, allowed_errors, timeout_seconds))

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "instruction.md"
            source.write_text("exact user outcome\n", encoding="utf-8")
            destination = uploader.validated_destination(
                "Files/ProjectOsmos/tasks/00000000-0000-0000-0000-000000000003/instruction.md"
            )

            with mock.patch.object(uploader, "send_request", side_effect=record_request):
                result = uploader.upload(
                    source,
                    "00000000-0000-0000-0000-000000000001",
                    "00000000-0000-0000-0000-000000000002",
                    destination,
                    "secret-token",
                )

        self.assertEqual(b"exact user outcome\n", calls[-2][2])
        self.assertTrue(all(call[4] == ((409, "PathAlreadyExists"),) for call in calls[:-3]))
        self.assertNotIn("overwrite=", calls[-3][1])
        self.assertEqual((201,), calls[-3][3])
        self.assertEqual((202,), calls[-2][3])
        self.assertIn("action=flush", calls[-1][1])
        self.assertEqual((200,), calls[-1][3])
        self.assertTrue(all(call[5] == uploader.DEFAULT_TIMEOUT_SECONDS for call in calls))
        self.assertEqual(19, result["bytes"])
        self.assertEqual(destination.as_posix(), result["destination"])


if __name__ == "__main__":
    unittest.main()
