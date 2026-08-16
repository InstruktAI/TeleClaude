"""AI-driven project onboarding: dispatch quality-config assessment and doc-snippet analysis.

The dispatchers spawn TeleClaude agent sessions in tmux via the daemon's
``POST /sessions/run`` endpoint. ``run_onboard`` chains init plumbing with both
AI dispatches; the individual ``run_analyze`` and ``run_assess`` entry points
exist for targeted re-runs.

This module is the *only* owner of the agent-session dispatches that used to
live in ``init_flow.py``. ``init`` itself stays plumbing-only.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.api_models import RunSessionRequest
from teleclaude.cli.tool_client import ToolAPIError, tool_api_request
from teleclaude.project_setup.init_flow import init_project

logger = get_logger(__name__)


_ANALYZE_COMMAND = "/projects-analyze"
_ASSESS_COMMAND = "/projects-assess-config"

# Bounded so a stalled daemon API can't block the operator forever.
_DISPATCH_TIMEOUT_S = 30.0
_LIST_TIMEOUT_S = 10.0


class DedupState(Enum):
    """Result of a dedup lookup against the daemon's session list.

    ``UNKNOWN`` distinguishes lookup failure (transport error, malformed
    response) from a confirmed absence of a matching open session. Callers
    must refuse to dispatch when the state is ``UNKNOWN`` rather than treat it
    as ``INACTIVE`` — silent degradation here would spawn duplicate long-running
    sessions.
    """

    INACTIVE = "inactive"
    ACTIVE = "active"
    UNKNOWN = "unknown"


def _active_session_for_command(project_root: Path, command_slug: str) -> DedupState:
    """Probe the daemon for an open session running ``command_slug`` for ``project_root``.

    Queries the daemon with ``all=true`` so the dedup probe sees sessions
    spawned by any caller, not just the current one — a caller-filtered view
    would miss a parallel onboarding in flight from a different shell.

    Match contract: same project_path AND title starts with the slash command
    AND lifecycle is not closed. Lookup failure surfaces as ``UNKNOWN`` so the
    caller can fail closed instead of dispatching blind.
    """
    try:
        sessions = tool_api_request("GET", "/sessions", params={"all": "true"}, timeout=_LIST_TIMEOUT_S)
    except ToolAPIError as exc:
        logger.warning(
            "dedup_lookup_failed",
            command=command_slug,
            project_root=str(project_root),
            error=str(exc),
            state="unknown",
        )
        return DedupState.UNKNOWN
    if not isinstance(sessions, list):
        logger.warning(
            "dedup_lookup_unexpected_payload",
            command=command_slug,
            project_root=str(project_root),
            payload_type=type(sessions).__name__,
            state="unknown",
        )
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
    or daemon-side failure.
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
        print(f"  telec sessions run --command {command_slug} --path {project_root}")
        return False

    # exclude_unset preserves an omitted agent until the daemon's routing boundary.
    request = RunSessionRequest(command=command_slug, project=str(project_root))
    try:
        tool_api_request(
            "POST",
            "/sessions/run",
            json_body=request.model_dump(mode="json", exclude_unset=True),
            timeout=_DISPATCH_TIMEOUT_S,
        )
    except ToolAPIError as exc:
        logger.warning(
            "dispatch_failed",
            command=command_slug,
            project_root=str(project_root),
            error=str(exc),
            status_code=exc.status_code,
            is_timeout=exc.is_timeout,
        )
        print(f"{label} session could not be started ({exc.message}). Retry with:")
        print(f"  telec sessions run --command {command_slug} --path {project_root}")
        return False
    print(f"{label} session started ({command_slug}).")
    return True


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
