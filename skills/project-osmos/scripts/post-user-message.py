# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Post a user follow-up to a Project Osmos task.

The skill operates as a mediator between the human and the SparkCore orchestrator:
every user message intended for the run is POSTed to the orchestrator with
flat `metadata.author_name` / `metadata.author_source` values so the dashboard
can attribute it without sending the nested metadata shape currently rejected
by deployed SparkCore-direct routes.

Before posting, the helper fetches live task state for context. It posts the
user message, always fetches live status again, then starts exactly one run on
the same task only when the post-message state is not running. An elicitation
response therefore cannot be stranded when the run becomes terminal while the
user is answering, and a message-post failure cannot start a run.

Usage:
    python3 skills/project-osmos/scripts/post-user-message.py \\
        --base-url   https://.../aichat \\
        --task-id    <uuid> \\
        --token-file <path> \\
        --message    "also dedupe by invoice_id" \\
        [--author-name "user@contoso.com"]   # auto-detected from `az` if omitted
        [--source "copilot-cli"]              # default
        [--auth-scheme "mwctoken"]            # default
        [--output json]                       # structured continuation result

Exits 0 only when the message is accepted and any required run start succeeds.
The default output remains the new message ID; `--output json` also reports the
live status decision and whether a poller restart is required.

The token is read from `--token-file` (chmod 600 expected) — never argv/env.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from python_runtime import require_supported_python
from task_status import is_task_running, is_task_terminal, status_label

require_supported_python()


AUTH_BODY_HINTS = ("unauthorized", "token", "invalid_token", "authentication", "auth", "expired")


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def is_auth_failure(self) -> bool:
        if self.status in (401, 403):
            return True
        return self.status == 400 and any(hint in self.text.casefold() for hint in AUTH_BODY_HINTS)


@dataclass(frozen=True)
class ContinuationResult:
    task_id: str
    message_id: str
    status_before: str
    terminal_before: bool
    running_before: bool
    status_after_message: str
    running_after_message: bool
    message_posted: bool
    run_start_attempted: bool
    run_started: bool
    run_active: bool
    run_start_outcome: str
    poller_restart_required: bool


class ContinuationError(RuntimeError):
    """A continuation step failed and must be surfaced to the user."""


def http_request(
    url: str,
    auth_header: str,
    timeout: float,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
) -> HttpResult:
    headers = {"Authorization": auth_header}
    if content_type:
        headers["Content-Type"] = content_type
    if method == "POST" and body is None:
        body = b""
        headers["Content-Length"] = "0"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(response.status, response.read(), url)
    except urllib.error.HTTPError as exc:
        response_body = exc.read() if exc.fp else b""
        return HttpResult(exc.code, response_body, url)
    except (urllib.error.URLError, OSError) as exc:
        detail = f"{type(exc).__name__}: {exc}".encode("utf-8", errors="replace")
        return HttpResult(0, detail, url)


def failure_message(action: str, result: HttpResult) -> str:
    if result.status == 0:
        return f"{action} failed before receiving an HTTP response: {result.text[:500]}"
    category = "authentication failed" if result.is_auth_failure() else f"HTTP {result.status}"
    detail = result.text.strip()
    suffix = f": {detail[:500]}" if detail else ""
    return f"{action} failed ({category}){suffix}"


