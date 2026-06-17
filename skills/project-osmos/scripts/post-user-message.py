#!/usr/bin/env python3
"""Post a user follow-up to a Project Osmos task.

The skill operates as a mediator between the human and the Project Osmos task:
every user message intended for the run is POSTed to the task API with
flat `metadata.author_name` / `metadata.author_source` values so the dashboard
can attribute it. The running `dashboard-poller.py` daemon will pick the
message up on its next poll and write it into `state.js`.

Usage:
    post-user-message.py \\
        --base-url   https://.../aichat \\
        --task-id    <uuid> \\
        --token-file <path> \\
        --message    "also dedupe by invoice_id" \\
        [--author-name "user@contoso.com"]   # auto-detected from `az` if omitted
        [--source "copilot-cli"]              # default
        [--auth-scheme "Bearer"]              # default

Exits 0 on 2xx response. Prints the new message id to stdout.

The token is read from `--token-file` (chmod 600 expected) — never argv/env.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


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
    p.add_argument("--auth-scheme", default="Bearer")
    p.add_argument("--timeout", type=float, default=15.0)
    args = p.parse_args()

    try:
        token = args.token_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        print(f"error: unable to read token file {args.token_file}: {exc}", file=sys.stderr)
        return 2
    if not token:
        print("error: token file is empty", file=sys.stderr)
        return 2

    author_name = args.author_name or detect_az_user() or "unknown"
    msg_id = str(uuid.uuid4())
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    payload = {
        "messages": [{
            "id": msg_id,
            "role": "User",
            "content": args.message,
            "timestamp": ts,
            "metadata": {
                # Flat string-valued keys are safest across service versions.
                # The poller normalizes these into entry.author = {name, source}
                # for the dashboard renderer. See references/task-lifecycle.md.
                "author_name": author_name,
                "author_source": args.source,
            },
        }],
    }

    url = f"{args.base_url.rstrip('/')}/{args.task_id}/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"{args.auth_scheme} {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            code = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"error: HTTP {e.code} from orchestrator: {body[:500]}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"error: network failure posting message: {e}", file=sys.stderr)
        return 1

    if not (200 <= code < 300):
        print(f"error: unexpected status {code}", file=sys.stderr)
        return 1

    print(msg_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
