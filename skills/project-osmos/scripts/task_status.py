# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Normalize Project Osmos task status values returned by deployed routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from python_runtime import require_supported_python


require_supported_python()


TERMINAL_STRINGS = {"completed", "failed", "cancelled", "canceled"}

# Canonical enum order:
#   0=Created, 1=Running, 2=Cancelling, 3=Cancelled, 4=Completed, 5=Failed
STATUS_BY_CODE = {0: "Created", 1: "Running", 2: "Cancelling", 3: "Cancelled", 4: "Completed", 5: "Failed"}


def status_label(status: Any) -> str:
    """Return the canonical label for string, numeric, and stringified-numeric status values."""
    if status is None:
        return "Created"
    if isinstance(status, bool):
        return str(status)
    if isinstance(status, int):
        return STATUS_BY_CODE.get(status, f"Status {status}")
    if isinstance(status, str):
        stripped = status.strip()
        if not stripped:
            return "Created"
        if stripped.isdigit():
            return STATUS_BY_CODE.get(int(stripped), f"Status {stripped}")
        return stripped
    return str(status)


def is_terminal_status(status: Any) -> bool:
    """Return whether a status value is an explicit terminal status."""
    return status_label(status).casefold() in TERMINAL_STRINGS


def task_run_details(task: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return runDetails when it is an object, otherwise an empty mapping."""
    run_details = task.get("runDetails")
    return run_details if isinstance(run_details, Mapping) else {}


def _has_value(value: Any) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


def is_task_terminal(task: Mapping[str, Any]) -> bool:
    """Classify terminal tasks using status plus deployed runDetails completion evidence."""
    if is_terminal_status(task.get("status")):
        return True
    run_details = task_run_details(task)
    return _has_value(run_details.get("completedAt")) or _has_value(run_details.get("errorMessage"))


def is_task_running(task: Mapping[str, Any]) -> bool:
    """Return true only for a live Running task with no completion or error evidence."""
    return status_label(task.get("status")).casefold() == "running" and not is_task_terminal(task)