def parse_task(result: HttpResult, action: str = "live task status lookup") -> dict[str, Any]:
    if not result.ok:
        raise ContinuationError(failure_message(action, result))
    try:
        payload = json.loads(result.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ContinuationError(f"{action} returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContinuationError(f"{action} returned a non-object payload")
    return payload


def build_message_payload(message: str, author_name: str, source: str) -> tuple[str, bytes]:
    msg_id = str(uuid.uuid4())
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payload = {
        "messages": [{
            "id": msg_id,
            "role": "User",
            "content": message,
            "timestamp": timestamp,
            "metadata": {
                "author_name": author_name,
                "author_source": source,
            },
        }],
    }
    return msg_id, json.dumps(payload).encode("utf-8")


def continue_task(
    *,
    base_url: str,
    task_id: str,
    auth_header: str,
    message: str,
    author_name: str,
    source: str,
    timeout: float,
) -> ContinuationResult:
    """Post a follow-up and start one same-task run only when no run is active."""
    task_url = f"{base_url.rstrip('/')}/{task_id}"
    task = parse_task(http_request(task_url, auth_header, timeout))
    running_before = is_task_running(task)
    terminal_before = is_task_terminal(task)
    normalized_status = status_label(task.get("status"))

    msg_id, body = build_message_payload(message, author_name, source)
    message_result = http_request(
        f"{task_url}/messages",
        auth_header,
        timeout,
        method="POST",
        body=body,
        content_type="application/json",
    )
    if not message_result.ok:
        raise ContinuationError(failure_message("user message post", message_result))

    task_after_message = parse_task(
        http_request(task_url, auth_header, timeout),
        "post-message status recheck",
    )
    running_after_message = is_task_running(task_after_message)
    status_after_message = status_label(task_after_message.get("status"))

    run_start_attempted = False
    run_started = False
    run_active = running_after_message
    run_start_outcome = "not_needed"
    poller_restart_required = running_after_message and not running_before
    if not running_after_message:
        run_start_attempted = True
        run_result = http_request(f"{task_url}/run", auth_header, timeout, method="POST")
        if run_result.ok:
            run_started = True
            run_active = True
            run_start_outcome = "started"
            poller_restart_required = True
        elif run_result.status == 409:
            conflict_task = parse_task(
                http_request(task_url, auth_header, timeout),
                "run-conflict status lookup",
            )
            if not is_task_running(conflict_task):
                conflict_status = status_label(conflict_task.get("status"))
                raise ContinuationError(
                    f"user message {msg_id} was posted, but same-task run start returned HTTP 409 "
                    f"and the live task is {conflict_status}; no second run request was sent"
                )
            status_after_message = status_label(conflict_task.get("status"))
            running_after_message = True
            run_active = True
            run_start_outcome = "already_running"
            poller_restart_required = True
        else:
            detail = failure_message("same-task run start", run_result)
            raise ContinuationError(f"user message {msg_id} was posted, but {detail}")

    return ContinuationResult(
        task_id=task_id,
        message_id=msg_id,
        status_before=normalized_status,
        terminal_before=terminal_before,
        running_before=running_before,
        status_after_message=status_after_message,
        running_after_message=running_after_message,
        message_posted=True,
        run_start_attempted=run_start_attempted,
        run_started=run_started,
        run_active=run_active,
        run_start_outcome=run_start_outcome,
        poller_restart_required=poller_restart_required,
    )


def detect_az_user() -> str | None:
    """Best-effort: ask `az` for the signed-in user. Returns None on any failure."""
    if shutil.which("az") is None:
        return None
    try:
        out = subprocess.run(
            ["az", "account", "show", "--query", "user.name", "-o", "tsv"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        name = (out.stdout or "").strip()
        return name or None
    except (subprocess.SubprocessError, OSError):
        return None


def read_private_token_file(path: Path) -> str:
    with path.open(encoding="utf-8") as token_file:
        if os.name != "nt" and stat.S_IMODE(os.fstat(token_file.fileno()).st_mode) & 0o077:
            raise PermissionError("--token-file must not be accessible by group or other users")
        return token_file.read().strip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="Task base URL up to and including /aichat")
    p.add_argument("--task-id", required=True)
    p.add_argument("--token-file", required=True, type=Path)
    p.add_argument("--message", required=True)
    p.add_argument("--author-name", default=None,
                   help="Override the author name. Defaults to `az account show --query user.name`.")
    p.add_argument("--source", default="copilot-cli",
                   help="Source label for the author (default: copilot-cli).")
    p.add_argument("--auth-scheme", default="mwctoken")
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--output", choices=("id", "json"), default="id",
                   help="Print only the message ID (default) or a structured continuation result.")
    args = p.parse_args()

    try:
        token = read_private_token_file(args.token_file)
    except OSError as exc:
        print(f"error: unable to read token file {args.token_file}: {exc}", file=sys.stderr)
        return 2
    if not token:
        print("error: token file is empty", file=sys.stderr)
        return 2

    try:
        result = continue_task(
            base_url=args.base_url,
            task_id=args.task_id,
            auth_header=f"{args.auth_scheme} {token}",
            message=args.message,
            author_name=args.author_name or detect_az_user() or "unknown",
            source=args.source,
            timeout=args.timeout,
        )
    except ContinuationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), sort_keys=True) if args.output == "json" else result.message_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
