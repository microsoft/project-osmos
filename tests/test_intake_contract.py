from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_launch_task_page import launch_task_page


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "project-osmos"
INTAKE_PATH = SKILL_DIR / "references" / "intake-questionnaire.md"
SKILL_PATH = SKILL_DIR / "SKILL.md"
TASK_STATE_REFERENCE_PATH = SKILL_DIR / "references" / "task-state.md"
URL_PARSING_PATH = SKILL_DIR / "references" / "url-parsing.md"
POLLER_PATH = SKILL_DIR / "scripts" / "dashboard-poller.py"
LENGTH_CHECKER_PATH = SKILL_DIR / "scripts" / "check-instruction-length.py"
OVERSIZED_REFERENCE_PATH = SKILL_DIR / "references" / "oversized-instructions.md"
TASK_LIFECYCLE_PATH = SKILL_DIR / "references" / "task-lifecycle.md"


def load_dashboard_poller():
    module_name = "project_osmos_dashboard_poller_test"
    original_task_status = sys.modules.get("task_status")
    original_runtime = sys.modules.get("python_runtime")
    scripts_dir = POLLER_PATH.parent
    try:
        with mock.patch.object(sys, "path", [str(scripts_dir), *sys.path]):
            spec = importlib.util.spec_from_file_location(module_name, POLLER_PATH)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"could not load poller from {POLLER_PATH}")
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


dashboard_poller = load_dashboard_poller()


def load_instruction_length_checker():
    module_name = "project_osmos_instruction_length_test"
    original_runtime = sys.modules.get("python_runtime")
    try:
        with mock.patch.object(sys, "path", [str(LENGTH_CHECKER_PATH.parent), *sys.path]):
            spec = importlib.util.spec_from_file_location(module_name, LENGTH_CHECKER_PATH)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"could not load checker from {LENGTH_CHECKER_PATH}")
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


instruction_length = load_instruction_length_checker()


