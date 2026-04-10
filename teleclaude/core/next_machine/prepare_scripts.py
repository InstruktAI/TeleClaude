"""Prepare state machine — script and message formatters.

Pure string builders for the linear scripts the prepare state machine emits
to the orchestrator, and the findings relay messages sent to live workers.
No state mutation, no I/O — just string formatting.
"""

from __future__ import annotations

from teleclaude.core.next_machine._types import DEFAULT_MAX_REVIEW_ROUNDS

__all__ = [
    "_fix_findings_message",
    "_format_review_approved_script",
    "_format_review_blocked_script",
    "_format_review_needs_work_script",
]


def _fix_findings_message(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    slug: str,
    phase_label: str,
    rounds: int,
    open_count: int,
    findings_artifact: str,
    target_artifact: str,
) -> str:
    """Build the findings relay message sent to an existing worker session."""
    return (
        f"Round {rounds} {phase_label} review: {open_count} unresolved finding(s). "
        f"Findings artifact: `{findings_artifact}`. "
        f"Target artifact: `{target_artifact}`. "
        f"Required read: software-development/procedure/lifecycle/fix-review-findings. "
        f"Address the findings and report FIX COMPLETE. "
        f"Read findings via: telec todo artifacts read {slug} {findings_artifact}"
    )


def _format_review_approved_script(
    slug: str,
    reviewer_session_id: str | None,
    worker_session_id: str | None,
    phase_label: str,
) -> str:
    """Script for APPROVED variant: end phase sessions, call prepare to advance."""
    end_lines: list[str] = []
    if reviewer_session_id:
        end_lines.append(f"telec sessions end {reviewer_session_id}")
    if worker_session_id:
        end_lines.append(f"telec sessions end {worker_session_id}")
    end_block = "\n".join(end_lines) if end_lines else "(no live sessions for this phase to end)"
    return (
        f"{phase_label.upper()} REVIEW APPROVED: {slug}\n\nExecute in order:\n\n{end_block}\ntelec todo prepare {slug}"
    )


def _format_review_needs_work_script(
    slug: str,
    worker_session_id: str,
    reviewer_session_id: str,
    message: str,
) -> str:
    """Script for NEEDS_WORK variant: send findings to existing worker, wait on reviewer."""
    escaped = message.replace('"', '\\"')
    return (
        f"REVIEW NEEDS WORK: {slug}\n\n"
        f"Execute in order:\n\n"
        f'telec sessions send {worker_session_id} "{escaped}"\n\n'
        f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
        f'Start a new non-blocking heartbeat timer via Bash(command="sleep 300", run_in_background=true) '
        f"and save the new task_id.\n"
        f"Wait for reviewer session {reviewer_session_id} to report idle.\n"
        f"When the reviewer idles, call telec todo prepare {slug}."
    )


def _format_review_blocked_script(
    slug: str,
    phase_label: str,
    reviewer_session_id: str | None,
    worker_session_id: str | None,
) -> str:
    """Script for BLOCKED variant: sessions stay alive as signal for human."""
    live_sessions: list[str] = []
    if reviewer_session_id:
        live_sessions.append(f"Reviewer: {reviewer_session_id}")
    if worker_session_id:
        live_sessions.append(f"Worker: {worker_session_id}")
    sessions_block = "\n".join(f"  - {line}" for line in live_sessions) if live_sessions else "  (no live sessions)"
    return (
        f"BLOCKED: {slug} {phase_label} review exceeded {DEFAULT_MAX_REVIEW_ROUNDS} rounds. "
        f"Manual resolution required.\n\n"
        f"Live sessions kept alive for human inspection:\n"
        f"{sessions_block}\n\n"
        f"Before acting, load the relevant worker role:\n"
        f"  telec docs index\n"
        f"Then use telec docs get to load the procedure for the role you are assuming."
    )
