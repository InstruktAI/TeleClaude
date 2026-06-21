"""Shared script and message formatters for next-machine actor orchestration."""

from __future__ import annotations

from teleclaude.core.next_machine.output_formatting import HEARTBEAT_RESET_INSTRUCTION, format_send_command


def format_reviewer_direct_fix_message(
    *,
    fixer_session_id: str,
    task_context: str,
    completion_clause: str,
) -> str:
    """Build the reviewer message that opens the worker-owned direct fix link.

    Used by the work lifecycle, where reviewer ↔ fixer direct-link collaboration
    is the established pattern.
    """
    return (
        f"A fixer is active at {fixer_session_id}. "
        f"Start a direct conversation: telec sessions send {fixer_session_id} '<your findings summary>' --direct. "
        f"{task_context} "
        f"{completion_clause}"
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
