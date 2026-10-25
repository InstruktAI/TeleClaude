"""Shared script and message formatters for next-machine actor orchestration."""

from __future__ import annotations

from teleclaude.core.next_machine.output_formatting import (
    format_orchestration_watch_instruction,
)


def format_review_in_progress_script(slug: str, reviewer_id: str, *, next_step: str) -> str:
    """Script for continuing to watch an already-running reviewer session."""
    return (
        f"REVIEW IN PROGRESS: {slug}\n\n"
        f"Execute in order:\n\n"
        f"Do not dispatch a new reviewer. Reuse live reviewer session {reviewer_id}.\n"
        f"{format_orchestration_watch_instruction(slug=slug, restart_cadence=True)}\n"
        f"Wait for reviewer session {reviewer_id} to report idle.\n"
        f"When the signal arrives, call {next_step}."
    )
