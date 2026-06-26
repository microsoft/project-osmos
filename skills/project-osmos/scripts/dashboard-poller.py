# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Dashboard state poller for Project Osmos tasks.

Runs as a detached background process. Polls the SparkCore orchestrator
on an adaptive cadence and rewrites `state.js` / `state.json` /
`messages.ndjson` in the task's `.dataprojects/<task-id>/` directory.

Designed so the LLM agent does not have to stay in a polling loop — see
SKILL.md "Operating contract" for the rationale.

Cadence (adaptive, all configurable):
  - Fast phase   : 15s for the first 90s after spawn (so users see early activity)
  - Base interval: 60s once warm
  - Idle backoff : grow up to --max-interval (default 180s) after consecutive
                   polls with no new messages and no status change
  - Snap back    : reset to base on any new message or status change
  - Terminal     : exit 0 once status is terminal AND no auto-recovery is in
                   progress; on hard ceilings (--max-runtime, --max-auto-retries,
                   --no-progress-window-seconds) write terminal.json with the
                   reason and exit.

Auto-recovery (runs entirely inside the daemon, no agent involvement):

  - Token refresh: SparkCore terminates agent processes near the
    ~60-75 min token expiration window. The daemon proactively re-runs
    `--token-refresh-cmd` every `--token-refresh-interval` seconds
    (default 2700 = 45 min, under the lower bound with margin) and also
    reactively on any auth-class 4xx. Proactive swaps are validated
    against a cheap GET before committing, so a bad refresh cmd cannot
    poison a working session. On unrecoverable auth (no cmd, or refresh
    fails), the daemon enters `auth_broken` state: stops normal polling
    and stops advancing `last_polled_at`. With `--token-refresh-cmd` it
    retries refresh on a short backoff; without one it waits for the
    poller to be respawned with fresh credentials.

  - Auto-retry of the documented Spark statement transient:
    `"Run failed while executing statements on the Spark session. Please retry."`
    When `runDetails.errorMessage` (preferred) or a fresh assistant message
    matches this normalized phrase set, the daemon POSTs to `/{taskId}/run`
    on the same task ID (preserving backend checkpoints) after a backoff
    (30s, 60s, 120s, then 120s flat). Each unique error signature
    (operationId + completedAt + normalized error) is retried at most
    once until a new run identity appears. Hard ceiling:
    --max-auto-retries (default 10). Time-based safety net: if no new
    assistant progress within --no-progress-window-seconds (default
    7200 = 2h, paused while auth-broken), give up.

Run example (the skill spawns it like this):

  nohup python3 dashboard-poller.py \\
      --base-url            "https://.../aichat/v1/.../tasks" \\
      --task-id             "<guid>" \\
      --state-dir           ".dataprojects/<guid>" \\
      --token-file          ".dataprojects/<guid>/mwc-token" \\
      --auth-scheme         "mwctoken" \\
      --interval            60 \\
      --max-interval        180 \\
      --token-refresh-cmd   "python3 .dataprojects/<guid>/refresh-mwc-token.py" \\
      > .dataprojects/<guid>/poller.log 2>&1 &
  echo $! > .dataprojects/<guid>/poller.pid
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TERMINAL_STRINGS = {"completed", "failed", "cancelled", "canceled"}

# Normalized phrase tokens for the documented retryable Spark statement
# transient. We require *all* of these phrases, in order, after lowercasing
# and collapsing whitespace. Strict enough to avoid false positives on
# unrelated errors; tolerant enough to survive minor backend wording drift
# (e.g. trailing period present/absent).
RETRYABLE_PHRASES = ("run failed", "executing statements", "spark session", "retry")

# Sentinel substrings that confirm a 400 is auth-related (case-insensitive).
# Used by HttpResult.is_auth_failure() to disambiguate validation 400s
# from token-expiry 400s; 401/403 are always auth and short-circuit before
# this check is reached.
AUTH_BODY_HINTS = ("unauthorized", "token", "invalid_token", "authentication", "auth", "expired")

# The orchestrator normally emits string status values:
# Created, Running, Cancelling, Cancelled, Completed, Failed.
# Some deployed services have also returned the numeric enum index
# instead (for example, status=1 mid-run), so we coerce defensively. The
# numeric mapping MUST preserve the documented status order, including
# Cancelling. An earlier revision of this map had
# 2=Completed/3=Failed/4=Cancelled, which was wrong: it skipped Cancelling
# entirely and would silently mis-render terminal states.
#   0=Created, 1=Running, 2=Cancelling, 3=Cancelled, 4=Completed, 5=Failed
# Unknown numerics fall through as "Status N".
STATUS_BY_CODE = {0: "Created", 1: "Running", 2: "Cancelling", 3: "Cancelled", 4: "Completed", 5: "Failed"}
#
# Expected message role values are "User", "Assistant", and "System".
# Like status, some deployed services have also serialized roles as
# numeric or stringified-digit indices in the wire payload:
#     0 = User, 1 = Assistant, 2 = Tool (legacy), 3 = System
# We accept all forms defensively for inbound classification. There is
# legacy payloads in older runs use 2/Tool; we route both into
# DROPPED_ROLES so the dashboard never renders them.
ASSISTANT_ROLES = {1, "1", "Assistant", "assistant"}
USER_ROLES = {0, "0", "User", "user"}
TOOL_ROLES = {2, "2", "Tool", "tool"}
SYSTEM_ROLES = {3, "3", "System", "system"}

DROPPED_ROLES = TOOL_ROLES | SYSTEM_ROLES  # never rendered in dashboard


# ----------------------------- HTTP -----------------------------

@dataclass
class HttpResult:
    """Structured HTTP response. Wraps both success and error in one shape so
    the main loop can introspect status and body without juggling exceptions
    for routine 4xx/5xx (which are common during auth-broken or retry cycles)."""
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    url: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        try:
            return self.body.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""

    def json(self) -> dict[str, Any]:
        if not self.body:
            raise ValueError(f"empty JSON body from {self.url or '<unknown>'}")
        try:
            return json.loads(self.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"invalid JSON from {self.url or '<unknown>'}: {e}") from e

    def is_auth_failure(self) -> bool:
        """True when the response indicates the bearer token is invalid /
        expired. 401 and 403 always count; 400 only when the body contains
        auth-related sentinels (to avoid false-positives on validation 400s).
        """
        if self.status in (401, 403):
            return True
        if self.status == 400:
            t = self.text.lower()
            return any(hint in t for hint in AUTH_BODY_HINTS)
        return False


