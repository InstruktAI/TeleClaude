"""AI-driven project onboarding: dispatch quality-config assessment and doc-snippet analysis.

The dispatchers spawn TeleClaude agent sessions in tmux via ``telec sessions
run``. ``run_onboard`` chains init plumbing with both AI dispatches; the
individual ``run_analyze`` and ``run_assess`` entry points exist for targeted
re-runs.

This module is the *only* owner of the agent-session dispatches that used to
live in ``init_flow.py``. ``init`` itself stays plumbing-only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from enum import Enum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.project_setup.init_flow import init_project

logger = get_logger(__name__)


_ANALYZE_COMMAND = "/projects-analyze"
_ASSESS_COMMAND = "/projects-assess-config"

# Bounded so a stalled daemon API can't block the operator forever.
_DISPATCH_TIMEOUT_S = 300
_LIST_TIMEOUT_S = 10


class DedupState(Enum):
    """Result of a dedup lookup against the daemon's session list.

    ``UNKNOWN`` distinguishes lookup failure (timeout, OS error, bad JSON,
    non-zero exit) from a confirmed absence of a matching open session. Callers
    must refuse to dispatch when the state is ``UNKNOWN`` rather than treat it
    as ``INACTIVE`` — silent degradation here would spawn duplicate long-running
    sessions.
    """

    INACTIVE = "inactive"
    ACTIVE = "active"
    UNKNOWN = "unknown"


def _active_session_for_command(project_root: Path, command_slug: str) -> DedupState:
    """Probe the daemon for an open session running ``command_slug`` for ``project_root``.

    Match contract: same project_path AND title starts with the slash command
    AND lifecycle is not closed. Lookup failure surfaces as ``UNKNOWN`` so the
    caller can fail closed instead of dispatching blind.
    """
    # subprocess justification: the TeleClaude HTTP API client (TelecAPIClient)
    # is async-only; this dispatcher runs in a sync codepath that is also entered
    # from CLI/init contexts where bringing up an asyncio loop just to enumerate
    # sessions adds complexity without value. Shelling to the same daemon via
    # `telec sessions list` routes through the same identity gate as native callers.
    cmd = [sys.executable, "-m", "teleclaude.cli.telec", "sessions", "list"]
    try:
        result = subprocess.run(cmd, check=False, timeout=_LIST_TIMEOUT_S, capture_output=True, text=True)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Dedup lookup failed (%s); treating state as UNKNOWN", exc)
        return DedupState.UNKNOWN
    if result.returncode != 0:
        logger.warning("Dedup lookup returned rc=%d; treating state as UNKNOWN", result.returncode)
        return DedupState.UNKNOWN
    try:
        sessions = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("Dedup lookup produced invalid JSON (%s); treating state as UNKNOWN", exc)
        return DedupState.UNKNOWN
    if not isinstance(sessions, list):
        logger.warning("Dedup lookup payload not a list; treating state as UNKNOWN")
        return DedupState.UNKNOWN

    target_path = str(project_root)
    for entry in sessions:
        if not isinstance(entry, dict):
            continue
        if entry.get("project_path") != target_path:
            continue
        title = entry.get("title") or ""
        if not isinstance(title, str) or not title.startswith(command_slug):
            continue
        if entry.get("closed_at"):
            continue
        return DedupState.ACTIVE
    return DedupState.INACTIVE


def _dispatch_session(project_root: Path, command_slug: str, label: str) -> bool:
    """Spawn a TeleClaude agent session running ``command_slug``.

    Returns True on confirmed dispatch. Returns False on skip (active session
    already running), unknown dedup state (fail closed — never dispatch blind),
    bad return code, timeout, or OS-level failure.
    """
    state = _active_session_for_command(project_root, command_slug)
    if state is DedupState.ACTIVE:
        print(f"Skipping {label}: a {command_slug} session is already running for this project.")
        return False
    if state is DedupState.UNKNOWN:
        print(
            f"Skipping {label}: could not verify whether a {command_slug} session is already running. "
            f"Investigate the daemon, then retry with:"
        )
        print(f"  telec sessions run --command {command_slug} --project {project_root}")
        return False

    # subprocess justification: same as the dedup lookup — the TeleClaude HTTP
    # API client is async-only and this dispatcher runs in a sync codepath. The
    # CLI subprocess routes through the same daemon API as the native client.
    cmd = [
        sys.executable,
        "-m",
        "teleclaude.cli.telec",
        "sessions",
        "run",
        "--command",
        command_slug,
        "--project",
        str(project_root),
    ]
    try:
        result = subprocess.run(cmd, check=False, timeout=_DISPATCH_TIMEOUT_S, capture_output=True, text=True)
        if not result.returncode:
            print(f"{label} session started ({command_slug}).")
            return True
        logger.warning("%s dispatch failed (rc=%d): %s", label, result.returncode, result.stderr.strip())
        print(f"{label} session could not be started. Retry with:")
        print(f"  telec sessions run --command {command_slug} --project {project_root}")
    except subprocess.TimeoutExpired:
        logger.warning("%s dispatch timed out after %ds", label, _DISPATCH_TIMEOUT_S)
        print(f"{label} session timed out. Retry with:")
        print(f"  telec sessions run --command {command_slug} --project {project_root}")
    except OSError as exc:
        logger.warning("Could not launch %s session: %s", label, exc)
        print(f"Could not launch {label} session. Retry with:")
        print(f"  telec sessions run --command {command_slug} --project {project_root}")
    return False


def run_analyze(project_root: Path) -> bool:
    """Dispatch the doc-snippet analysis agent for ``project_root``."""
    return _dispatch_session(project_root, _ANALYZE_COMMAND, "Doc-snippet analysis")


def run_assess(project_root: Path) -> bool:
    """Dispatch the quality-tool config assessment agent for ``project_root``."""
    return _dispatch_session(project_root, _ASSESS_COMMAND, "Config assessment")


def run_onboard(project_root: Path) -> None:
    """Full project bootstrap: init plumbing, then dispatch assess + analyze.

    init runs synchronously; the AI dispatches are fire-and-forget — they
    return as soon as the session is registered and then run concurrently in
    tmux. Operator monitors progress via ``telec sessions list`` / TUI.
    """
    init_project(project_root)
    run_assess(project_root)
    run_analyze(project_root)
