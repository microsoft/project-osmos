from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import unittest
import webbrowser
from pathlib import Path
from unittest import mock


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "project-osmos"
    / "scripts"
    / "launch-task-page.py"
)
SPEC = importlib.util.spec_from_file_location("launch_task_page", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {SCRIPT}")
launch_task_page = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launch_task_page
original_runtime = sys.modules.get("python_runtime")
try:
    with mock.patch.object(sys, "path", [str(SCRIPT.parent), *sys.path]):
        SPEC.loader.exec_module(launch_task_page)
finally:
    if original_runtime is None:
        sys.modules.pop("python_runtime", None)
    else:
        sys.modules["python_runtime"] = original_runtime

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
LAKEHOUSE_ID = "22222222-2222-2222-2222-222222222222"
TASK_ID = "33333333-3333-3333-3333-333333333333"


def args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "lakehouse_id": LAKEHOUSE_ID,
        "task_id": TASK_ID,
        "environment": "prod",
        "source_url": None,
        "portal_base_url": None,
        "no_open": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TaskPageLaunchTests(unittest.TestCase):
    def test_schemeless_portal_preserves_literal_url_query_values(self) -> None:
        query = "context=https://example.test/path&keep=a%2fb+%20c"
        path = f"/groups/{WORKSPACE_ID}/lakehouses/{LAKEHOUSE_ID}"
        suffix = f"&projectOsmosUX=1&selectedPath=ProjectOsmos%2F{TASK_ID}"
        for environment, host in (
            ("prod", "app.fabric.microsoft.com"),
            ("test", "portal.example.test:8443"),
        ):
            for field in ("source_url", "portal_base_url"):
                with self.subTest(environment=environment, field=field):
                    result = launch_task_page.launch_task_page(
                        args(
                            environment=environment,
                            no_open=True,
                            **{field: f"{host}/?{query}"},
                        ),
                    )
                    self.assertEqual(
                        result["task_page_url"],
                        f"https://{host}{path}?{query}{suffix}",
                    )

    def test_private_base_url_and_source_precedence(self) -> None:
        path = f"/groups/{WORKSPACE_ID}/lakehouses/{LAKEHOUSE_ID}"
        suffix = f"&projectOsmosUX=1&selectedPath=ProjectOsmos%2F{TASK_ID}"
        for overrides, expected in (
            (
                {"portal_base_url": "https://portal.example.test:8443"},
                f"https://portal.example.test:8443{path}?experience=power-bi{suffix}",
            ),
            (
                {"portal_base_url": "portal.example.test"},
                f"https://portal.example.test{path}?experience=power-bi{suffix}",
            ),
            (
                {
                    "source_url": "https://source.example.test/?keep=a%2fb+%20c",
                    "portal_base_url": "https://base.example.test/?ignored=1",
                },
                f"https://source.example.test{path}?keep=a%2fb+%20c{suffix}",
            ),
        ):
            with self.subTest(overrides=overrides):
                result = launch_task_page.launch_task_page(
                    args(environment="test", no_open=True, **overrides),
                )
                self.assertEqual(result["task_page_url"], expected)

    def test_private_context_rejects_non_http_schemes_and_missing_hosts(self) -> None:
        for field in ("source_url", "portal_base_url"):
            for url in ("ftp://portal.example.test", "file:///example", "https://"):
                with self.subTest(field=field, url=url):
                    opener = mock.Mock()
                    with self.assertRaisesRegex(ValueError, "valid HTTP\\(S\\) host"):
                        launch_task_page.launch_task_page(
                            args(environment="test", **{field: url}), opener,
                        )
                    opener.assert_not_called()

    def test_guid_validation_and_normalization(self) -> None:
        self.assertEqual(
            launch_task_page.guid("{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"),
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )
        for value in ("../../example", "", "not-a-guid"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    launch_task_page.guid(value)

    def test_cli_reports_invalid_identifiers_and_portal_context_on_stderr(self) -> None:
        defaults = {
            "--workspace-id": WORKSPACE_ID, "--lakehouse-id": LAKEHOUSE_ID,
            "--task-id": TASK_ID, "--environment": "prod",
        }
        cases = [
            ({option: "../../example"}, "invalid GUID:")
            for option in ("--workspace-id", "--lakehouse-id", "--task-id")
        ]
        cases.extend((
            ({"--environment": "test"}, "required outside production"),
            ({"--source-url": "https://portal.example.test"}, "production requires"),
            ({"--environment": ""}, "environment must not be empty"),
        ))
        for overrides, diagnostic in cases:
            with self.subTest(overrides=overrides):
                values = {**defaults, **overrides}
                command = [sys.executable, str(SCRIPT), "--no-open"]
                for option, value in values.items():
                    command.extend((option, value))
                completed = subprocess.run(
                    command, capture_output=True, text=True, timeout=5, check=False,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertIn(diagnostic, completed.stderr)

    def test_empty_environment_is_rejected_before_browser_open(self) -> None:
        for environment in ("", " ", "\t\n"):
            with self.subTest(environment=environment):
                opener = mock.Mock()
                with self.assertRaisesRegex(ValueError, "environment must not be empty"):
                    launch_task_page.launch_task_page(args(environment=environment), opener)
                opener.assert_not_called()

    def test_browser_subprocess_result_mapping(self) -> None:
        for returncode, expected in ((0, "opened"), (1, "failed"), (7, "failed")):
            with self.subTest(returncode=returncode):
                with mock.patch.object(
                    launch_task_page.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], returncode),
                ) as run:
                    result = launch_task_page.launch_task_page(args())
                self.assertEqual(result["telemetry"]["launch_result"], expected)
                self.assertEqual(result["telemetry"]["fallback_used"], returncode != 0)
                self.assertEqual(run.call_args.args[0][-1], result["task_page_url"])

    def test_browser_environment_excludes_tokens_without_changing_parent(self) -> None:
        browser_environment = {
            "BROWSER": "custom-browser %s",
            "DISPLAY": ":0",
            "PATH": os.defpath,
        }
        for tokens in (
            {},
            {"MWC_TOKEN": "test-mwc", "PBI_TOKEN": "test-pbi", "BEARER": "test-bearer"},
            {"mwc_token": "test-mwc", "Pbi_Token": "test-pbi", "bearer": "test-bearer"},
        ):
            with self.subTest(token_names=list(tokens)):
                with mock.patch.dict(os.environ, {**browser_environment, **tokens}, clear=True):
                    parent_environment = dict(os.environ)
                    with mock.patch.object(
                        launch_task_page.subprocess, "run",
                        return_value=subprocess.CompletedProcess([], 0),
                    ) as run:
                        self.assertTrue(launch_task_page.open_browser("https://app.fabric.microsoft.com"))
                    self.assertEqual(run.call_args.kwargs.get("env"), browser_environment)
                    self.assertEqual(dict(os.environ), parent_environment)

    def test_production_url_is_canonical_without_source_url(self) -> None:
        result = launch_task_page.launch_task_page(args(), opener=lambda _: True)

        self.assertEqual(
            result["task_page_url"],
            "https://app.fabric.microsoft.com/groups/"
            f"{WORKSPACE_ID}/lakehouses/{LAKEHOUSE_ID}"
            "?experience=power-bi&projectOsmosUX=1"
            f"&selectedPath=ProjectOsmos%2F{TASK_ID}",
        )
        self.assertEqual(result["telemetry"]["launch_result"], "opened")

    def test_source_url_preserves_environment_and_unowned_query(self) -> None:
        source_url = (
            "https://portal.example.test/groups/old/lakehouses/old/tables/T"
            "?context=https:%2F%2Fexample.test%2Fpath"
            "&selectedPath=old&projectOsmosUX=0&feature=preview#fragment"
        )
        result = launch_task_page.launch_task_page(
            args(environment="test", source_url=source_url),
            opener=lambda _: True,
        )

        self.assertEqual(
            result["task_page_url"],
            "https://portal.example.test/groups/"
            f"{WORKSPACE_ID}/lakehouses/{LAKEHOUSE_ID}"
            "?context=https:%2F%2Fexample.test%2Fpath&feature=preview"
            f"&projectOsmosUX=1&selectedPath=ProjectOsmos%2F{TASK_ID}",
        )

    def test_every_task_opens_without_enrollment_context(self) -> None:
        opened: list[str] = []
        result = launch_task_page.launch_task_page(
            args(),
            opener=lambda url: opened.append(url) or True,
        )

        self.assertEqual(opened, [result["task_page_url"]])
        self.assertEqual(result["telemetry"]["launch_result"], "opened")
        self.assertFalse(result["telemetry"]["fallback_used"])

    def test_browser_failure_returns_nonfatal_url_fallback(self) -> None:
        result = launch_task_page.launch_task_page(args(), opener=lambda _: False)

        self.assertIsNotNone(result["task_page_url"])
        self.assertIn("remote task is still running", result["warning"])
        self.assertEqual(result["telemetry"]["launch_result"], "failed")
        self.assertTrue(result["telemetry"]["fallback_used"])

    def test_no_open_still_returns_fabric_link(self) -> None:
        opener = mock.Mock()
        result = launch_task_page.launch_task_page(
            args(no_open=True),
            opener=opener,
        )

        opener.assert_not_called()
        self.assertIn(f"selectedPath=ProjectOsmos%2F{TASK_ID}", result["task_page_url"])
        self.assertEqual(result["telemetry"]["launch_result"], "not_attempted")
        self.assertFalse(result["telemetry"]["fallback_used"])
        self.assertIsNone(result["warning"])

    def test_browser_exception_is_nonfatal(self) -> None:
        for error in (
            OSError("no browser"),
            webbrowser.Error("no browser"),
            RuntimeError("controller failed"),
        ):
            with self.subTest(error=type(error).__name__):
                result = launch_task_page.launch_task_page(
                    args(), opener=mock.Mock(side_effect=error),
                )
                self.assertIsNotNone(result["task_page_url"])
                self.assertEqual(result["telemetry"]["launch_result"], "failed")

    def test_browser_timeout_returns_link_without_waiting_for_browser(self) -> None:
        with mock.patch.object(
            launch_task_page.subprocess, "run",
            side_effect=subprocess.TimeoutExpired("browser", 3),
        ) as run:
            result = launch_task_page.launch_task_page(args())
        self.assertIsNotNone(result["task_page_url"])
        self.assertEqual(result["telemetry"]["launch_result"], "timed_out")
        self.assertTrue(result["telemetry"]["fallback_used"])
        self.assertEqual(run.call_args.kwargs["timeout"], 3.0)
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(run.call_args.kwargs[stream], subprocess.DEVNULL)

    @unittest.skipIf(os.name == "nt", "BROWSER command quoting uses POSIX shlex")
    def test_cli_isolates_noisy_long_running_browser_from_json_pipe(self) -> None:
        browser = shlex.join([
            sys.executable, "-c",
            "import time; print('browser output', flush=True); time.sleep(10)",
            "%s",
        ])
        process = subprocess.Popen(
            [
                sys.executable, str(SCRIPT),
                "--workspace-id", WORKSPACE_ID, "--lakehouse-id", LAKEHOUSE_ID,
                "--task-id", TASK_ID, "--environment", "prod",
            ],
            env={**os.environ, "BROWSER": browser},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=8)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        result = json.loads(stdout)
        self.assertIsNotNone(result["task_page_url"])
        self.assertEqual(result["telemetry"]["launch_result"], "timed_out")
        self.assertEqual(stderr, "")

    def test_production_spellings_cannot_bypass_portal_validation(self) -> None:
        for environment in ("Prod", "PROD", "production", " Production ", "prod "):
            with self.subTest(environment=environment):
                opener = mock.Mock()
                with self.assertRaises(ValueError):
                    launch_task_page.launch_task_page(
                        args(environment=environment, source_url="http://portal.example.test"),
                        opener,
                    )
                opener.assert_not_called()
                result = launch_task_page.launch_task_page(
                    args(environment=environment, no_open=True),
                )
                self.assertTrue(result["task_page_url"].startswith(
                    "https://app.fabric.microsoft.com/",
                ))
                self.assertEqual(result["telemetry"]["environment"], "prod")

    def test_pasted_surrounding_whitespace_is_trimmed(self) -> None:
        for whitespace in (" ", "\n", "\r\n", "\t"):
            with self.subTest(whitespace=whitespace):
                result = launch_task_page.launch_task_page(args(
                    source_url=f"{whitespace}https://app.fabric.microsoft.com{whitespace}",
                    no_open=True,
                ))
                self.assertTrue(result["task_page_url"].startswith(
                    "https://app.fabric.microsoft.com/",
                ))

    def test_production_rejects_untrusted_portal_urls(self) -> None:
        for source_url in (
            "https://portal.example.test",
            "http://app.fabric.microsoft.com",
            "https://app.fabric.microsoft.com:444",
            "https://user@app.fabric.microsoft.com",
            "https://app.fabric.microsoft.com\\@portal.example.test",
            "https://app.fabric.microsoft.com:invalid",
            "https://app.fabric.micro\nsoft.com",
        ):
            with self.subTest(source_url=source_url):
                opener = mock.Mock()
                with self.assertRaises(ValueError):
                    launch_task_page.launch_task_page(args(source_url=source_url), opener)
                opener.assert_not_called()

    def test_percent_encoded_owned_keys_are_replaced_without_changing_values(self) -> None:
        result = launch_task_page.launch_task_page(
            args(source_url=(
                "https://app.powerbi.com/?%73electedPath=old&%70rojectOsmosUX=0"
                "&context=a%2fb+%20c&flag&empty="
            )),
            opener=lambda _: True,
        )
        self.assertTrue(result["task_page_url"].endswith(
            f"?context=a%2fb+%20c&flag&empty=&projectOsmosUX=1"
            f"&selectedPath=ProjectOsmos%2F{TASK_ID}"
        ))

    def test_cli_needs_no_enrollment_argument(self) -> None:
        with mock.patch.object(sys, "argv", [
            str(SCRIPT), "--environment", "prod",
            "--workspace-id", WORKSPACE_ID, "--lakehouse-id", LAKEHOUSE_ID,
            "--task-id", TASK_ID, "--no-open",
        ]):
            parsed = launch_task_page.parse_args()
        self.assertFalse(hasattr(parsed, "private_preview_scope"))
        self.assertIsNotNone(launch_task_page.launch_task_page(parsed)["task_page_url"])

    def test_telemetry_contains_no_prompt_content(self) -> None:
        result = launch_task_page.launch_task_page(args(), opener=lambda _: True)

        self.assertEqual(
            set(result["telemetry"]),
            {
                "event_name",
                "cli_originated",
                "task_created",
                "launch_result",
                "fallback_used",
                "workspace_id",
                "task_id",
                "environment",
            },
        )

    def test_private_environment_requires_portal_context(self) -> None:
        with self.assertRaisesRegex(ValueError, "required outside production"):
            launch_task_page.launch_task_page(
                args(environment="test"),
                opener=lambda _: True,
            )


if __name__ == "__main__":
    unittest.main()
