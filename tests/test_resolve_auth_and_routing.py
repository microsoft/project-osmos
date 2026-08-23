from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "project-osmos" / "scripts" / "resolve-auth-and-routing.py"
DASHBOARD_POLLER_REFERENCE = REPO_ROOT / "skills" / "project-osmos" / "references" / "dashboard-poller.md"

HOME_TENANT_ID = "11111111-1111-4111-8111-111111111111"
RESOURCE_TENANT_ID = "22222222-2222-4222-8222-222222222222"
CASE_TENANT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
WORKSPACE_ID = "33333333-3333-4333-8333-333333333333"
LAKEHOUSE_ID = "44444444-4444-4444-8444-444444444444"
CAPACITY_ID = "55555555-5555-4555-8555-555555555555"


def load_resolver():
    spec = importlib.util.spec_from_file_location("project_osmos_auth_resolver", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load resolver from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


resolver = load_resolver()


class ResourceTenantSelectionTests(unittest.TestCase):
    def test_current_session_is_used_when_resource_tenant_is_omitted(self) -> None:
        commands: list[list[str]] = []

        def fake_check_output(command: list[str], *, text: bool) -> str:
            self.assertTrue(text)
            commands.append(command)
            return "bearer-token\n"

        resource_tenant_id = resolver.select_resource_tenant_id(None, None)
        with mock.patch.object(resolver.subprocess, "check_output", side_effect=fake_check_output):
            token = resolver.get_bearer_token(resource_tenant_id, resolver.PBI_RESOURCE)

        self.assertEqual(token, "bearer-token")
        self.assertIsNone(resource_tenant_id)
        self.assertNotIn("--tenant", commands[0])

    def test_resource_tenant_is_used_instead_of_default_home_tenant(self) -> None:
        selected_tenants: list[str] = []

        def fake_check_output(command: list[str], *, text: bool) -> str:
            self.assertTrue(text)
            selected_tenant = HOME_TENANT_ID
            if "--tenant" in command:
                selected_tenant = command[command.index("--tenant") + 1]
            selected_tenants.append(selected_tenant)
            return "bearer-token\n"

        resource_tenant_id = resolver.select_resource_tenant_id(RESOURCE_TENANT_ID, None)
        with mock.patch.object(resolver.subprocess, "check_output", side_effect=fake_check_output):
            token = resolver.get_bearer_token(resource_tenant_id, resolver.PBI_RESOURCE)

        self.assertEqual(token, "bearer-token")
        self.assertEqual(selected_tenants, [RESOURCE_TENANT_ID])

    def test_conflicting_resource_and_legacy_tenant_values_are_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "disagree"):
            resolver.select_resource_tenant_id(RESOURCE_TENANT_ID, HOME_TENANT_ID)

    def test_legacy_tenant_argument_remains_a_compatibility_alias(self) -> None:
        self.assertEqual(resolver.select_resource_tenant_id(None, RESOURCE_TENANT_ID), RESOURCE_TENANT_ID)

    def test_invalid_resource_tenant_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid GUID"):
            resolver.select_resource_tenant_id("not-a-guid", None)

    def test_resource_tenant_argument_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = resolver.parse_args(
                [
                    "--workspace-id",
                    WORKSPACE_ID,
                    "--lakehouse-id",
                    LAKEHOUSE_ID,
                    "--output-dir",
                    temp_dir,
                ]
            )

        self.assertIsNone(args.resource_tenant_id)
        self.assertIsNone(args.legacy_tenant_id)


