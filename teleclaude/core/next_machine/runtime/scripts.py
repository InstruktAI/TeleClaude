"""Shared script and message formatters for next-machine actor orchestration."""

from __future__ import annotations

from teleclaude.core.next_machine._types import DEFAULT_MAX_REVIEW_ROUNDS
from teleclaude.core.next_machine.output_formatting import HEARTBEAT_RESET_INSTRUCTION, format_send_command


def format_reviewer_direct_fix_message(
    *,
    fixer_session_id: str,
    task_context: str,
    completion_clause: str,
) -> str:
    """Build the reviewer message that opens the worker-owned direct fix link.

    Used by the work lifecycle, where reviewer ↔ fixer direct-link collaboration
    is the established pattern. The prepare lifecycle uses
    ``format_reviewer_handoff_message`` instead — prepare reviewer dispatch is
    tail-only with no ``--direct`` link.
    """
    return (
        f"A fixer is active at {fixer_session_id}. "
        f"Start a direct conversation: telec sessions send {fixer_session_id} '<your findings summary>' --direct. "
        f"{task_context} "
        f"{completion_clause}"
    )


def format_reviewer_handoff_message(
    *,
    fixer_session_id: str,
    task_context: str,
    completion_clause: str,
) -> str:
    """Build the reviewer message that hands findings to the active fixer session.

    The reviewer writes findings to the findings artifact and idles; the
    fixer reads them on its next state-machine advance. Used by the prepare
    lifecycle.
    """
    return (
        f"A fixer is active at {fixer_session_id}. "
        f"Write your findings to the findings artifact and idle when done. "
        f"The fixer will read the artifact on its next state-machine advance. "
        f"{task_context} "
        f"{completion_clause}"
    )


def format_pair_missing_error(slug: str, phase_label: str) -> str:
    """Compatibility BLOCKED script for obsolete callers."""
    return (
        f"BLOCKED: {slug} {phase_label} cannot proceed because an obsolete prepare orchestration path was called.\n\n"
        f"Re-enter the v2 prepare state machine:\n  telec todo prepare {slug}"
    )


def format_review_needs_work_script(
    slug: str,
    worker_session_id: str,
    reviewer_session_id: str,
    message: str,
    *,
    next_step: str,
) -> str:
    """Script for NEEDS_WORK variant: reviewer writes findings; fixer reads them and re-advances.

    No ``--direct`` link is opened between the reviewer and the active fixer
    session. The reviewer writes its findings artifact and idles. The fixer
    (the active procedure in the prepare session) reads the findings on its
    next state-machine advance and addresses them in its own session.
    """
    completion_clause = (
        "Persist the full review-findings artifact and set verdict by arithmetic "
        "(APPROVE only when unresolved Critical and Important counts both reach zero). "
        "Then idle. The fixer reads your findings on its next state-machine advance."
    )
    reviewer_message = format_reviewer_handoff_message(
        fixer_session_id=worker_session_id,
        task_context=message,
        completion_clause=completion_clause,
    )
    return (
        f"REVIEW NEEDS WORK: {slug}\n\n"
        f"Execute in order:\n\n"
        f"Hand findings off to the reviewer:\n"
        f"{format_send_command(reviewer_session_id, reviewer_message)}\n\n"
        f"{HEARTBEAT_RESET_INSTRUCTION}\n"
        f"Wait for the fixer to address findings and advance the state machine; "
        f"the state machine will re-dispatch the reviewer when the artifact is updated.\n"
        f"Wait for reviewer session {reviewer_session_id} to report idle.\n"
        f"When the reviewer idles, call {next_step}."
    )


def format_review_blocked_script(
    slug: str,
    phase_label: str,
    reviewer_session_id: str | None,
    worker_session_id: str | None,
) -> str:
    """Script for BLOCKED variant: keep live sessions available for human inspection."""
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


def format_review_in_progress_script(slug: str, reviewer_id: str, *, next_step: str) -> str:
    """Script for continuing to watch an already-running reviewer session."""
    return (
        f"REVIEW IN PROGRESS: {slug}\n\n"
        f"Execute in order:\n\n"
        f"Do not dispatch a new reviewer. Reuse live reviewer session {reviewer_id}.\n"
        f"{HEARTBEAT_RESET_INSTRUCTION}\n"
        f"Wait for reviewer session {reviewer_id} to report idle.\n"
        f"When the signal arrives, call {next_step}."
    )


def _truncate_file_list(paths: list[str], limit: int = 6) -> str:
    """Render a compact comma-separated path list for reviewer follow-up messages."""
    if len(paths) <= limit:
        return ", ".join(paths)
    shown = ", ".join(paths[:limit])
    return f"{shown}, and {len(paths) - limit} more"


def format_review_ground_shift_script(
    slug: str,
    reviewer_id: str,
    previous_head: str,
    current_head: str,
    overlapping_files: list[str],
    *,
    next_step: str,
) -> str:
    """Script for nudging an existing reviewer when merged code overlaps reviewed files."""
    file_list = _truncate_file_list(overlapping_files)
    message = (
        f"Ground shifted for {slug}: origin/main merge advanced the review target from {previous_head} to "
        f"{current_head}. Keep focus on this todo only. Re-check only the overlapping reviewed files "
        f"({file_list}) and continue the same review session. If the merged changes are irrelevant to your "
        "existing findings, keep your current scope and verdict logic unchanged."
    )
    return (
        f"REVIEW GROUND SHIFTED: {slug}\n\n"
        f"Execute in order:\n\n"
        f"{format_send_command(reviewer_id, message)}\n\n"
        f"{HEARTBEAT_RESET_INSTRUCTION}\n"
        f"Wait for reviewer session {reviewer_id} to report idle.\n"
        f"When the signal arrives, call {next_step}."
    )