class IntakeContractTests(unittest.TestCase):
    def test_public_intake_parser_matches_launcher_portal_policy(self) -> None:
        public_reference = self.url_parsing
        stripper = REPO_ROOT / ".github" / "public" / "strip-internal-blocks.py"
        if stripper.exists():
            spec = importlib.util.spec_from_file_location("public_block_stripper", stripper)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            public_reference = module.BLOCK_RE.sub("", public_reference)
        self.assertNotRegex(public_reference.lower(), r"<[/]?internal>")
        public_reference = public_reference.split("## Task page URL construction", 1)[0]
        blocks = re.findall(r"```python\n(.*?)```", public_reference, re.DOTALL)
        namespace: dict[str, object] = {}
        exec("\n".join(blocks), namespace)
        parse = namespace["parse_fabric_url"]
        self.assertEqual(namespace["SUPPORTED_HOSTS"], launch_task_page.PRODUCTION_HOSTS)
        path = (
            "/groups/11111111-1111-1111-1111-111111111111"
            "/lakehouses/22222222-2222-2222-2222-222222222222"
        )
        for origin in (
            "http://app.fabric.microsoft.com",
            "ftp://app.fabric.microsoft.com",
            "https://app.fabric.microsoft.com:444",
            "https://user@app.fabric.microsoft.com",
            "https://app.fabric.microsoft.com:invalid",
            "https://portal.example.test",
            "https://app.fabric.microsoft.com\n",
            "https://app.fabric.microsoft.com\\",
        ):
            with self.subTest(origin=origin):
                self.assertIsNone(parse(origin + path))
                with self.assertRaises(ValueError):
                    launch_task_page.portal_parts("prod", origin + path, None)
        for origin in (
            *(f"https://{host}" for host in launch_task_page.PRODUCTION_HOSTS),
            "https://app.powerbi.com:443",
            "app.fabric.microsoft.com",
        ):
            with self.subTest(origin=origin):
                self.assertEqual(
                    parse(origin + path)["lakehouse_id"],
                    "22222222-2222-2222-2222-222222222222",
                )
                self.assertEqual(
                    launch_task_page.portal_parts("prod", origin + path, None)[0],
                    "https",
                )
        for whitespace in (" ", "\n", "\r\n", "\t"):
            with self.subTest(whitespace=whitespace):
                self.assertIsNotNone(parse(
                    whitespace + "https://app.fabric.microsoft.com" + path + whitespace,
                ))
        query = "context=https://example.test/path&keep=a%2fb+%20c"
        for host in launch_task_page.PRODUCTION_HOSTS:
            with self.subTest(host=host, query=query):
                url = f"{host}{path}?{query}"
                self.assertEqual(
                    parse(url)["lakehouse_id"],
                    "22222222-2222-2222-2222-222222222222",
                )
                self.assertEqual(
                    launch_task_page.portal_parts("prod", url, None),
                    ("https", host, query),
                )

    def test_task_page_error_run_card_has_explicit_unavailable_value(self) -> None:
        self.assertIn(
            "set the run card's `Task page` value to `Unavailable (URL validation failed)`",
            self.skill,
        )
        self.assertIn("never print an empty link or literal `<task_page_url>`", self.skill)

    @classmethod
    def setUpClass(cls) -> None:
        cls.intake = INTAKE_PATH.read_text(encoding="utf-8")
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.task_state = TASK_STATE_REFERENCE_PATH.read_text(encoding="utf-8")
        cls.url_parsing = URL_PARSING_PATH.read_text(encoding="utf-8")
        cls.oversized_reference = OVERSIZED_REFERENCE_PATH.read_text(encoding="utf-8")
        cls.task_lifecycle = TASK_LIFECYCLE_PATH.read_text(encoding="utf-8")

    def test_explicit_requirements_precede_task_type_fallbacks(self) -> None:
        self.assertIn("Derive requirements before applying defaults", self.intake)
        self.assertIn("Explicit user requirement", self.intake)
        self.assertIn("Task-type fallback", self.intake)
        self.assertIn(
            "Never let a task-type fallback override an explicit user requirement",
            self.intake,
        )
        self.assertNotIn("binding — overrides anything below", self.intake)

    def test_rerun_conflict_is_blocked_before_dispatch(self) -> None:
        self.assertIn("Step 2b — resolve dependent values and reconcile before dispatch", self.intake)
        self.assertIn("`counts unchanged`", self.intake)
        self.assertIn("`fail if target already populated`", self.intake)
        self.assertIn("do not use precedence and do not dispatch", self.intake)
        self.assertIn("reconcile idempotently", self.intake)
        self.assertIn("stable key columns or a partition scope", self.intake)

    def test_fail_if_populated_is_not_an_approval_gate(self) -> None:
        expected = (
            "This is a terminal safety policy, not a request for approval, "
            "and a confirmation message does not override it."
        )
        self.assertIn(expected, self.intake)
        self.assertIn("Only a gate explicitly listed under `Approval gates`", self.skill)

    def test_handoff_is_self_contained_and_per_target(self) -> None:
        required = (
            "## Execution plan",
            "mode=autonomous",
            "gates=<none|explicit gate>",
            "Resources:",
            "Writes:",
            "safety=<choice> (<concise behavior>)",
            "rerun=<choice> (<exact populated-target behavior>",
            "approval=<none|gate>",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.intake)
        self.assertIn("Send the exact same composed", self.skill)
        self.assertIn("never send bare", self.skill)
        self.assertIn("cap generated", self.skill)
        self.assertIn("`## Execution plan`", self.skill)
        normalized_skill = " ".join(self.skill.split())
        self.assertIn(
            "the verbatim `## User outcome` first and the self-contained "
            "`## Execution plan` immediately below it",
            normalized_skill,
        )
        command = '"${PYTHON_RUNNER[@]}" skills/project-osmos/scripts/check-instruction-length.py'
        self.assertIn(command, self.skill)
        self.assertIn(
            command,
            self.intake,
        )
        self.assertIn("--limit", self.skill)
        self.assertIn("9500", self.skill)

    def test_pick_letters_start_at_a(self) -> None:
        self.assertIn("The `Pick` letters start at\n`a`", self.intake)
        self.assertNotIn("0-indexed alphabetically", self.intake)

    def test_reasoning_effort_always_defaults_to_medium(self) -> None:
        self.assertIn("Always recommend `medium`", self.intake)
        self.assertIn("Do not infer `low`, `high`, or `xhigh`", self.intake)
        self.assertIn(
            "| **Question 8** Reasoning effort | `medium` | `medium` | `medium` | `medium` | `medium` | `medium` |",
            self.intake,
        )
        self.assertNotIn("derive `high` effort", self.intake)
        self.assertIn("effort=medium", self.intake)

    def test_guidewire_example_uses_idempotent_per_target_semantics(self) -> None:
        self.assertIn("Attempt#1-Guidewire Claims only", self.intake)
        self.assertIn("bronze_guidewire_claim", self.intake)
        self.assertIn("gold_claim_starter", self.intake)
        example = self.intake.split(
            "### Compact Guidewire example",
            maxsplit=1,
        )[1]
        self.assertEqual(example.count("rerun=reconcile idempotently"), 2)
        self.assertEqual(example.count("state=missing"), 2)
        self.assertEqual(example.count("key=claim_id"), 2)
        self.assertIn("gates=none", example)
        self.assertIn("name=agent choice", example)
        self.assertNotIn("<resolved claim identifier column>", example)
        handoff = example.split("```text", maxsplit=1)[1].split(
            "```",
            maxsplit=1,
        )[0]
        self.assertLess(
            handoff.index("## User outcome"),
            handoff.index("## Execution plan"),
        )
        execution_plan = handoff.split("## Execution plan", maxsplit=1)[1]
        self.assertLessEqual(len(execution_plan), 2500)

    def test_handoff_budget_preserves_user_text_and_drops_generated_verbose_content(self) -> None:
        self.assertIn("at most **10,000 characters**", self.intake)
        self.assertIn("**9,500 characters or fewer**", self.intake)
        self.assertIn("at most **2,500 characters**", self.intake)
        self.assertIn("remove generated verbosity—not user text", self.intake)
        self.assertIn("Do not include unselected options", self.intake)
        self.assertIn("do not paste the full questionnaire definition", self.intake)

    def test_oversized_handoff_uses_lossless_onelake_reference(self) -> None:
        self.assertIn("oversized instruction fallback", self.skill)
        self.assertIn("never truncate, paraphrase, or ask the user to shorten it", self.skill)
        self.assertIn("Files/ProjectOsmos/tasks/$TASK_ID/instruction.md", self.oversized_reference)
        self.assertIn("Read the entire UTF-8 file before planning or execution", self.oversized_reference)
        self.assertIn("If upload fails, stop before task creation", self.oversized_reference)
        self.assertIn("handoff_mode: onelake_reference", self.oversized_reference)
        self.assertIn("[oversized instruction fallback](oversized-instructions.md)", self.task_lifecycle)
        self.assertNotIn("ask the user to shorten nonessential outcome context", self.intake)

    def test_intake_action_menu_has_only_four_choices(self) -> None:
        for choice in (
            "**Accept recommendations**",
            "**Change a setting**",
            "**Explain a setting**",
            "**Walk through every question**",
        ):
            with self.subTest(choice=choice):
                self.assertIn(choice, self.intake)
        self.assertIn("exactly these four visible", self.intake)
        self.assertIn("Do not enumerate `change 1` through `change 8`", self.intake)
        self.assertIn("second `ask_user` prompt", self.intake)

    def test_accept_recommendations_is_final_task_authorization(self) -> None:
        self.assertIn("final authorization", self.intake)
        self.assertIn("not display another confirmation", self.intake)
        self.assertIn("The recommendation card is the review-and-consent surface", self.intake)
        self.assertIn("acceptance in the intake step is the authorization", self.skill)

    def test_every_user_gets_fabric_task_page(self) -> None:
        self.assertIn("For every user", self.skill)
        self.assertIn("No enrollment signal is required", self.skill)
        self.assertIn("Print `task_page_url` as `Task page`", self.skill)
        self.assertIn("| Task page | `<task_page_url>` (clickable Fabric link) |", self.skill)
        self.assertNotIn("--private-preview-scope", self.skill)

    def test_local_display_removed_but_headless_poller_retained(self) -> None:
        self.assertFalse((SKILL_DIR / "assets" / "dashboard.html").exists())
        self.assertFalse((SKILL_DIR / "references" / "dashboard.md").exists())
        self.assertNotIn("references/dashboard.md", self.skill)
        self.assertNotIn("| Dashboard |", self.skill)
        self.assertNotIn("`state.js`", self.skill)
        self.assertIn("For every task, spawn `scripts/dashboard-poller.py`", self.skill)
        self.assertIn("do not depend on either browser page being open", self.skill)
        for path in SKILL_DIR.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".py", ".html", ".js"}:
                with self.subTest(path=path.relative_to(SKILL_DIR)):
                    text = path.read_text(encoding="utf-8")
                    for removed in ("state.js", "dashboard.html", "references/dashboard.md"):
                        self.assertNotRegex(text, re.escape(removed) + r"(?![a-zA-Z0-9])")

    def test_follow_up_keeps_recovery_without_duplicate_workers(self) -> None:
        self.assertIn("poller_restart_required: true", self.skill)
        self.assertIn("Reuse a healthy existing process", self.skill)
        self.assertIn("do not launch duplicate recovery workers", self.skill)

    def test_browser_failure_keeps_link_and_recovery(self) -> None:
        self.assertIn("launch is non-fatal", self.url_parsing)
        self.assertIn("Browser opening is bounded to three seconds", self.url_parsing)
        self.assertIn("continue starting the headless recovery poller", self.url_parsing)
        self.assertIn("Never substitute a local HTML path for the Fabric link", self.skill)

    def test_url_validation_failure_does_not_gate_recovery(self) -> None:
        self.assertIn("URL validation fails (exit 2)", self.url_parsing)
        self.assertIn("start the recovery poller anyway", self.url_parsing)
        self.assertIn("start recovery anyway", self.skill)
        self.assertIn("rerun the helper for the same task", self.skill)
        poller_reference = (SKILL_DIR / "references" / "dashboard-poller.md").read_text(
            encoding="utf-8",
        )
        self.assertIn("browser launch or URL validation failed", poller_reference)

    def test_task_state_keeps_contract_provenance_and_loop_state(self) -> None:
        for text in (
            "| `contract_version` | `2` |",
            "contract_sha256",
            "selection_source",
            "executable_meaning",
            "possible_elicitation_loop",
            "elicitation_loop_count",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.task_state)


