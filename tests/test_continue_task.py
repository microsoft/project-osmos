from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills" / "project-osmos" / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "post-user-message.py"


def load_post_user_message():
    module_name = "project_osmos_post_user_message"
    original_task_status = sys.modules.get("task_status")
    original_runtime = sys.modules.get("python_runtime")
    try:
        with mock.patch.object(sys, "path", [str(SCRIPTS_DIR), *sys.path]):
            spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"could not load helper from {SCRIPT_PATH}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        if original_task_status is None:
            sys.modules.pop("task_status", None)
        else:
            sys.modules["task_status"] = original_task_status
        if original_runtime is None:
            sys.modules.pop("python_runtime", None)
        else:
            sys.modules["python_runtime"] = original_runtime


post_user_message = load_post_user_message()


class DynamicLoaderIsolationTests(unittest.TestCase):
    def test_loader_restores_import_search_path_and_task_status_module(self) -> None:
        missing = object()
        original_path = list(sys.path)
        original_task_status = sys.modules.get("task_status", missing)
        original_runtime = sys.modules.get("python_runtime", missing)

        load_post_user_message()

        self.assertEqual(sys.path, original_path)
        if original_task_status is missing:
            self.assertNotIn("task_status", sys.modules)
        else:
            self.assertIs(sys.modules.get("task_status"), original_task_status)
        if original_runtime is missing:
            self.assertNotIn("python_runtime", sys.modules)
        else:
            self.assertIs(sys.modules.get("python_runtime"), original_runtime)