def http_request(
    url: str,
    auth_header: str,
    timeout: int,
    method: str = "GET",
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> HttpResult:
    """Single-shot HTTP call that returns HttpResult instead of raising.

    HTTPError (4xx/5xx) is captured into HttpResult.status/body so the main
    loop can introspect without juggling exceptions for routine auth-broken
    or retry cycles.

    Transport errors (URLError without an HTTPError, socket timeouts, DNS
    failures, connection resets — all subclasses of OSError) are also
    captured: the result has status=0 and body containing the exception
    type, so callers see a non-ok HttpResult and back off through the
    normal "not result.ok" branch instead of crashing the daemon. This
    matters for long-running polls where transient network blips
    (Wi-Fi handoff, sleep/wake, brief DNS unavailability) would otherwise
    take down the poller.
    """
    headers = {"Authorization": auth_header}
    if extra_headers:
        headers.update(extra_headers)
    if method == "POST" and body is None:
        # POST /run requires an empty body with explicit Content-Length: 0;
        # some backend versions return 411 otherwise (see troubleshooting.md).
        body = b""
        headers.setdefault("Content-Length", "0")
    req = urllib.request.Request(url, headers=headers, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return HttpResult(
                status=response.status,
                body=response.read(),
                headers={k: v for k, v in response.headers.items()},
                url=url,
            )
    except urllib.error.HTTPError as e:
        body_bytes = b""
        try:
            body_bytes = e.read() or b""
        except Exception:  # noqa: BLE001
            pass
        return HttpResult(status=e.code, body=body_bytes, url=url)
    except (urllib.error.URLError, OSError) as e:
        # URLError covers DNS / connection-refused / SSL handshake; OSError
        # covers socket.timeout (Python 3.10+ alias) and broader I/O failures.
        # Status 0 is our sentinel for "no HTTP exchange happened" — callers
        # treat it as a transient and back off.
        return HttpResult(
            status=0,
            body=f"transport_error: {type(e).__name__}: {e}".encode("utf-8", errors="replace"),
            url=url,
        )


# ----------------------------- helpers -----------------------------

def status_label(s: Any) -> str:
    """Coerce a task status value into a clean display string.

    The task API usually returns string status labels, but deployed
    Some deployed services can return numeric codes (see STATUS_BY_CODE
    comment block above). This helper handles both: numeric → mapped label, string →
    stripped, null/empty → "Created".
    """
    if s is None:
        return "Created"
    if isinstance(s, bool):
        return str(s)
    if isinstance(s, int):
        return STATUS_BY_CODE.get(s, "Status " + str(s))
    if isinstance(s, str):
        stripped = s.strip()
        if not stripped:
            return "Created"
        # API sometimes returns the numeric code as a stringified digit.
        if stripped.isdigit():
            return STATUS_BY_CODE.get(int(stripped), "Status " + stripped)
        return stripped
    return str(s)


def is_terminal(status: Any) -> bool:
    return status_label(status).lower() in TERMINAL_STRINGS


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def role_label(role: Any) -> str:
    if role in ASSISTANT_ROLES:
        return "assistant"
    if role in USER_ROLES:
        return "user"
    if role in TOOL_ROLES:
        return "tool"
    if role in SYSTEM_ROLES:
        return "system"
    return str(role)


def normalize_text(text: str) -> str:
    """Collapse internal whitespace for dedup comparison."""
    return " ".join((text or "").split())


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_utc_iso_epoch(ts: str | None) -> float | None:
    """Parse UTC timestamps with or without fractional seconds."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return float(calendar.timegm(time.strptime(ts, fmt)))
        except (ValueError, OverflowError):
            continue
    return None


def log(msg: str) -> None:
    """Module-level logger. Stamps every line with `now_iso()` and flushes
    immediately so `tail -f poller.log` is responsive. Module-level (rather
    than a closure inside main()) so refactored helpers can reach it without
    threading a callable through every signature.
    """
    sys.stdout.write(f"[{now_iso()}] {msg}\n")
    sys.stdout.flush()


def message_ts(m: dict[str, Any]) -> str:
    """Best-effort message timestamp extraction.

    `timestamp` is the preferred field and is checked first. `createdAt`
    and `ts` are kept as fallbacks so any older payload shape (or a
    poller-rewritten ndjson row) still resolves. Falls back to `now_iso()`
    only when the message carries no timestamp at all.
    """
    return m.get("timestamp") or m.get("createdAt") or m.get("ts") or now_iso()


def atomic_write(path: Path, data: str, mode: int | None = None) -> None:
    """Atomic write via temp + rename. If `mode` is set, the temp file is
    created with that mode bit before content is written, so the final file
    has restricted permissions throughout (no brief umask window).
    """
    tmp_name: str | None = None
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        if mode is not None:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
        if mode is not None:
            try:
                os.chmod(path, mode)
            except OSError:
                pass
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def sleep_interruptibly(seconds: float, stop_flag: dict[str, bool], chunk: float = 1.0) -> None:
    """Sleep in small chunks so SIGTERM / SIGINT interrupts the daemon promptly."""
    slept = 0.0
    while slept < seconds and not stop_flag.get("flag"):
        time.sleep(min(chunk, seconds - slept))
        slept += chunk


def matches_retryable(text: str) -> bool:
    """Return True iff `text` contains every RETRYABLE_PHRASES token, in order,
    after lower-casing and collapsing whitespace.

    Stricter than substring match (rejects "please retry" alone) and more
    tolerant than literal-string match (survives e.g. trailing punctuation,
    minor capitalization, or single-character drift).
    """
    if not text:
        return False
    norm = " ".join(text.lower().split())
    cursor = 0
    for phrase in RETRYABLE_PHRASES:
        idx = norm.find(phrase, cursor)
        if idx < 0:
            return False
        cursor = idx + len(phrase)
    return True


def error_signature(operation_id: str | None, completed_at: str | None, error_message: str | None) -> str:
    """Stable hash of (operationId, completedAt, normalized errorMessage).

    Each unique error signature is retried at most once. A real new failure
    after a successful retry has either a new operationId (the orchestrator
    started a fresh run) or a new completedAt timestamp, so it gets a fresh
    signature and is eligible for one more auto-retry.
    """
    norm_err = " ".join((error_message or "").lower().split())
    key = "|".join((operation_id or "", completed_at or "", norm_err))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# Patterns that look like credentials and must be scrubbed before persisting
# error text into state.json (which the dashboard reads as state.js, fully
# visible in the browser). Spark statement errors don't usually carry
# secrets, but lakehouse mount errors, ABFS path errors, and notebook
# stack traces can include SAS query strings, account keys, bearer tokens,
# user-provided connection strings, or customer-identifying storage/file paths.
# Scrub defensively. Do not add a blanket GUID redaction pattern here: task,
# workspace, lakehouse, operation, and session identifiers are first-class
# troubleshooting fields, and terminal.json reports them separately.
_REDACT_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:\"|')?(?:access[_-]?token|account[_-]?key|password|authorization|sharedaccesssignature)(?:\"|')?\s*[:=]\s*(?:\"|')?)[^\"',\s}]+((?:\"|')?)"), r"\1[REDACTED]\2"),
    (re.compile(r"(?i)(access[_-]?token\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(account[_-]?key\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(SharedAccessSignature\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(\?|&)(sig|sv|st|se|sp|skoid|sktid|skt|ske|sks|skv)=[^&\s'\"]+"), r"\1\2=[REDACTED]"),
    (re.compile(r"(?i)\babfss://[^\s'\")<>]+"), "[REDACTED-ABFS-PATH]"),
    (re.compile(r"(?i)\bhttps://[^/\s'\")<>]+\.(?:dfs|blob)\.core\.windows\.net/[^\s'\")<>]+"), "[REDACTED-AZURE-STORAGE-URL]"),
    (re.compile(r"(?i)\bfile://[^\s'\")<>]+"), "[REDACTED-FILE-PATH]"),
    (re.compile(r"(?i)(?<![\w/])/(?:Users|home|mnt|tmp|var|Volumes)/[^\s'\")<>]+"), "[REDACTED-FILE-PATH]"),
    (re.compile(r"(?i)\b[A-Z]:\\(?:Users|Temp|Windows|ProgramData)\\[^\s'\")<>]+"), "[REDACTED-FILE-PATH]"),
    # JWT-looking blobs (three base64url segments separated by dots, each
    # at least 8 chars). False-positive risk on long base64 hashes is
    # acceptable — better to over-redact than leak a token.
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"), "[REDACTED-JWT]"),
)


def redact_error(text: str | None, max_len: int = 500) -> str | None:
    """Scrub credential-shaped substrings and bound length before persisting.

    Returns None if input is None/empty so callers can use truthiness checks.
    Length cap is generous (500 chars) — long enough to keep stack frame
    context, short enough to keep state.json from ballooning if a giant
    Spark traceback comes through.
    """
    if not text:
        return None
    out = str(text)
    for pat, repl in _REDACT_PATTERNS:
        out = pat.sub(repl, out)
    if len(out) > max_len:
        out = out[: max_len - 1] + "…"
    return out


# ----------------------------- state merge -----------------------------

def load_state(state_json: Path) -> dict[str, Any]:
    empty = {
        "schema_version": 1,
        "task": {},
        "messages": [],
        "intake": {},
        "spec": "",
        "summary": "",
        "artifacts": {"notebook": None, "table": None},
        "recovery": {},
    }
    if not state_json.exists():
        return empty
    try:
        state = json.loads(state_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty
    return state if isinstance(state, dict) else empty


def task_state_block(state: dict[str, Any]) -> dict[str, Any]:
    task_block = state.get("task")
    if isinstance(task_block, dict):
        return task_block
    task_block = {}
    state["task"] = task_block
    return task_block


@dataclass
class MergeStats:
    """Outcome of one merge_messages() call. Used by the main loop to decide
    cadence and (critically) whether `recovery.last_progress_at` should
    advance — only new assistant appends count as progress, never collapsed
    duplicates or user messages.
    """
    assistant_appended: int = 0
    user_appended: int = 0
    collapsed_repeats: int = 0
    latest_assistant_ts: str | None = None
    latest_assistant_seq: int | None = None  # poller-local monotonic seq, used as retry-clear watermark

    @property
    def any_change(self) -> bool:
        return bool(self.assistant_appended or self.user_appended or self.collapsed_repeats)


def merge_messages(existing: list[dict[str, Any]], polled: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], MergeStats]:
    """Append new messages, collapse consecutive duplicates, drop tool/system.

    Returns (new_message_list, MergeStats). The stats split assistant appends
    from user appends and from collapsed repeats so the caller can advance
    `last_progress_at` only on genuine orchestrator progress.
    """
    seen_ids = {m.get("id") for m in existing if m.get("id")}
    for m in existing:
        for collapsed_id in m.get("collapsed_ids") or []:
            if collapsed_id:
                seen_ids.add(collapsed_id)
    next_seq = max((int(m.get("seq", -1)) for m in existing), default=-1) + 1
    stats = MergeStats()

    for m in polled:
        mid = m.get("id")
        if mid and mid in seen_ids:
            continue
        role = role_label(m.get("role"))
        if role in {"tool", "system"}:
            # drop from state.messages (still in messages.ndjson)
            continue
        text = str(m.get("content") or m.get("text") or "")
        ts = message_ts(m)

        # Dedup against last entry
        if existing:
            last = existing[-1]
            if (
                last.get("role") == role
                and normalize_text(last.get("text", "")) == normalize_text(text)
            ):
                last["repeats"] = int(last.get("repeats", 1)) + 1
                last["last_seen_ts"] = ts
                if mid:
                    seen_ids.add(mid)
                    collapsed_ids = last.setdefault("collapsed_ids", [])
                    if mid not in collapsed_ids:
                        collapsed_ids.append(mid)
                stats.collapsed_repeats += 1
                continue

        entry = {
            "seq": next_seq,
            "id": mid,
            "ts": ts,
            "role": role,
            "text": text,
        }
        # Preserve author metadata when present (mediator pattern: user
        # follow-ups POSTed via post-user-message.py carry author info so
        # the dashboard can show "👤 <name>" on each bubble).
        #
        # We accept two shapes because the SparkCore-direct POST /messages
        # Some deployed binders reject nested objects inside metadata
        # today, so post-user-message.py sends flat author_name/author_source
        # keys. Once the server widens metadata to dict[str, Any] the nested
        # metadata.author = {name, source} shape will also round-trip.
        # Normalize both into entry.author = {name, source} so the dashboard
        # renderer at assets/dashboard.html doesn't need to know either way.
        meta = m.get("metadata") or {}
        author = None
        if isinstance(meta, dict):
            nested = meta.get("author")
            if isinstance(nested, dict):
                author = nested
            else:
                name = meta.get("author_name")
                if isinstance(name, str) and name:
                    author = {"name": name}
                    src = meta.get("author_source")
                    if isinstance(src, str) and src:
                        author["source"] = src
        if author:
            entry["author"] = author
        existing.append(entry)
        if mid:
            seen_ids.add(mid)
        next_seq += 1
        if role == "assistant":
            stats.assistant_appended += 1
            stats.latest_assistant_ts = ts
            stats.latest_assistant_seq = entry["seq"]
        elif role == "user":
            stats.user_appended += 1

    return existing, stats


def append_ndjson(ndjson_path: Path, polled: list[dict[str, Any]], ndjson_seen: set[str]) -> int:
    """Append never-before-seen message ids (any role) to messages.ndjson.

    The caller maintains `ndjson_seen` separately from `state.messages` so that
    tool/system messages — which are dropped from the dashboard feed — are
    still recorded exactly once in the audit log. Without this set the old
    implementation re-appended tool/system messages on every poll, causing
    unbounded growth on long runs.

    Returns the count of new lines appended.
    """
    new = []
    for m in polled:
        mid = m.get("id")
        if not mid or mid in ndjson_seen:
            continue
        new.append(m)
        ndjson_seen.add(mid)
    if not new:
        return 0
    with ndjson_path.open("a", encoding="utf-8") as f:
        for m in new:
            f.write(json.dumps({
                "ts": message_ts(m),
                "role": role_label(m.get("role")),
                "id": m.get("id"),
                "text": str(m.get("content") or m.get("text") or ""),
            }) + "\n")
    return len(new)


def load_ndjson_seen(ndjson_path: Path) -> set[str]:
    """Rebuild the seen-id set on poller startup so resumed runs don't double-write.

    `messages.ndjson` is append-only, so we read every prior line and extract
    its id. Bounded by run length but a 24h run is at most ~few thousand
    messages, which is cheap to scan.
    """
    seen: set[str] = set()
    if not ndjson_path.exists():
        return seen
    try:
        with ndjson_path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                stripped_line = raw_line.strip()
                if not stripped_line:
                    continue
                try:
                    obj = json.loads(stripped_line)
                except json.JSONDecodeError:
                    continue
                mid = obj.get("id")
                if mid:
                    seen.add(mid)
    except OSError:
        pass
    return seen


def write_state(state_dir: Path, state: dict[str, Any]) -> None:
    state_json_path = state_dir / "state.json"
    state_js_path = state_dir / "state.js"
    # Defensive backfill: the dashboard refuses to render when schema_version is
    # missing. A seed file written by the skill before the poller starts may
    # omit it; setdefault here heals the snapshot on the next poll cycle so the
    # dashboard's mismatch banner clears without manual intervention.
    state.setdefault("schema_version", 1)
    state.setdefault("recovery", {})
    payload = json.dumps(state, indent=2)
    atomic_write(state_json_path, payload)
    atomic_write(state_js_path, "window.__STATE = " + payload + ";\n")


# ----------------------------- recovery: token + retry -----------------------------

@dataclass
class TokenManager:
    """Owns the in-memory bearer token and the shared token file.

    Invariants:
      - Reactive refresh (token *known* bad): validate the candidate token via a
        cheap GET before committing; if refresh or validation fails, surface the
        failure so the caller can enter auth_broken.
      - Proactive refresh (token *believed* good): validate the candidate
        token via a cheap GET before committing, so a misconfigured refresh
        cmd cannot poison a working session.
      - Token file is written with 0600 mode via secure atomic_write so
        sibling tools (post-user-message.py, agent) get the same token
        without exposing it to other local users.
    """
    token: str
    auth_scheme: str
    token_file: Path | None
    refresh_cmd: str | None
    refresh_timeout: int
    validate_url: str
    http_timeout: int
    log: Any  # callable
    refresh_count: int = 0
    last_refreshed_at: str | None = None

    @property
    def header(self) -> str:
        return f"{self.auth_scheme} {self.token}"

    def _run_refresh_cmd(self, stop_flag: dict[str, bool]) -> str | None:
        """Execute the configured shell refresh command; return new token or None.

        Uses Popen so SIGTERM can kill the subprocess. Truncates stderr in
        the log so credentials in error output don't leak.
        """
        if not self.refresh_cmd:
            return None
        self.log("token_refresh: running refresh command")
        try:
            proc = subprocess.Popen(
                self.refresh_cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as e:
            self.log(f"token_refresh: spawn failed: {e}")
            return None
        # Interruptible wait: poll up to refresh_timeout, react to stop_flag
        deadline = time.monotonic() + self.refresh_timeout

        def terminate_refresh_process(sig: int) -> None:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(proc.pid, sig)
                else:
                    proc.send_signal(sig)
            except ProcessLookupError:
                return
            except (AttributeError, OSError):
                try:
                    proc.send_signal(sig)
                except OSError:
                    pass

        while True:
            if stop_flag.get("flag"):
                terminate_refresh_process(signal.SIGTERM)
                self.log("token_refresh: interrupted by signal")
                return None
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() > deadline:
                    terminate_refresh_process(getattr(signal, "SIGKILL", signal.SIGTERM))
                    self.log(f"token_refresh: timed out after {self.refresh_timeout}s")
                    return None
                continue
        if proc.returncode != 0:
            # Route stderr through redact_error before logging — refresh
            # helpers occasionally echo the bearer token, an Authorization
            # header, or a SAS-laden URL into stderr on failure paths, and
            # poller.log is not a credential-safe sink.
            err_short = redact_error((stderr or "").strip(), max_len=200) or ""
            self.log(f"token_refresh: cmd exit={proc.returncode} stderr={err_short!r}")
            return None
        candidate = (stdout or "").strip()
        if not candidate or "\n" in candidate or len(candidate) < 16:
            self.log(f"token_refresh: rejected candidate (len={len(candidate)})")
            return None
        return candidate

    def _commit(self, new_token: str) -> None:
        self.token = new_token
        if self.token_file:
            try:
                atomic_write(self.token_file, new_token, mode=0o600)
            except OSError as e:
                self.log(f"token_refresh: warn — could not write token file: {e}")
        self.refresh_count += 1
        self.last_refreshed_at = now_iso()
        self.log(f"token_refresh: committed (refresh_count={self.refresh_count})")

    def refresh_reactive(self, stop_flag: dict[str, bool]) -> bool:
        """Called when we *know* the current token is bad (auth 4xx).

        On success: token is validated, then swapped immediately.
        On failure: returns False; caller should enter auth_broken.
        """
        new = self._run_refresh_cmd(stop_flag)
        if not new:
            return False
        candidate_header = f"{self.auth_scheme} {new}"
        result = http_request(self.validate_url, candidate_header, self.http_timeout)
        if not result.ok:
            detail = "transport error" if result.status == 0 else f"status={result.status}"
            self.log(
                f"token_refresh: reactive candidate rejected by validate GET "
                f"({detail}); entering auth_broken"
            )
            return False
        self._commit(new)
        return True

    def refresh_proactive(self, stop_flag: dict[str, bool]) -> bool:
        """Periodic refresh while the current token still works.

        We acquire a candidate token, validate it via a cheap GET, and only
        commit if validation succeeds. This avoids breaking a working
        session if the refresh cmd has been misconfigured (wrong tenant,
        stale az context, etc.). If validation fails, we keep the current
        token and log loudly — the next reactive refresh on real expiry
        will get a fresh attempt.
        """
        new = self._run_refresh_cmd(stop_flag)
        if not new:
            return False
        # Validate with a cheap GET; success → commit.
        candidate_header = f"{self.auth_scheme} {new}"
        result = http_request(self.validate_url, candidate_header, self.http_timeout)
        if not result.ok:
            # status=0 is the http_request sentinel for transport errors
            # (DNS / connection / timeout). Anything non-ok means we cannot
            # confirm the candidate works; keep the current token.
            detail = "transport error" if result.status == 0 else f"status={result.status}"
            self.log(
                f"token_refresh: candidate rejected by validate GET "
                f"({detail}); keeping current token"
            )
            return False
        self._commit(new)
        return True


@dataclass
class RecoveryState:
    """In-memory recovery state machine for auto-retry and auth-broken modes.

    Persisted into `state["recovery"]` on each write_state so the dashboard
    can render banners and pills.
    """
    auto_retries_total: int = 0
    last_retry_at: str | None = None
    last_progress_at: str | None = None
    last_successful_poll_at: str | None = None
    auth_status: str = "ok"  # "ok" | "broken"
    last_auth_error_at: str | None = None
    auth_broken_started_at: str | None = None
    auto_retries_exhausted: bool = False
    last_retried_signature: str | None = None
    # Wall time spent in auth_broken state since last successful poll; used
    # to pause the no-progress timer so auth outages don't trigger false
    # give-up. Reset to 0 on each successful poll.
    auth_blind_seconds_accumulated: float = 0.0
    visibility_lost_at_monotonic: float | None = None

    # ----- mid-run-error visibility (sticky across the wipe) -----
    # When the daemon decides to auto-retry, it wipes task.completed_at /
    # task.status_detail / sets task.status="Running" so the dashboard
    # stops showing terminal. Without these sticky fields the user would
    # see the retry-count pill increment with NO visible explanation of
    # what failed. Captured BEFORE the wipe; cleared on the first fresh
    # assistant append after the retry's message-seq watermark, or
    # carried forward into terminal.json on exit.
    last_trigger_error: str | None = None
    last_trigger_error_at: str | None = None
    last_trigger_error_signature: str | None = None
    pending_retry_signature: str | None = None
    # Poller-local monotonic message seq captured at the moment of retry.
    # Wall-clock comparison would race against server clock skew and the
    # ordering between /run POST and the orchestrator's first response
    # message; the seq watermark is robust because it reflects what the
    # poller has actually observed and merged into state.messages.
    last_retry_message_seq: int | None = None

    def to_dict(self, max_retries: int, no_progress_window: int) -> dict[str, Any]:
        return {
            "auto_retries_total": self.auto_retries_total,
            "auto_retries_max": max_retries,
            "auto_retries_exhausted": self.auto_retries_exhausted,
            "last_retry_at": self.last_retry_at,
            "last_progress_at": self.last_progress_at,
            "last_successful_poll_at": self.last_successful_poll_at,
            "no_progress_window_seconds": no_progress_window,
            "auth_status": self.auth_status,
            "last_auth_error_at": self.last_auth_error_at,
            "auth_broken_started_at": self.auth_broken_started_at,
            "auth_blind_seconds_accumulated": self.auth_blind_seconds_accumulated,
            "last_retried_signature": self.last_retried_signature,
            "last_trigger_error": self.last_trigger_error,
            "last_trigger_error_at": self.last_trigger_error_at,
            "last_trigger_error_signature": self.last_trigger_error_signature,
            "pending_retry_signature": self.pending_retry_signature,
            "last_retry_message_seq": self.last_retry_message_seq,
        }

    def hydrate_from_state(self, state: dict[str, Any], task_id: str) -> None:
        """On daemon restart, reload recovery fields that are run-scoped.

        Transport-only state such as auth_broken visibility monotonic timers is
        process-local, but retry counters, trigger details, and progress
        timestamps are run-level dashboard state and should survive respawns.
        """
        if state.get("terminal"):
            return
        task_block = task_state_block(state)
        if task_block.get("id") and task_block.get("id") != task_id:
            return
        rec = state.get("recovery") or {}
        self.auto_retries_total = int_or_zero(rec.get("auto_retries_total"))
        self.last_retry_at = rec.get("last_retry_at")
        self.last_progress_at = rec.get("last_progress_at")
        self.last_successful_poll_at = rec.get("last_successful_poll_at")
        self.auth_status = rec.get("auth_status") if rec.get("auth_status") == "broken" else "ok"
        self.last_auth_error_at = rec.get("last_auth_error_at")
        self.auth_broken_started_at = rec.get("auth_broken_started_at")
        self.auth_blind_seconds_accumulated = float_or_zero(
            rec.get("auth_blind_seconds_accumulated")
        )
        if self.auth_status == "broken":
            broken_started_epoch = parse_utc_iso_epoch(
                self.auth_broken_started_at or self.last_auth_error_at
            )
            if broken_started_epoch is not None:
                self.auth_blind_seconds_accumulated += max(
                    0.0, time.time() - broken_started_epoch
                )
                self.auth_broken_started_at = now_iso()
            self.visibility_lost_at_monotonic = time.monotonic()
        self.auto_retries_exhausted = bool(rec.get("auto_retries_exhausted"))
        self.last_retried_signature = rec.get("last_retried_signature")
        if rec.get("last_trigger_error"):
            self.last_trigger_error = rec.get("last_trigger_error")
            self.last_trigger_error_at = rec.get("last_trigger_error_at")
            self.last_trigger_error_signature = rec.get("last_trigger_error_signature")
            self.pending_retry_signature = rec.get("pending_retry_signature")
            self.last_retry_message_seq = rec.get("last_retry_message_seq")


def write_terminal_json(state_dir: Path, payload: dict[str, Any]) -> None:
    """Write the terminal marker exactly once. Idempotent — subsequent calls overwrite.

    The agent reads this on re-engage to know why the poller exited without
    asking the user.
    """
    payload.setdefault("exited_at", now_iso())
    try:
        atomic_write(state_dir / "terminal.json", json.dumps(payload, indent=2))
    except OSError:
        pass


def write_terminal_state(state_dir: Path, state: dict[str, Any],
                         payload: dict[str, Any]) -> None:
    """Write terminal.json and mirror it into state.json/state.js."""
    write_terminal_json(state_dir, payload)
    state["terminal"] = payload
    write_state(state_dir, state)


def archive_stale_terminal_json(state_dir: Path) -> bool:
    """Rename any existing terminal.json so a fresh poller run starts clean.

    Without this, the agent would read the OLD terminal.json on re-engage
    and conclude the new run already exited. We rename rather than delete
    to preserve forensic history.
    """
    src = state_dir / "terminal.json"
    if not src.exists():
        return False
    try:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        dst = state_dir / f"terminal.{ts}.{time.time_ns()}.{os.getpid()}.json"
        src.rename(dst)
        return True
    except OSError:
        # If rename fails (e.g. cross-device), best-effort unlink.
        try:
            src.unlink()
            return True
        except OSError:
            pass
    return False


def compute_backoff(retry_index: int, backoff_schedule: list[float]) -> float:
    """Pick the backoff for the Nth retry attempt (0-indexed).

    For retry indices beyond the schedule, the last value in the schedule
    is used flat. Example default schedule [30, 60, 120] → 30s, 60s, 120s,
    then 120s for every subsequent retry.
    """
    if not backoff_schedule:
        return 60.0
    idx = min(retry_index, len(backoff_schedule) - 1)
    return float(backoff_schedule[idx])


def parse_backoff_schedule(arg: str) -> list[float]:
    """Parse "30,60,120" → [30.0, 60.0, 120.0]. Empty / malformed → default."""
    if not arg:
        return [30.0, 60.0, 120.0]
    out: list[float] = []
    for raw_token in arg.split(","):
        token = raw_token.strip()
        if not token:
            continue
        try:
            v = float(token)
            if v > 0:
                out.append(v)
        except ValueError:
            continue
    return out or [30.0, 60.0, 120.0]


# ----------------------------- main loop -----------------------------


@dataclass
class RetryOutcome:
    """Result of `_handle_terminal_failed`. Drives main()'s next move:

      - action="continue" — a retry was kicked off (or a transient transport
        error was absorbed). main() should continue the loop. If
        `reset_cadence=True`, main() should also snap interval and
        consecutive_idle back to fast-poll.
      - action="break" — the daemon should exit the loop. `reason` and
        `status` are written into the terminal payload; signal paths must
        set `reason="signal"` explicitly.
    """

    action: str
    reason: str = ""
    status: str = ""
    reset_cadence: bool = False


# Distinct daemon exit codes so supervisors (systemd, launchd, k8s, watchdog
# scripts) can differentiate "orchestrator hit a terminal state, daemon did
# its job" (0) from "daemon itself gave up or crashed" (non-zero).
# Orchestrator-level outcomes (Completed vs Failed vs Cancelled) live in
# terminal.json.status — supervisors that care should read that file. The
# exit code answers "did the poller succeed at observing?".
_EXIT_CODES = {
    "terminal_status": 0,
    "signal": 0,
    "crash": 1,
    "max_runtime": 2,
    "max_auto_retries": 3,
    "retry_signature_repeat": 4,
    "no_progress_window": 5,
    "no_token_at_startup": 7,
}
_STALE_RETRY_SIGNATURE_GRACE_SECONDS = 300.0


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser. Lifted out of main() so the option contract
    is scannable without wading through the loop body."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="Task base URL (no trailing task id)")
    p.add_argument("--task-id", required=True)
    p.add_argument("--state-dir", required=True, help="Path to .dataprojects/<task-id>/")
    p.add_argument("--token-file", help="File containing the bearer token (preferred)")
    p.add_argument("--token-env", default="MWC_TOKEN", help="Env var fallback for the token")
    p.add_argument("--auth-scheme", default="mwctoken")
    p.add_argument("--interval", type=float, default=60.0, help="Base poll interval (s)")
    p.add_argument("--fast-interval", type=float, default=15.0, help="Initial fast-poll interval (s)")
    p.add_argument("--fast-window", type=float, default=90.0, help="Seconds to stay in fast-poll mode")
    p.add_argument("--max-interval", type=float, default=180.0, help="Max idle interval (s)")
    p.add_argument("--max-runtime", type=float, default=86400.0,
                   help="Hard cap (s); default 24h to accommodate long-running DE jobs.")
    p.add_argument("--timeout", type=int, default=30, help="HTTP timeout (s)")
    # ----- recovery flags -----
    p.add_argument("--token-refresh-cmd",
                   help="Shell command whose stdout is a fresh MWC token. If unset, no auto-refresh; "
                        "the daemon enters auth_broken on expiry and waits for external intervention.")
    p.add_argument("--token-refresh-interval", type=float, default=2700.0,
                   help="Proactive refresh interval (s); default 2700 (45 min). "
                        "SparkCore terminates agent processes near the ~60-75 min "
                        "token expiry window, so we refresh comfortably under the "
                        "lower bound with margin. Reactive refresh always fires "
                        "on auth 4xx regardless.")
    p.add_argument("--token-refresh-timeout", type=int, default=120,
                   help="Max wall time (s) for one --token-refresh-cmd invocation.")
    p.add_argument("--max-auto-retries", type=int, default=10,
                   help="Hard cap on auto-retries of the documented Spark statement transient. "
                        "Default 10. Each unique error signature is retried at most once until a "
                        "new run identity is observed (so this counts distinct failure events).")
    p.add_argument("--retry-backoff-seconds", default="30,60,120",
                   help="Comma-separated backoff schedule before each auto-retry POST /run. "
                        "Last value is used flat for subsequent retries. Default '30,60,120'.")
    p.add_argument("--no-progress-window-seconds", type=int, default=7200,
                    help="If no new assistant message has been observed within this many seconds "
                         "(paused while auth-broken), stop the poller with reason no_progress_window. "
                         "Applies to ordinary Running tasks and auto-retry recovery. Default 7200 = 2h.")
    p.add_argument("--auth-broken-min-backoff", type=float, default=30.0,
                   help="Minimum wait (s) between refresh attempts while auth-broken.")
    p.add_argument("--auth-broken-max-backoff", type=float, default=300.0,
                   help="Maximum wait (s) between refresh attempts while auth-broken.")
    return p


def _resolve_initial_token(args: argparse.Namespace) -> str | None:
    """Return the bootstrap token from --token-file (preferred) or env var.
    Empty string and unreadable file both fall through to env-var fallback."""
    token: str | None = None
    if args.token_file:
        try:
            token = Path(args.token_file).read_text(encoding="utf-8").strip()
        except OSError:
            pass
    if not token:
        token = os.environ.get(args.token_env)
    return token or None


def _install_signal_handlers(stop: dict[str, bool]) -> None:
    """Wire SIGTERM and SIGINT to flip `stop['flag']`. The
    `sleep_interruptibly` helper observes that flag, so signals interrupt
    the loop within ~1s."""
    def handle_signal(_sig: int, _frame: Any) -> None:
        stop["flag"] = True
        log("received signal, exiting cleanly")

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


def _persist_recovery(state: dict[str, Any], recovery: RecoveryState,
                      tokens: TokenManager, args: argparse.Namespace,
                      with_token_metadata: bool = True) -> None:
    """Merge RecoveryState + TokenManager metadata into `state['recovery']`.
    Called from every code path that mutates RecoveryState before
    write_state. Does NOT call write_state itself — the caller controls
    when state hits disk.

    `with_token_metadata=False` preserves the original behavior of the
    auth-broken and auto-retry-recovery paths, which historically updated
    only the `recovery.to_dict(...)` block and did not stamp
    `token_refreshed_at` / `token_refresh_count`. The success-only
    refresh and post-poll persist paths keep the default (True)."""
    state.setdefault("recovery", {}).update(recovery.to_dict(
        args.max_auto_retries, args.no_progress_window_seconds
    ))
    state["recovery"]["token_refresh_configured"] = bool(args.token_refresh_cmd)
    if with_token_metadata:
        state["recovery"]["token_refreshed_at"] = tokens.last_refreshed_at
        state["recovery"]["token_refresh_count"] = tokens.refresh_count


def _apply_task_payload(
    task_block: dict[str, Any],
    task_payload: dict[str, Any],
    ignored_error_signature: str | None = None,
    ignored_error_since: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Merge polled task payload fields into `task_block`. Returns the
    `(completed_at, err, operation_id)` triple that downstream auto-retry
    decisions key off of. Status is derived from runDetails completion markers
    without overriding explicit cancellation or failure statuses from the task
    payload."""
    for k in ("status", "workspace_id", "workspace_name", "lakehouse_id",
              "lakehouse_name", "created_at", "started_at"):
        v = task_payload.get(k)
        if v is not None:
            task_block[k] = status_label(v) if k == "status" else v
    run_details = task_payload.get("runDetails") or {}
    completed_at: str | None = None
    err: str | None = None
    operation_id = task_payload.get("operationId") or run_details.get("operationId")
    if operation_id:
        # Persist into state.task so terminal.json (read at exit) and
        # the SKILL.md "resume" flow (which reads operation_id from
        # state.json) actually have it. Until this fix the field was
        # extracted for retry-signature use only and dropped on the
        # floor.
        task_block["operation_id"] = operation_id
    session_id = task_payload.get("sessionId") or run_details.get("sessionId")
    if session_id:
        task_block["session_id"] = session_id
    capacity_id = task_payload.get("capacityId") or run_details.get("capacityId")
    if capacity_id:
        task_block["capacity_id"] = capacity_id
    if isinstance(run_details, dict):
        payload_status = status_label(task_payload.get("status"))
        raw_completed_at = run_details.get("completedAt")
        raw_err = run_details.get("errorMessage")
        same_retried_signature = (
            ignored_error_signature
            and raw_completed_at
            and raw_err
            and error_signature(
                operation_id, raw_completed_at, redact_error(raw_err) or raw_err
            ) == ignored_error_signature
        )
        if same_retried_signature and payload_status in {"Completed", "Cancelled", "Canceled"}:
            task_block.pop("completed_at", None)
            task_block.pop("status_detail", None)
            task_block["status"] = payload_status
            return None, None, operation_id
        last_retry_epoch = parse_utc_iso_epoch(ignored_error_since)
        within_stale_grace = (
            last_retry_epoch is not None
            and time.time() - last_retry_epoch < _STALE_RETRY_SIGNATURE_GRACE_SECONDS
        )
        if same_retried_signature and within_stale_grace:
            # We already POSTed /run for this exact failure. Some deployed
            # routes keep returning the old runDetails while the new run is
            # acquiring; do not re-stamp the stale terminal fields into state.
            # The suppression is time-bounded so a same-signature failed
            # runDetails that remains after the acquiring grace reaches
            # _handle_terminal_failed() and exits as retry_signature_repeat.
            task_block.pop("completed_at", None)
            task_block.pop("status_detail", None)
            task_block["status"] = "Running"
            return None, None, operation_id

        completed_at = raw_completed_at
        err = redact_error(raw_err)
        if completed_at:
            task_block["completed_at"] = completed_at
        else:
            task_block.pop("completed_at", None)
        if err:
            task_block["status_detail"] = err
        else:
            task_block.pop("status_detail", None)
        if err and payload_status not in {"Cancelled", "Canceled"}:
            task_block["status"] = "Failed"
        elif completed_at and not err and payload_status not in {"Cancelled", "Canceled", "Failed"}:
            task_block["status"] = "Completed"
    return completed_at, err, operation_id


def _restore_failed_task_block(
    task_block: dict[str, Any],
    status: str | None,
    err: str | None,
    completed_at: str | None,
) -> None:
    task_block["status"] = status or "Failed"
    if completed_at:
        task_block["completed_at"] = completed_at
    else:
        task_block.pop("completed_at", None)
    if err:
        task_block["status_detail"] = redact_error(err)
    else:
        task_block.pop("status_detail", None)


def _update_progress_and_trigger(recovery: RecoveryState, merge_stats: MergeStats) -> None:
    """Advance `recovery.last_progress_at` on a fresh assistant append (NOT
    on collapsed repeats or user messages) and clear the sticky
    mid-run-error trigger banner once the orchestrator has emitted past the
    last-retry seq watermark."""
    if not (merge_stats.assistant_appended and merge_stats.latest_assistant_ts):
        return
    recovery.last_progress_at = merge_stats.latest_assistant_ts
    # Reset blind-time accumulator on fresh progress so old auth
    # outages don't get double-counted against future silences.
    recovery.auth_blind_seconds_accumulated = 0.0
    if recovery.auth_status == "ok":
        recovery.auth_broken_started_at = None
    # Clear the sticky mid-run-error trigger banner once the
    # orchestrator has emitted a fresh assistant message AFTER
    # the last retry's seq watermark. We use seq (poller-local
    # monotonic) instead of timestamp comparison because server
    # clocks can skew and the orchestrator's first post-/run
    # message can arrive with a timestamp predating last_retry_at
    # depending on which clock the server stamps from.
    if (
        recovery.last_trigger_error
        and recovery.last_retry_message_seq is not None
        and merge_stats.latest_assistant_seq is not None
        and merge_stats.latest_assistant_seq > recovery.last_retry_message_seq
    ):
        recovery.last_trigger_error = None
        recovery.last_trigger_error_at = None
        recovery.last_trigger_error_signature = None
        recovery.pending_retry_signature = None
        recovery.last_retry_message_seq = None


def _handle_auth_failure(
    msgs_result: HttpResult,
    task_result: HttpResult,
    recovery: RecoveryState,
    tokens: TokenManager,
    args: argparse.Namespace,
    state: dict[str, Any],
    state_dir: Path,
    stop: dict[str, bool],
    consecutive_idle: int,
    last_token_refresh_mono: float,
) -> tuple[str, float]:
    """Handle a poll cycle where one or both polls returned auth-class
    failures. Returns `(outcome, last_token_refresh_mono)`:

      - "not_auth"  → neither poll was an auth failure; caller falls through
                      to the normal poll-success path.
      - "refreshed" → reactive refresh succeeded; caller `continue`s with
                      no consecutive_idle increment (a retry, not idle).
      - "broken"    → entered/in auth_broken state; this helper has already
                      slept the bounded backoff; caller increments
                      consecutive_idle then `continue`s.
    """
    if not (msgs_result.is_auth_failure() or task_result.is_auth_failure()):
        return "not_auth", last_token_refresh_mono

    recovery.last_auth_error_at = now_iso()
    log(
        f"poll: auth failure "
        f"(msgs={msgs_result.status}, task={task_result.status}); "
        f"attempting reactive refresh"
    )
    if args.token_refresh_cmd and tokens.refresh_reactive(stop):
        recovery.auth_status = "ok"
        if recovery.visibility_lost_at_monotonic is not None:
            recovery.auth_blind_seconds_accumulated += (
                time.monotonic() - recovery.visibility_lost_at_monotonic
            )
            recovery.visibility_lost_at_monotonic = None
        recovery.auth_broken_started_at = None
        # Persist refresh metadata into recovery block, then continue
        # the loop — next iteration retries the polls with the fresh token.
        _persist_recovery(state, recovery, tokens, args)
        write_state(state_dir, state)
        return "refreshed", time.monotonic()

    # Refresh unavailable or failed → auth_broken
    if recovery.auth_status != "broken":
        recovery.auth_status = "broken"
        recovery.auth_broken_started_at = recovery.last_auth_error_at
        recovery.visibility_lost_at_monotonic = time.monotonic()
        log("auth_broken: entering — refresh unavailable or failed")
    _persist_recovery(state, recovery, tokens, args, with_token_metadata=False)
    write_state(state_dir, state)
    # Bounded backoff before re-attempting refresh.
    wait = min(
        args.auth_broken_max_backoff,
        args.auth_broken_min_backoff * (1.5 ** min(consecutive_idle, 10)),
    )
    sleep_interruptibly(wait, stop)
    return "broken", last_token_refresh_mono


def _clear_auth_broken_if_set(recovery: RecoveryState) -> None:
    """If the previous cycle was auth_broken and this cycle's polls
    succeeded, flip state back to ok and roll the lost-visibility window
    into the blind-time accumulator (so the no-progress-window check
    excludes it)."""
    if recovery.auth_status != "broken":
        return
    log("auth_broken: cleared — resuming normal polling")
    if recovery.visibility_lost_at_monotonic is not None:
        recovery.auth_blind_seconds_accumulated += (
            time.monotonic() - recovery.visibility_lost_at_monotonic
        )
        recovery.visibility_lost_at_monotonic = None
    recovery.auth_status = "ok"


def _visible_no_progress_seconds(recovery: RecoveryState) -> float | None:
    """Seconds since last assistant progress, excluding auth-broken blind time."""
    last_prog_epoch = parse_utc_iso_epoch(recovery.last_progress_at)
    if last_prog_epoch is None:
        return None
    wall_no_progress = time.time() - last_prog_epoch
    return wall_no_progress - recovery.auth_blind_seconds_accumulated


def _no_progress_window_exceeded(recovery: RecoveryState,
                                 args: argparse.Namespace) -> float | None:
    visible_no_progress = _visible_no_progress_seconds(recovery)
    if visible_no_progress is None:
        return None
    if visible_no_progress > args.no_progress_window_seconds:
        return visible_no_progress
    return None


def _handle_terminal_failed(  # noqa: PLR0915
    *,
    state: dict[str, Any],
    state_dir: Path,
    recovery: RecoveryState,
    tokens: TokenManager,
    args: argparse.Namespace,
    backoff_schedule: list[float],
    run_url: str,
    merge_stats: MergeStats,
    status: str | None,
    err: str | None,
    completed_at: str | None,
    operation_id: str | None,
    stop: dict[str, bool],
) -> RetryOutcome:
    """Decide what to do when the polled task is in a terminal Failed state.

    Returns:
      - RetryOutcome("continue", reset_cadence=True) on a successful POST /run
      - RetryOutcome("continue") on a transient transport error during POST
        /run (do NOT consume an auto-retry slot; the next loop iteration
        retries with the standard backoff schedule)
      - RetryOutcome("break", reason, status) on a hard exit condition:
        non-retryable, signature already retried, max retries reached,
        no-progress window exceeded, or POST /run hard-failed
      - RetryOutcome("break", "signal", status) if a signal arrived during
        the retry backoff sleep.
    """
    err_or_msg = err or ""
    # If runDetails didn't carry the error, accept a fresh assistant
    # message as fallback only if it was appended *in this poll cycle*
    # (i.e., timestamp matches the current failed run).
    if not err_or_msg and merge_stats.assistant_appended and merge_stats.latest_assistant_ts:
        last_msg = state["messages"][-1] if state.get("messages") else {}
        if last_msg.get("role") == "assistant":
            err_or_msg = last_msg.get("text", "")

    if not matches_retryable(err_or_msg):
        # Non-retryable failure → normal terminal exit.
        log(f"terminal status={status} (not retryable); exiting")
        return RetryOutcome("break", "terminal_status", status or "Unknown")

    sig = error_signature(operation_id, completed_at, err_or_msg)
    if sig == recovery.last_retried_signature:
        log(f"auto_retry: signature {sig} already retried; not retrying again")
        return RetryOutcome("break", "retry_signature_repeat", "Failed")
    if recovery.auto_retries_total >= args.max_auto_retries:
        log(
            f"auto_retry: max ({args.max_auto_retries}) reached; "
            f"giving up"
        )
        recovery.auto_retries_exhausted = True
        return RetryOutcome("break", "max_auto_retries", "Failed")

    # No-progress-window check (paused during auth-broken via accumulated blind seconds).
    visible_no_progress = _no_progress_window_exceeded(recovery, args)
    if visible_no_progress is not None:
        log(
            f"auto_retry: no progress for {visible_no_progress:.0f}s "
            f"(> {args.no_progress_window_seconds}s); giving up"
        )
        return RetryOutcome("break", "no_progress_window", "Failed")

    # Compute backoff, then POST /run.
    wait = compute_backoff(recovery.auto_retries_total, backoff_schedule)
    pending_retry_count = recovery.auto_retries_total + 1
    recovery.last_trigger_error = redact_error(err_or_msg)
    recovery.last_trigger_error_at = completed_at or now_iso()
    recovery.last_trigger_error_signature = sig
    recovery.pending_retry_signature = sig
    recovery.last_retry_message_seq = max(
        (int(m.get("seq", -1)) for m in state.get("messages", [])),
        default=-1,
    )
    task_block = task_state_block(state)
    task_block["status"] = "Running"
    task_block.pop("completed_at", None)
    task_block.pop("status_detail", None)
    _persist_recovery(state, recovery, tokens, args, with_token_metadata=False)
    write_state(state_dir, state)
    log(
        f"auto_retry #{pending_retry_count}: "
        f"sig={sig} sleeping {wait:.0f}s before POST /run"
    )
    sleep_interruptibly(wait, stop)
    if stop["flag"]:
        _restore_failed_task_block(task_block, status, err_or_msg, completed_at)
        return RetryOutcome("break", "signal", status or "Unknown")

    post_result = http_request(run_url, tokens.header, args.timeout, method="POST")
    if post_result.is_auth_failure():
        log("auto_retry: POST /run got auth failure")
        refreshed = args.token_refresh_cmd and tokens.refresh_reactive(stop)
        if stop["flag"]:
            _restore_failed_task_block(task_block, status, err_or_msg, completed_at)
            return RetryOutcome("break", "signal", status or "Unknown")
        if refreshed:
            post_result = http_request(run_url, tokens.header, args.timeout, method="POST")
        if (not refreshed) or post_result.is_auth_failure():
            recovery.last_auth_error_at = now_iso()
            if recovery.auth_status != "broken":
                recovery.auth_status = "broken"
                recovery.auth_broken_started_at = recovery.last_auth_error_at
                recovery.visibility_lost_at_monotonic = time.monotonic()
                if refreshed:
                    reason = "refreshed token still rejected"
                else:
                    reason = "refresh failed" if args.token_refresh_cmd else "refresh unavailable"
                log(f"auth_broken: entering — POST /run auth failure; {reason}")
            _persist_recovery(state, recovery, tokens, args, with_token_metadata=False)
            write_state(state_dir, state)
            return RetryOutcome("continue")

    if post_result.status == 0:
        # Transport error during the auto-retry POST itself
        # (URLError / OSError / timeout — see http_request()).
        # This is the exact transient class auto-retry exists
        # to recover from; treat it the same as a poll-loop
        # transport blip: log, do NOT consume an auto-retry
        # slot, do NOT mark terminal — just continue and let
        # the next iteration try POST /run again with the
        # standard backoff schedule. Without this, a single
        # network blip during the recovery window would write
        # exit_reason=run_post_failed_0 and kill the daemon.
        log(
            f"auto_retry: POST /run transport error "
            f"({redact_error(post_result.text, max_len=200)!r}); will retry next cycle"
        )
        return RetryOutcome("continue")

    post_conflict_running = False
    if post_result.status == 409:
        followup = http_request(tokens.validate_url, tokens.header, args.timeout)
        if followup.ok:
            try:
                followup_status = status_label(followup.json().get("status"))
            except ValueError as e:
                log(f"auto_retry: POST /run returned 409 but follow-up task JSON was invalid ({e}); will continue polling before deciding")
                return RetryOutcome("continue")
            post_conflict_running = followup_status == "Running"
            if not post_conflict_running:
                log(
                    f"auto_retry: POST /run returned 409 but follow-up task "
                    f"status={followup_status}; treating as retry failure"
                )
        else:
            detail = "transport error" if followup.status == 0 else f"status={followup.status}"
            log(
                f"auto_retry: POST /run returned 409 but follow-up task poll "
                f"failed ({detail}); will continue polling before deciding"
            )
            return RetryOutcome("continue")

    if post_result.ok or post_conflict_running:
        # 409 is success only when a follow-up task poll confirms the run is
        # already in flight. Other 409s mean the task is not currently runnable.
        recovery.auto_retries_total = pending_retry_count
        recovery.last_retry_at = now_iso()
        recovery.last_retried_signature = sig
        recovery.pending_retry_signature = None
        log(
            f"auto_retry: POST /run status={post_result.status}; "
            f"resuming poll (auto_retries_total={recovery.auto_retries_total})"
        )
        # Clear task.completed_at / status_detail / status so dashboard
        # stops showing terminal. Next poll will re-populate.
        task_block = task_state_block(state)
        task_block.pop("completed_at", None)
        task_block.pop("status_detail", None)
        task_block["status"] = "Running"
        _persist_recovery(state, recovery, tokens, args, with_token_metadata=False)
        write_state(state_dir, state)
        return RetryOutcome("continue", reset_cadence=True)

    # POST /run hard-failed for a non-auth reason.
    log(
        f"auto_retry: POST /run failed status={post_result.status} "
        f"body={redact_error(post_result.text, max_len=200)!r}; giving up"
    )
    _restore_failed_task_block(task_block, "Failed", err_or_msg, completed_at)
    return RetryOutcome("break", f"run_post_failed_{post_result.status}", "Failed")


def _compute_next_interval(
    merge_stats: MergeStats,
    elapsed: float,
    args: argparse.Namespace,
    interval: float,
    consecutive_idle: int,
    status: str | None,
    status_changed: bool,
) -> tuple[float, int]:
    """Compute the next poll interval and consecutive-idle counter, mirroring
    the "snap back on change, exponential backoff while idle" rules. Logs
    one summary line per cycle (kept inside the helper so main()'s loop body
    stays compact)."""
    if merge_stats.any_change or status_changed:
        next_interval = args.fast_interval if elapsed < args.fast_window else args.interval
        if merge_stats.any_change:
            log(
                f"poll: a={merge_stats.assistant_appended} u={merge_stats.user_appended} "
                f"r={merge_stats.collapsed_repeats} status={status} next={next_interval:.0f}s"
            )
        else:
            log(f"poll: status changed status={status} next={next_interval:.0f}s")
        return next_interval, 0
    next_idle = consecutive_idle + 1
    if elapsed < args.fast_window:
        next_interval = args.fast_interval
    elif next_idle >= 3:
        next_interval = min(max(interval, args.interval) * 1.5, args.max_interval)
    else:
        next_interval = args.interval
    log(f"poll: idle ({next_idle}) status={status} next={next_interval:.0f}s")
    return next_interval, next_idle


def _capacity_id_from_base_url(base_url: str) -> str | None:
    """Extract /capacities/<id>/ from SparkCore direct-route base URLs."""
    match = re.search(r"/capacities/([^/]+)/workloads/", base_url)
    return match.group(1) if match else None


def _build_terminal_payload(
    args: argparse.Namespace,
    recovery: RecoveryState,
    tokens: TokenManager,
    state: dict[str, Any],
    exit_reason: str,
    exit_status: str,
) -> dict[str, Any]:
    """Compose the terminal.json payload written from the finally block.

    If the daemon exits while the sticky mid-run-error trigger is still set
    (e.g., max_runtime fires mid-retry, machine sleep, SIGTERM during
    recovery), fall back to that as the visible last_error_message so the
    terminal banner can still explain what was happening. Otherwise the user
    gets a terminal banner with no error context — exactly the gap we are
    fixing."""
    task_block = task_state_block(state)
    last_error = task_block.get("status_detail")
    terminal_error = last_error
    if exit_status != "Completed":
        terminal_error = terminal_error or recovery.last_trigger_error
    exit_code = _exit_code_for(exit_reason)
    return {
        "status": exit_status,
        "reason": exit_reason,
        "exit_code": exit_code,
        "task_id": args.task_id,
        "workspace_id": task_block.get("workspace_id"),
        "workspace_name": task_block.get("workspace_name"),
        "lakehouse_id": task_block.get("lakehouse_id"),
        "lakehouse_name": task_block.get("lakehouse_name"),
        "capacity_id": task_block.get("capacity_id") or _capacity_id_from_base_url(args.base_url),
        "session_id": task_block.get("session_id"),
        "auto_retries_total": recovery.auto_retries_total,
        "auto_retries_exhausted": recovery.auto_retries_exhausted,
        "token_refresh_count": tokens.refresh_count,
        "last_error_message": terminal_error,
        "last_retry_trigger_error": recovery.last_trigger_error,
        "last_retry_trigger_error_at": recovery.last_trigger_error_at,
        "operation_id": task_block.get("operation_id"),
        "completed_at": task_block.get("completed_at"),
        "exited_at": now_iso(),
    }


def _exit_code_for(exit_reason: str) -> int:
    """Map an exit_reason tag to the daemon's process exit code. See
    `_EXIT_CODES` for the full table; `run_post_failed_<HTTP>` collapses to
    a single code (6) regardless of the suffix."""
    if exit_reason.startswith("run_post_failed_"):
        return 6
    return _EXIT_CODES.get(exit_reason, 1)


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    args = _build_arg_parser().parse_args()

    state_dir = Path(args.state_dir).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_path = state_dir / "poller.pid"
    pid_path.write_text(str(os.getpid()))

    # Archive any stale terminal.json from a prior run so the agent doesn't
    # read it on re-engage and think the new run already exited.
    archived_terminal_json = archive_stale_terminal_json(state_dir)

    token = _resolve_initial_token(args)
    if not token:
        log(f"FATAL: no token (--token-file missing/empty and ${args.token_env} unset)")
        state = load_state(state_dir / "state.json")
        task_block = task_state_block(state)
        task_block["id"] = args.task_id
        payload = {
            "status": "Failed",
            "reason": "no_token_at_startup",
            "exit_code": _exit_code_for("no_token_at_startup"),
            "task_id": args.task_id,
            "workspace_id": task_block.get("workspace_id"),
            "workspace_name": task_block.get("workspace_name"),
            "lakehouse_id": task_block.get("lakehouse_id"),
            "lakehouse_name": task_block.get("lakehouse_name"),
            "capacity_id": task_block.get("capacity_id") or _capacity_id_from_base_url(args.base_url),
            "session_id": task_block.get("session_id"),
            "operation_id": task_block.get("operation_id"),
            "auto_retries_total": int_or_zero((state.get("recovery") or {}).get("auto_retries_total")),
            "auto_retries_exhausted": bool((state.get("recovery") or {}).get("auto_retries_exhausted")),
            "token_refresh_count": int_or_zero((state.get("recovery") or {}).get("token_refresh_count")),
            "last_error_message": task_block.get("status_detail"),
            "last_retry_trigger_error": (state.get("recovery") or {}).get("last_trigger_error"),
            "last_retry_trigger_error_at": (state.get("recovery") or {}).get("last_trigger_error_at"),
            "completed_at": task_block.get("completed_at"),
            "exited_at": now_iso(),
        }
        try:
            write_terminal_state(state_dir, state, payload)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                pid_path.unlink()
            except OSError:
                pass
        return _exit_code_for("no_token_at_startup")

    base_url = args.base_url.rstrip("/")
    task_url = f"{base_url}/{args.task_id}"
    messages_url = f"{task_url}/messages"
    run_url = f"{task_url}/run"

    tokens = TokenManager(
        token=token,
        auth_scheme=args.auth_scheme,
        token_file=Path(args.token_file) if args.token_file else None,
        refresh_cmd=args.token_refresh_cmd,
        refresh_timeout=args.token_refresh_timeout,
        validate_url=task_url,  # task GET is cheap and covers token + routing
        http_timeout=args.timeout,
        log=log,
    )
    recovery = RecoveryState()
    backoff_schedule = parse_backoff_schedule(args.retry_backoff_seconds)

    # Rebuild ndjson seen-set from disk so resumed runs don't double-write.
    ndjson_path = state_dir / "messages.ndjson"
    ndjson_seen = load_ndjson_seen(ndjson_path)

    state = load_state(state_dir / "state.json")
    # A respawned poller is live; clear any stale terminal payload left by a
    # previous poller process so the dashboard's "Poller stopped" banner
    # disappears. If the prior poller exited cleanly and wrote terminal state,
    # this respawn is an explicit "try again" and should get a fresh retry
    # budget. If there is no terminal marker (machine sleep, OOM, kill -9),
    # hydrate run-scoped retry state so a simple resume does not lose context.
    stale_terminal = state.pop("terminal", None)
    if stale_terminal is not None or archived_terminal_json:
        log("cleared stale terminal marker from previous poller run; retry budget reset")
        rec = state.get("recovery")
        if isinstance(rec, dict):
            rec["auto_retries_total"] = 0
            rec["auto_retries_exhausted"] = False
            rec["auth_status"] = "ok"
            rec["last_progress_at"] = now_iso()
            for key in (
                "last_auth_error_at",
                "last_retry_at",
                "last_retried_signature",
                "pending_retry_signature",
                "last_trigger_error",
                "last_trigger_error_at",
                "last_trigger_error_signature",
                "last_retry_message_seq",
            ):
                rec.pop(key, None)
        write_state(state_dir, state)
    else:
        recovery.hydrate_from_state(state, args.task_id)
    rec = state.get("recovery") or {}
    tokens.refresh_count = max(tokens.refresh_count, int_or_zero(rec.get("token_refresh_count")))
    tokens.last_refreshed_at = rec.get("token_refreshed_at")
    if not recovery.last_progress_at:
        recovery.last_progress_at = now_iso()
    # Monotonic start timestamp (NOT wall-clock) so elapsed computation is
    # immune to clock adjustments / NTP jumps during long runs.
    start_time = time.monotonic()
    last_token_refresh_mono = time.monotonic()
    interval = args.fast_interval
    consecutive_idle = 0

    stop = {"flag": False}
    _install_signal_handlers(stop)

    log(
        f"poller started: pid={os.getpid()} task={args.task_id} state_dir={state_dir} "
        f"max_runtime={args.max_runtime}s max_auto_retries={args.max_auto_retries} "
        f"no_progress_window={args.no_progress_window_seconds}s "
        f"refresh_cmd={'set' if args.token_refresh_cmd else 'unset'}"
    )

    # exit_reason and exit_status are intentionally different shapes:
    #   - exit_reason: daemon-internal tag (lowercase snake_case); joins
    #     the same set as "crash", "signal", "max_runtime",
    #     "terminal_status", "no_progress_window", etc. Consumed by
    #     terminal.json readers as a machine-friendly key.
    #   - exit_status: mirrors the orchestrator's task.status field, which
    #     ships capitalized strings ("Running", "Completed", "Failed",
    #     "Cancelled"). Default "Unknown" matches that capitalization
    #     so downstream renderers can compare or display it without
    #     case-juggling.
    exit_reason: str = "unknown"
    exit_status: str = "Unknown"

    try:
        while not stop["flag"]:
            # Reload state from disk each cycle so out-of-band agent edits to
            # agent-authored fields (summary, intake.*, spec,
            # task.workspace_name, task.lakehouse_name, etc.) survive.
            state = load_state(state_dir / "state.json")
            task_block = task_state_block(state)
            previous_status = task_block.get("status")
            elapsed = time.monotonic() - start_time
            if elapsed > args.max_runtime:
                log(f"max-runtime reached ({args.max_runtime}s); exiting")
                exit_reason = "max_runtime"
                exit_status = task_state_block(state).get("status") or "Unknown"
                break

            # ---- proactive token refresh ----
            if (
                args.token_refresh_cmd
                and recovery.auth_status == "ok"
                and (time.monotonic() - last_token_refresh_mono) >= args.token_refresh_interval
            ):
                ok = tokens.refresh_proactive(stop)
                # Reset timer whether or not it succeeded — we don't want to
                # spin tight on a failing cmd; reactive will catch real expiry.
                last_token_refresh_mono = time.monotonic()
                if not ok:
                    log("token_refresh: proactive validation failed; continuing with current token")
                if stop["flag"]:
                    exit_reason = "signal"
                    exit_status = task_state_block(state).get("status") or "Unknown"
                    break

            # ---- HTTP poll (with reactive refresh on auth failure) ----
            msgs_result = http_request(messages_url, tokens.header, args.timeout)
            task_result = http_request(task_url, tokens.header, args.timeout)

            auth_outcome, last_token_refresh_mono = _handle_auth_failure(
                msgs_result, task_result, recovery, tokens, args,
                state, state_dir, stop, consecutive_idle, last_token_refresh_mono,
            )
            if auth_outcome == "refreshed":
                continue
            if auth_outcome == "broken":
                consecutive_idle += 1
                continue

            # Either poll failed for a non-auth reason (transient network etc.)?
            if not msgs_result.ok or not task_result.ok:
                log(
                    f"poll: non-auth error msgs={msgs_result.status} task={task_result.status}; backing off"
                )
                visible_no_progress = _no_progress_window_exceeded(recovery, args)
                if visible_no_progress is not None:
                    log(
                        f"no_progress_window: no assistant progress for "
                        f"{visible_no_progress:.0f}s (> {args.no_progress_window_seconds}s); exiting"
                    )
                    exit_reason = "no_progress_window"
                    exit_status = task_state_block(state).get("status") or "Unknown"
                    break
                sleep_interruptibly(min(interval * 2, args.max_interval), stop)
                continue

            try:
                msgs_payload = msgs_result.json()
                task_payload = task_result.json()
            except ValueError as e:
                log(f"poll: invalid JSON response; backing off ({e})")
                visible_no_progress = _no_progress_window_exceeded(recovery, args)
                if visible_no_progress is not None:
                    log(
                        f"no_progress_window: no assistant progress for "
                        f"{visible_no_progress:.0f}s (> {args.no_progress_window_seconds}s); exiting"
                    )
                    exit_reason = "no_progress_window"
                    exit_status = task_state_block(state).get("status") or "Unknown"
                    break
                sleep_interruptibly(min(interval * 2, args.max_interval), stop)
                continue

            # Both polls succeeded and returned parseable payloads.
            _clear_auth_broken_if_set(recovery)
            recovery.last_successful_poll_at = now_iso()

            polled_msgs = msgs_payload.get("messages") or []
            if not isinstance(polled_msgs, list):
                polled_msgs = []

            # Audit log first (deduped against its own seen set).
            append_ndjson(ndjson_path, polled_msgs, ndjson_seen)

            messages, merge_stats = merge_messages(state.get("messages", []), polled_msgs)
            state["messages"] = messages

            # Update task block. last_polled_at advances ONLY on successful polls
            # so the dashboard's freshness signal is honest during auth_broken.
            task_block = task_state_block(state)
            task_block["id"] = args.task_id
            task_block["last_polled_at"] = now_iso()
            completed_at, err, operation_id = _apply_task_payload(
                task_block,
                task_payload,
                ignored_error_signature=recovery.last_retried_signature,
                ignored_error_since=recovery.last_retry_at,
            )

            status = task_block.get("status")
            status_changed = status_label(previous_status) != status_label(status)
            terminal = is_terminal(status) or bool(err) or bool(completed_at)

            # Advance progress / clear sticky mid-run-error trigger.
            _update_progress_and_trigger(recovery, merge_stats)

            # ---- auto-retry decision (only on terminal Failed) ----
            if terminal and status not in {"Cancelled", "Canceled"} and (status == "Failed" or err):
                _persist_recovery(state, recovery, tokens, args)
                outcome = _handle_terminal_failed(
                    state=state,
                    state_dir=state_dir,
                    recovery=recovery,
                    tokens=tokens,
                    args=args,
                    backoff_schedule=backoff_schedule,
                    run_url=run_url,
                    merge_stats=merge_stats,
                    status=status,
                    err=err,
                    completed_at=completed_at,
                    operation_id=operation_id,
                    stop=stop,
                )
                if outcome.action == "continue":
                    if outcome.reset_cadence:
                        # Reset cadence so we observe the new run quickly.
                        interval = args.fast_interval
                        consecutive_idle = 0
                    continue
                if outcome.reason:
                    exit_reason = outcome.reason
                    exit_status = outcome.status
                break

            _persist_recovery(state, recovery, tokens, args)
            write_state(state_dir, state)

            # Non-failed terminal (Completed / Cancelled).
            if terminal:
                log(f"terminal status={status}; exiting")
                exit_reason = "terminal_status"
                exit_status = status or "Unknown"
                break

            visible_no_progress = _no_progress_window_exceeded(recovery, args)
            if visible_no_progress is not None:
                log(
                    f"no_progress_window: no assistant progress for "
                    f"{visible_no_progress:.0f}s (> {args.no_progress_window_seconds}s); exiting"
                )
                exit_reason = "no_progress_window"
                exit_status = status or "Unknown"
                break

            # ---- adaptive cadence (non-terminal path) ----
            interval, consecutive_idle = _compute_next_interval(
                merge_stats, elapsed, args, interval, consecutive_idle, status, status_changed,
            )
            sleep_interruptibly(interval, stop)
    except Exception as e:  # noqa: BLE001
        log(f"poller crashed: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        exit_reason = "crash"
        exit_status = "Unknown"
    else:
        # Loop exited without raising and without `break` setting a reason —
        # only path here is `stop["flag"]` flipping in response to SIGTERM /
        # SIGINT. Tag it so terminal.json carries an honest reason instead of
        # the default "unknown" sentinel.
        if exit_reason == "unknown":
            exit_reason = "signal"
            exit_status = task_state_block(state).get("status") or "Unknown"
    finally:
        # Single terminal-write path covers every exit reason.
        try:
            _persist_recovery(state, recovery, tokens, args)
        except Exception:  # noqa: BLE001
            pass
        terminal_payload = _build_terminal_payload(
            args, recovery, tokens, state, exit_reason, exit_status
        )
        # Also mirror into state.js so the dashboard (which cannot fetch a
        # sibling JSON over file://) can render the exit reason banner.
        try:
            write_terminal_state(state_dir, state, terminal_payload)
        except Exception:  # noqa: BLE001
            pass
        try:
            pid_path.unlink()
        except OSError:
            pass
        log(f"poller stopped (reason={exit_reason}, status={exit_status})")

    return _exit_code_for(exit_reason)


if __name__ == "__main__":
    raise SystemExit(main())