class HeadlessRecoveryTests(unittest.TestCase):
    def test_state_and_terminal_preserve_context_without_ui_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            state = {
                "task": {"id": "task-1", "task_page_url": "https://app.fabric.microsoft.com/"},
                "intake": {"contract_version": 2, "contract_sha256": "accepted-spec"},
                "spec": "## Execution plan",
                "messages": [{"id": "a1", "role": "assistant", "text": "Done"}],
                "artifacts": {"notebook": None, "table": None},
            }
            terminal = {"status": "Completed", "reason": "terminal_status"}
            dashboard_poller.write_terminal_state(state_dir, state, terminal)
            restored = dashboard_poller.load_state(state_dir / "state.json")
            self.assertEqual(restored["intake"], state["intake"])
            self.assertEqual(restored["spec"], state["spec"])
            self.assertEqual(restored["task"], state["task"])
            self.assertEqual(restored["messages"], state["messages"])
            self.assertEqual(restored["artifacts"], state["artifacts"])
            self.assertEqual(restored["terminal"]["reason"], "terminal_status")
            self.assertEqual(
                {path.name for path in state_dir.iterdir()}, {"state.json", "terminal.json"},
            )

    def test_daemon_retries_same_task_without_a_browser_or_html(self) -> None:
        error = "Run failed while executing statements on the Spark session. Please retry."
        base_url = "https://example.invalid/tasks"
        task_id = "task-1"
        messages = {"messages": [
            {"id": "a1", "role": "Assistant", "content": "Checking data"},
            {"id": "t1", "role": "Tool", "content": "Tool detail"},
        ]}
        failed = {"status": "Failed", "runDetails": {
            "operationId": "operation-1", "completedAt": "2026-09-09T12:00:00Z",
            "errorMessage": error,
        }}
        completed = {"status": "Completed", "runDetails": {
            "operationId": "operation-2", "completedAt": "2026-09-09T12:01:00Z",
        }}

        def response(payload):
            return dashboard_poller.HttpResult(200, json.dumps(payload).encode())

        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            state = {
                "task": {"id": task_id},
                "intake": {"contract_version": 2, "contract_sha256": "accepted-spec"},
                "spec": "## Execution plan",
                "messages": [],
            }
            dashboard_poller.write_state(state_dir, state)
            with (
                mock.patch.object(sys, "argv", [
                    str(POLLER_PATH), "--base-url", base_url, "--task-id", task_id,
                    "--state-dir", directory, "--max-runtime", "5",
                ]),
                mock.patch.object(dashboard_poller, "_resolve_initial_token", return_value="test-token"),
                mock.patch.object(dashboard_poller, "_install_signal_handlers"),
                mock.patch.object(dashboard_poller, "sleep_interruptibly"),
                mock.patch.object(dashboard_poller, "log"),
                mock.patch.object(dashboard_poller, "http_request", side_effect=[
                    response(messages), response(failed),
                    dashboard_poller.HttpResult(202, b""),
                    response(messages), response(completed),
                ]) as request,
                mock.patch("webbrowser.open", side_effect=AssertionError("browser must not be used")),
            ):
                self.assertEqual(dashboard_poller.main(), 0)

            posts = [call for call in request.call_args_list if call.kwargs.get("method") == "POST"]
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0].args[0], f"{base_url}/{task_id}/run")
            restored = dashboard_poller.load_state(state_dir / "state.json")
            self.assertEqual(restored["terminal"]["status"], "Completed")
            self.assertEqual(restored["terminal"]["auto_retries_total"], 1)
            self.assertEqual(restored["intake"], state["intake"])
            self.assertEqual(restored["spec"], state["spec"])
            self.assertEqual(len(restored["messages"]), 1)
            audit = [json.loads(line) for line in (state_dir / "messages.ndjson").read_text().splitlines()]
            self.assertEqual([message["id"] for message in audit], ["a1", "t1"])
            self.assertFalse((state_dir / "poller.pid").exists())
            self.assertEqual(
                {path.name for path in state_dir.iterdir()},
                {"state.json", "terminal.json", "messages.ndjson"},
            )