class ContinueTaskTests(unittest.TestCase):
    base_url = "https://example.test/aichat"
    task_id = "task-123"
    auth_header = "mwctoken secret"

    def result(self, status: int, payload: dict[str, object] | None = None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        return post_user_message.HttpResult(status, body, "https://example.test")

    def invoke(
        self,
        task_payload: dict[str, object],
        message_status: int = 204,
        run_status: int = 202,
        later_task_payloads: tuple[dict[str, object], ...] = (),
    ):
        calls: list[tuple[str, str, bytes | None]] = []
        task_payloads = [task_payload, *later_task_payloads]
        task_read_index = 0

        def fake_request(
            url: str,
            auth_header: str,
            timeout: float,
            *,
            method: str = "GET",
            body: bytes | None = None,
            content_type: str | None = None,
        ):
            nonlocal task_read_index
            self.assertEqual(auth_header, self.auth_header)
            self.assertEqual(timeout, 15.0)
            calls.append((url, method, body))
            if method == "GET":
                payload = task_payloads[min(task_read_index, len(task_payloads) - 1)]
                task_read_index += 1
                return self.result(200, payload)
            if url.endswith("/messages"):
                self.assertEqual(content_type, "application/json")
                return self.result(message_status)
            self.assertTrue(url.endswith("/run"))
            self.assertIsNone(body)
            return self.result(run_status)

        with mock.patch.object(post_user_message, "http_request", side_effect=fake_request):
            result = post_user_message.continue_task(
                base_url=self.base_url,
                task_id=self.task_id,
                auth_header=self.auth_header,
                message="Preserve this exact follow-up.",
                author_name="user@example.test",
                source="test",
                timeout=15.0,
            )
        return result, calls

    def test_terminal_statuses_post_then_start_exactly_one_run(self) -> None:
        cases = (
            ("Completed", {}),
            (5, {"errorMessage": "failed"}),
            ("3", {"completedAt": "2026-08-24T12:00:00Z"}),
        )
        for status, run_details in cases:
            with self.subTest(status=status):
                result, calls = self.invoke({"status": status, "runDetails": run_details})

                self.assertTrue(result.terminal_before)
                self.assertTrue(result.run_started)
                self.assertEqual(result.run_start_outcome, "started")
                self.assertTrue(result.poller_restart_required)
                self.assertEqual([method for _, method, _ in calls], ["GET", "POST", "GET", "POST"])
                self.assertTrue(calls[1][0].endswith("/messages"))
                self.assertTrue(calls[3][0].endswith("/run"))
                message_payload = json.loads(calls[1][2].decode("utf-8"))
                self.assertEqual(message_payload["messages"][0]["content"], "Preserve this exact follow-up.")

    def test_running_status_variants_post_without_starting_a_duplicate_run(self) -> None:
        for status in ("Running", 1, "1"):
            with self.subTest(status=status):
                result, calls = self.invoke({"status": status, "runDetails": {}})

                self.assertTrue(result.running_before)
                self.assertFalse(result.run_started)
                self.assertTrue(result.run_active)
                self.assertEqual(result.run_start_outcome, "not_needed")
                self.assertFalse(result.poller_restart_required)
                self.assertEqual([method for _, method, _ in calls], ["GET", "POST", "GET"])

    def test_running_task_that_finishes_during_elicitation_recheck_starts_one_run(self) -> None:
        result, calls = self.invoke(
            {"status": "Running", "runDetails": {}},
            later_task_payloads=({"status": "Completed", "runDetails": {"completedAt": "2026-08-24T12:00:00Z"}},),
        )

        self.assertTrue(result.running_before)
        self.assertFalse(result.running_after_message)
        self.assertTrue(result.run_started)
        self.assertEqual(result.run_start_outcome, "started")
        self.assertEqual([method for _, method, _ in calls], ["GET", "POST", "GET", "POST"])
        self.assertEqual(sum(url.endswith("/run") for url, _, _ in calls), 1)

    def test_terminal_task_that_is_running_after_message_does_not_start_a_duplicate(self) -> None:
        result, calls = self.invoke(
            {"status": "Completed", "runDetails": {"completedAt": "2026-08-24T12:00:00Z"}},
            later_task_payloads=({"status": "Running", "runDetails": {}},),
        )

        self.assertTrue(result.terminal_before)
        self.assertTrue(result.running_after_message)
        self.assertFalse(result.run_start_attempted)
        self.assertFalse(result.run_started)
        self.assertTrue(result.run_active)
        self.assertEqual(result.run_start_outcome, "not_needed")
        self.assertTrue(result.poller_restart_required)
        self.assertEqual([method for _, method, _ in calls], ["GET", "POST", "GET"])

    def test_run_details_override_stale_running_status(self) -> None:
        cases = (
            {"completedAt": "2026-08-24T12:00:00Z", "errorMessage": None},
            {"completedAt": None, "errorMessage": "terminal failure"},
        )
        for run_details in cases:
            with self.subTest(run_details=run_details):
                result, calls = self.invoke({"status": "Running", "runDetails": run_details})

                self.assertTrue(result.terminal_before)
                self.assertFalse(result.running_before)
                self.assertTrue(result.run_started)
                self.assertEqual(sum(url.endswith("/run") for url, _, _ in calls), 1)

    def test_run_conflict_is_success_only_when_live_recheck_confirms_running(self) -> None:
        result, calls = self.invoke(
            {"status": "Completed", "runDetails": {"completedAt": "2026-08-24T12:00:00Z"}},
            run_status=409,
            later_task_payloads=(
                {"status": "Completed", "runDetails": {"completedAt": "2026-08-24T12:00:01Z"}},
                {"status": "Running", "runDetails": {}},
            ),
        )

        self.assertTrue(result.run_start_attempted)
        self.assertFalse(result.run_started)
        self.assertTrue(result.run_active)
        self.assertEqual(result.run_start_outcome, "already_running")
        self.assertTrue(result.poller_restart_required)
        self.assertEqual([method for _, method, _ in calls], ["GET", "POST", "GET", "POST", "GET"])
        self.assertEqual(sum(url.endswith("/run") for url, _, _ in calls), 1)

    def test_run_conflict_does_not_retry_when_live_task_is_not_running(self) -> None:
        with self.assertRaisesRegex(
            post_user_message.ContinuationError,
            r"returned HTTP 409 and the live task is Completed; no second run request was sent",
        ):
            self.invoke(
                {"status": "Completed", "runDetails": {}},
                run_status=409,
                later_task_payloads=(
                    {"status": "Completed", "runDetails": {}},
                    {"status": "Completed", "runDetails": {}},
                ),
            )

    def test_non_running_non_terminal_status_starts_one_run(self) -> None:
        result, calls = self.invoke({"status": "Created", "runDetails": {}})

        self.assertFalse(result.terminal_before)
        self.assertFalse(result.running_before)
        self.assertTrue(result.run_started)
        self.assertEqual(sum(url.endswith("/run") for url, _, _ in calls), 1)

    def test_message_post_failure_never_starts_a_run(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_request(
            url: str,
            _auth_header: str,
            _timeout: float,
            *,
            method: str = "GET",
            body: bytes | None = None,
            content_type: str | None = None,
        ):
            del body, content_type
            calls.append((url, method))
            if method == "GET":
                return self.result(200, {"status": "Completed", "runDetails": {}})
            return post_user_message.HttpResult(500, b"message rejected", url)

        with mock.patch.object(post_user_message, "http_request", side_effect=fake_request):
            with self.assertRaisesRegex(post_user_message.ContinuationError, "user message post failed"):
                post_user_message.continue_task(
                    base_url=self.base_url,
                    task_id=self.task_id,
                    auth_header=self.auth_header,
                    message="Do not lose this.",
                    author_name="user@example.test",
                    source="test",
                    timeout=15.0,
                )

        self.assertEqual([method for _, method in calls], ["GET", "POST"])
        self.assertFalse(any(url.endswith("/run") for url, _ in calls))

    def test_run_start_failure_reports_that_message_was_already_posted(self) -> None:
        with self.assertRaisesRegex(
            post_user_message.ContinuationError,
            r"user message .* was posted, but same-task run start failed \(HTTP 500\)",
        ):
            self.invoke({"status": "Failed", "runDetails": {}}, run_status=500)


class FollowUpGuidanceTests(unittest.TestCase):
    def test_skill_and_lifecycle_define_the_same_post_then_run_order(self) -> None:
        skill = (REPO_ROOT / "skills" / "project-osmos" / "SKILL.md").read_text(encoding="utf-8")
        lifecycle = (
            REPO_ROOT / "skills" / "project-osmos" / "references" / "task-lifecycle.md"
        ).read_text(encoding="utf-8")

        for content in (skill, lifecycle):
            self.assertIn("terminal.json", content)
            self.assertIn("state.json", content)
            self.assertIn("post-user-message.py", content)
            self.assertIn("same task ID", content)
        self.assertIn("Post the full user-authored message first", skill)
        self.assertIn("exactly once", lifecycle)
        self.assertIn("poller_restart_required", lifecycle)
        self.assertIn("elicitation", lifecycle)
        self.assertIn("HTTP 409", lifecycle)

    def test_public_projection_keeps_continuation_contract(self) -> None:
        skill = (REPO_ROOT / "skills" / "project-osmos" / "SKILL.md").read_text(encoding="utf-8")
        lifecycle = (
            REPO_ROOT / "skills" / "project-osmos" / "references" / "task-lifecycle.md"
        ).read_text(encoding="utf-8")
        internal_tag = "internal"
        internal_block = re.compile(
            rf"(?ms)^[ \t]*<{internal_tag}>[ \t\r]*\n"
            rf".*?^[ \t]*</{internal_tag}>[ \t\r]*(?:\n|$)",
            re.IGNORECASE,
        )
        public_skill = internal_block.sub("", skill)
        public_lifecycle = internal_block.sub("", lifecycle)

        self.assertIn("Elicitation responses commonly arrive", public_skill)
        self.assertIn("always fetches live status again", public_skill)
        self.assertIn("Always fetch live status again after the message post succeeds", public_lifecycle)
        self.assertIn("POST /{taskId}/run` exactly once", public_lifecycle)
        self.assertNotIn("For private routes", public_skill)
        self.assertNotIn("For private routes", public_lifecycle)


if __name__ == "__main__":
    unittest.main()
