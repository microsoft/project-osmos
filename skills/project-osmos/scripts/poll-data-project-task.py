#!/usr/bin/env python3
"""Poll a Project Osmos task and print new assistant messages."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


TERMINAL_STRINGS = {"completed", "failed", "cancelled", "canceled"}
STATUS_BY_CODE = {0: "Created", 1: "Running", 2: "Cancelling", 3: "Cancelled", 4: "Completed", 5: "Failed"}
ASSISTANT_ROLES = {1, "1", "Assistant", "assistant"}


def request_json(url: str, auth_header: str, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Authorization": auth_header})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def is_terminal(status: Any) -> bool:
    label: str
    if isinstance(status, str):
        stripped = status.strip()
        if stripped.isdigit():
            label = STATUS_BY_CODE.get(int(stripped), stripped)
        else:
            label = stripped
    elif isinstance(status, int) and not isinstance(status, bool):
        label = STATUS_BY_CODE.get(status, str(status))
    else:
        return False
    return label.strip().lower() in TERMINAL_STRINGS


def iter_assistant_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return []
    return [msg for msg in messages if isinstance(msg, dict) and msg.get("role") in ASSISTANT_ROLES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Task base URL without trailing task ID")
    parser.add_argument("--task-id", required=True, help="Project Osmos task ID")
    parser.add_argument("--token-env", default="PROJECT_OSMOS_TOKEN", help="Environment variable containing the task authorization token")
    parser.add_argument("--auth-scheme", default="Bearer", help="Authorization scheme, such as Bearer")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between polls")
    parser.add_argument("--max-polls", type=int, default=120, help="Maximum poll attempts before exiting")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    args = parser.parse_args()

    token = os.environ.get(args.token_env)
    if not token:
        print(f"Missing token environment variable: {args.token_env}", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    task_url = f"{base_url}/{args.task_id}"
    messages_url = f"{task_url}/messages"
    auth_header = f"{args.auth_scheme} {token}"
    seen_message_ids: set[str] = set()
    last_task: dict[str, Any] = {}

    for attempt in range(1, args.max_polls + 1):
        try:
            messages_payload = request_json(messages_url, auth_header, args.timeout)
            for message in iter_assistant_messages(messages_payload):
                message_id = str(message.get("id") or f"assistant-{attempt}-{len(seen_message_ids)}")
                if message_id in seen_message_ids:
                    continue
                seen_message_ids.add(message_id)
                content = str(message.get("content", "")).strip()
                if content:
                    print(json.dumps({"type": "assistant_message", "id": message_id, "content": content}))

            last_task = request_json(task_url, auth_header, args.timeout)
            status = last_task.get("status")
            run_details = last_task.get("runDetails") if isinstance(last_task.get("runDetails"), dict) else {}
            error_message = run_details.get("errorMessage") if run_details else None
            print(
                json.dumps(
                    {
                        "type": "task_status",
                        "attempt": attempt,
                        "status": status,
                        "operationId": run_details.get("operationId") if run_details else None,
                        "sessionId": run_details.get("sessionId") if run_details else None,
                        "errorMessage": error_message,
                    }
                )
            )

            if is_terminal(status) or error_message:
                break
        except urllib.error.HTTPError as exc:
            print(json.dumps({"type": "http_error", "status": exc.code, "url": exc.url}), file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - surface exact polling failure to the caller
            print(json.dumps({"type": "poll_error", "error": str(exc)}), file=sys.stderr)
            return 1

        interval = args.poll_interval
        run_details = last_task.get("runDetails") if isinstance(last_task.get("runDetails"), dict) else {}
        if isinstance(run_details.get("pollingIntervalSeconds"), (int, float)):
            interval = float(run_details["pollingIntervalSeconds"])
        time.sleep(interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