class InstructionLengthTests(unittest.TestCase):
    def test_measure_accepts_instruction_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instruction.txt"
            path.write_text("x" * 9500, encoding="utf-8")

            result = instruction_length.measure(path, 9500)

        self.assertTrue(result["within_limit"])
        self.assertEqual(result["characters"], 9500)
        self.assertEqual(result["remaining"], 0)

    def test_measure_rejects_instruction_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instruction.txt"
            path.write_text("x" * 9501, encoding="utf-8")

            result = instruction_length.measure(path, 9500)

        self.assertFalse(result["within_limit"])
        self.assertEqual(result["remaining"], -1)


class ElicitationLoopTests(unittest.TestCase):
    question_1 = (
        "Please confirm whether the original task contains a user-controlled gate. "
        "Does it require confirmation before any non-read-only action?"
    )
    question_2 = (
        "Please clarify whether the original task has a user controlled gate. "
        "Must I get your approval before taking a non read only action?"
    )
    question_3 = (
        "Does the original task contain a user-controlled gate requiring your "
        "confirmation or approval before a non-read-only action?"
    )

    def test_semantically_equivalent_questions_across_user_replies_are_flagged(self) -> None:
        polled = [
            {"id": "a1", "role": "assistant", "content": self.question_1},
            {"id": "u1", "role": "user", "content": "No gate. Proceed."},
            {"id": "a2", "role": "assistant", "content": self.question_2},
            {"id": "u2", "role": "user", "content": "I already answered."},
            {"id": "a3", "role": "assistant", "content": self.question_3},
        ]

        messages, stats = dashboard_poller.merge_messages([], polled)

        self.assertTrue(stats.possible_elicitation_loop)
        self.assertEqual(stats.elicitation_loop_count, 3)
        self.assertTrue(messages[-1]["possible_elicitation_loop"])

    def test_visible_assistant_progress_resets_elicitation_count(self) -> None:
        messages, stats = dashboard_poller.merge_messages(
            [],
            [
                {"id": "a1", "role": "assistant", "content": self.question_1},
                {"id": "u1", "role": "user", "content": "No gate."},
                {"id": "a2", "role": "assistant", "content": self.question_2},
                {"id": "p1", "role": "assistant", "content": "Validated the source schema."},
                {"id": "a3", "role": "assistant", "content": self.question_3},
            ],
        )

        self.assertFalse(stats.possible_elicitation_loop)
        self.assertFalse(messages[-1].get("possible_elicitation_loop", False))

    def test_progress_after_loop_clears_batch_warning(self) -> None:
        messages, stats = dashboard_poller.merge_messages(
            [],
            [
                {"id": "a1", "role": "assistant", "content": self.question_1},
                {"id": "a2", "role": "assistant", "content": self.question_1},
                {"id": "a3", "role": "assistant", "content": self.question_1},
                {
                    "id": "p1",
                    "role": "assistant",
                    "content": "Validated the source schema.",
                    "createdAt": "2026-08-26T12:01:00Z",
                },
            ],
        )

        self.assertTrue(messages[0]["possible_elicitation_loop"])
        self.assertFalse(stats.possible_elicitation_loop)
        self.assertEqual(stats.elicitation_loop_count, 0)
        self.assertIsNone(stats.elicitation_loop_text)

        recovery = dashboard_poller.RecoveryState(
            last_progress_at="2026-08-26T12:00:00Z",
            possible_elicitation_loop=True,
            elicitation_loop_count=3,
            elicitation_loop_text=self.question_1,
        )
        dashboard_poller._update_progress_and_trigger(recovery, stats)

        self.assertFalse(recovery.possible_elicitation_loop)
        self.assertEqual(recovery.last_progress_at, "2026-08-26T12:01:00Z")

    def test_three_consecutive_exact_questions_are_collapsed_and_flagged(self) -> None:
        polled = [
            {"id": f"a{index}", "role": "assistant", "content": self.question_1}
            for index in range(1, 4)
        ]

        messages, stats = dashboard_poller.merge_messages([], polled)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["repeats"], 3)
        self.assertTrue(messages[0]["possible_elicitation_loop"])
        self.assertTrue(stats.possible_elicitation_loop)
        self.assertIsNone(stats.latest_progress_assistant_ts)
        self.assertIsNone(stats.latest_progress_assistant_seq)

        recovery = dashboard_poller.RecoveryState(
            last_progress_at="2026-08-26T12:00:00Z"
        )
        dashboard_poller._update_progress_and_trigger(recovery, stats)
        self.assertEqual(recovery.last_progress_at, "2026-08-26T12:00:00Z")

    def test_paraphrase_then_exact_duplicate_counts_all_three_questions(self) -> None:
        polled = [
            {"id": "a1", "role": "assistant", "content": self.question_1},
            {"id": "u1", "role": "user", "content": "No gate."},
            {"id": "a2", "role": "assistant", "content": self.question_2},
            {"id": "a3", "role": "assistant", "content": self.question_2},
        ]

        messages, stats = dashboard_poller.merge_messages([], polled)

        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[-1]["repeats"], 2)
        self.assertTrue(messages[-1]["possible_elicitation_loop"])
        self.assertEqual(stats.elicitation_loop_count, 3)
        self.assertIsNone(stats.latest_progress_assistant_ts)
        self.assertIsNone(stats.latest_progress_assistant_seq)

    def test_short_approval_paraphrases_share_one_intent(self) -> None:
        questions = ("Do you approve?", "May I proceed?", "Can I continue?")
        messages, stats = dashboard_poller.merge_messages(
            [],
            [
                {
                    "id": f"a{index}",
                    "role": "assistant",
                    "content": question,
                }
                for index, question in enumerate(questions, start=1)
            ],
        )

        self.assertEqual(len(messages), 3)
        self.assertTrue(stats.possible_elicitation_loop)
        self.assertEqual(stats.elicitation_loop_count, 3)

    def test_plural_gate_paraphrases_share_one_intent(self) -> None:
        questions = (
            "Are there any gates?",
            "Is this gated?",
            "Does this require a gate?",
        )

        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(
                    dashboard_poller.canonical_elicitation_intent(question),
                    "approval_gate",
                )

    def test_elicitation_loop_does_not_advance_progress(self) -> None:
        recovery = dashboard_poller.RecoveryState(
            last_progress_at="2026-08-26T12:00:00Z"
        )
        stats = dashboard_poller.MergeStats(
            assistant_appended=1,
            latest_assistant_ts="2026-08-26T12:01:00Z",
            possible_elicitation_loop=True,
            elicitation_loop_count=3,
            elicitation_loop_text=self.question_3,
        )

        dashboard_poller._update_progress_and_trigger(recovery, stats)

        self.assertEqual(recovery.last_progress_at, "2026-08-26T12:00:00Z")
        self.assertTrue(recovery.possible_elicitation_loop)
        self.assertEqual(recovery.elicitation_loop_count, 3)

    def test_valid_progress_in_same_batch_still_advances(self) -> None:
        existing = [
            {"id": "a1", "role": "assistant", "text": self.question_1, "seq": 0},
            {"id": "u1", "role": "user", "text": "No gate.", "seq": 1},
            {"id": "a2", "role": "assistant", "text": self.question_2, "seq": 2},
        ]
        polled = [
            {
                "id": "a-progress",
                "role": "assistant",
                "content": "Validated the source schema and row count.",
                "createdAt": "2026-08-26T12:01:00Z",
            },
            {
                "id": "a3",
                "role": "assistant",
                "content": self.question_3,
                "createdAt": "2026-08-26T12:02:00Z",
            },
        ]
        _, stats = dashboard_poller.merge_messages(existing, polled)
        recovery = dashboard_poller.RecoveryState(
            last_progress_at="2026-08-26T12:00:00Z"
        )

        dashboard_poller._update_progress_and_trigger(recovery, stats)

        self.assertFalse(recovery.possible_elicitation_loop)
        self.assertEqual(recovery.last_progress_at, "2026-08-26T12:02:00Z")


if __name__ == "__main__":
    unittest.main()