class TargetRoutingTests(unittest.TestCase):
    def test_workspace_and_lakehouse_remain_the_selected_resource_targets(self) -> None:
        args = argparse.Namespace(
            workspace_id=WORKSPACE_ID,
            lakehouse_id=LAKEHOUSE_ID,
            workload_type="SparkCore",
            timeout=30.0,
        )
        calls: list[tuple[str, str, dict[str, object] | None]] = []

        workspace_url = f"{resolver.DEFAULT_FABRIC_API_HOST}/v1/workspaces/{WORKSPACE_ID}"
        lakehouse_url = f"{workspace_url}/lakehouses/{LAKEHOUSE_ID}"
        token_url = f"{resolver.DEFAULT_FABRIC_API_HOST}/metadata/v201606/generatemwctoken"

        responses = {
            workspace_url: resolver.HttpResult(
                status=200,
                body=json.dumps({"id": WORKSPACE_ID, "capacityId": CAPACITY_ID}).encode(),
                headers={},
                url=workspace_url,
            ),
            lakehouse_url: resolver.HttpResult(
                status=200,
                body=json.dumps({"id": LAKEHOUSE_ID}).encode(),
                headers={},
                url=lakehouse_url,
            ),
            token_url: resolver.HttpResult(
                status=200,
                body=json.dumps({"Token": "mwc-token", "TargetUriHost": "spark.example.test"}).encode(),
                headers={},
                url=token_url,
            ),
        }

        def fake_request_json(
            url: str,
            bearer_token: str,
            *,
            timeout: float,
            method: str = "GET",
            payload: dict[str, object] | None = None,
            allow_http_error: bool = False,
        ):
            self.assertEqual(bearer_token, "bearer-token")
            self.assertEqual(timeout, 30.0)
            self.assertEqual(allow_http_error, method == "POST")
            calls.append((url, method, payload))
            return responses[url]

        with mock.patch.object(resolver, "request_json", side_effect=fake_request_json):
            context = resolver.resolve_workspace_context(args, resolver.DEFAULT_FABRIC_API_HOST, "bearer-token")
            token_exchange = resolver.exchange_mwc_token(
                args,
                "bearer-token",
                resolver.DEFAULT_FABRIC_API_HOST,
                context,
            )

        exports, routing, mwc_token = resolver.build_routing_payload(
            args,
            resolver.DEFAULT_FABRIC_API_HOST,
            context,
            token_exchange,
            Path("/tmp/project-osmos-test-token"),
            RESOURCE_TENANT_ID,
        )

        self.assertEqual(
            calls,
            [
                (workspace_url, "GET", None),
                (lakehouse_url, "GET", None),
                (
                    token_url,
                    "POST",
                    {
                        "capacityObjectId": CAPACITY_ID,
                        "workloadType": "SparkCore",
                        "workspaceObjectId": WORKSPACE_ID,
                        "artifactObjectIds": [LAKEHOUSE_ID],
                    },
                ),
            ],
        )
        self.assertEqual(exports["RESOURCE_TENANT_ID"], RESOURCE_TENANT_ID)
        self.assertEqual(exports["TENANT_ID"], RESOURCE_TENANT_ID)
        self.assertEqual(exports["WORKSPACE_ID"], WORKSPACE_ID)
        self.assertEqual(exports["LAKEHOUSE_ID"], LAKEHOUSE_ID)
        self.assertEqual(routing["workspace_id"], WORKSPACE_ID)
        self.assertEqual(routing["lakehouse_id"], LAKEHOUSE_ID)
        self.assertEqual(
            routing["tasks_base"],
            (
                f"https://spark.example.test/webapi/capacities/{CAPACITY_ID}/workloads/SparkCore/"
                f"SparkCoreService/direct/v1/workspaces/{WORKSPACE_ID}/artifacts/{LAKEHOUSE_ID}/aichat"
            ),
        )
        self.assertEqual(mwc_token, "mwc-token")

        current_session_exports, _, _ = resolver.build_routing_payload(
            args,
            resolver.DEFAULT_FABRIC_API_HOST,
            context,
            token_exchange,
            Path("/tmp/project-osmos-test-token"),
            None,
        )
        self.assertEqual(current_session_exports["RESOURCE_TENANT_ID"], "")
        self.assertEqual(current_session_exports["TENANT_ID"], "")


class LegacyEnvironmentCompatibilityTests(unittest.TestCase):
    def tenant_guard_script(self) -> str:
        reference = DASHBOARD_POLLER_REFERENCE.read_text(encoding="utf-8")
        marker = '```bash\n: "${MWC_TOKEN:?set MWC_TOKEN before spawning the poller}"'
        start = reference.index(marker) + len("```bash\n")
        end = reference.index("\n```", start)
        return reference[start:end] + '\nprintf "%s" "$RESOURCE_TENANT_ID"\n'

    def base_environment(self) -> dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            "MWC_TOKEN": "mwc-token",
            "GENERATEMWC_URL": "https://example.test/generatemwctoken",
            "CAPACITY_ID": CAPACITY_ID,
            "WORKSPACE_ID": WORKSPACE_ID,
            "LAKEHOUSE_ID": LAKEHOUSE_ID,
            "TASKS_BASE": "https://example.test/aichat",
            "TASK_ID": "task-id",
        }

    def test_poller_guidance_promotes_legacy_tenant_id(self) -> None:
        environment = self.base_environment()
        environment["TENANT_ID"] = RESOURCE_TENANT_ID

        result = subprocess.run(
            ["bash", "-c", self.tenant_guard_script()],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, RESOURCE_TENANT_ID)

    def test_poller_guidance_allows_current_session_without_tenant_id(self) -> None:
        result = subprocess.run(
            ["bash", "-c", self.tenant_guard_script()],
            cwd=REPO_ROOT,
            env=self.base_environment(),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_poller_guidance_rejects_conflicting_tenant_variables(self) -> None:
        environment = self.base_environment()
        environment["RESOURCE_TENANT_ID"] = RESOURCE_TENANT_ID
        environment["TENANT_ID"] = HOME_TENANT_ID

        result = subprocess.run(
            ["bash", "-c", self.tenant_guard_script()],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("RESOURCE_TENANT_ID and TENANT_ID disagree", result.stderr)

    def test_poller_guidance_rejects_invalid_legacy_tenant_id(self) -> None:
        environment = self.base_environment()
        environment["TENANT_ID"] = "not-a-guid"

        result = subprocess.run(
            ["bash", "-c", self.tenant_guard_script()],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("TENANT_ID must be a valid GUID", result.stderr)

    def test_poller_guidance_canonicalizes_equivalent_tenant_ids(self) -> None:
        environment = self.base_environment()
        environment["RESOURCE_TENANT_ID"] = CASE_TENANT_ID.upper()
        environment["TENANT_ID"] = CASE_TENANT_ID

        result = subprocess.run(
            ["bash", "-c", self.tenant_guard_script()],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, CASE_TENANT_ID)


if __name__ == "__main__":
    unittest.main()
