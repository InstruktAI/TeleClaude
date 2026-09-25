"""Render a checkpoint result into the agent-facing checkpoint text, or return silence when nothing is to be enforced."""

from teleclaude.core.injected_text import checkpoint_text
from teleclaude.hooks.checkpoint._directives import _ESCAPE_HATCH, _RESPONSE_POLICY
from teleclaude.hooks.checkpoint._git import _is_docs_only
from teleclaude.hooks.checkpoint._models import CheckpointResult

__all__ = ["_commit_instruction", "_compose_checkpoint_message", "_declare_reminder_instruction"]


def _commit_instruction(on_main: bool) -> str:
    """Branch-aware commit instruction for the checkpoint message."""
    if on_main:
        return "Execute `telec code commit` (no flags) to surface the menu."
    return "Commit your changes with `telec code commit --approved '<message>'`"


def _declare_reminder_instruction() -> str:
    """Reminder emitted beside a commit action, for any file not yet declared."""
    return "Declare any file you changed that isn't declared yet: `telec code add <path>...`"


def _compose_checkpoint_message(git_files: list[str], result: CheckpointResult) -> str | None:
    """Compose checkpoint text, or silence when there is nothing to enforce."""
    commit_line = _commit_instruction(result.on_main)
    commit_lines = [commit_line, _declare_reminder_instruction()] if result.commit_action_required else []

    # Special case: docs only (bare *.md/txt/rst with no category and no pending actions)
    if (not git_files or _is_docs_only(git_files)) and not result.required_actions and not result.observations:
        if not commit_lines:
            return None
        body = " ".join(commit_lines)
        return checkpoint_text(f"No code changes detected this turn.\n{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}")

    # Special case: all clear
    if result.is_all_clear:
        if not result.commit_action_required:
            return None
        body = " ".join(
            [
                "All expected validations were observed.",
                *commit_lines,
            ]
        )
        return checkpoint_text(f"{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}")

    lines: list[str] = ["Context-aware checkpoint"]

    # Changed files summary grouped by category
    if result.categories:
        lines.append("")
        lines.append(f"Changed: {', '.join(result.categories)}")

    # Required actions (numbered). The commit instruction belongs to the action list
    # whenever any action applies — including a pending commit that has no other required
    # action (e.g. an uncommitted no-action turn). This guarantees an uncommitted change
    # is never silently dropped on a branch that lacks code actions.
    actions = list(result.required_actions)
    if result.required_actions or result.commit_action_required:
        if result.commit_action_required:
            actions.append(commit_line)
            actions.append(_declare_reminder_instruction())

    if actions:
        lines.append("")
        lines.append("Required actions (BLOCKING — do not resume user-facing work until all complete):")
        for i, action in enumerate(actions, 1):
            lines.append(f"{i}. {action}")

    # Observations (bullet points)
    if result.observations:
        lines.append("")
        lines.append("Observations:")
        for obs in result.observations:
            lines.append(f"- {obs}")

    lines.append("")
    if not actions:
        lines.append("Review and resolve the observations before responding to the user.")
        lines.append("")
    lines.append(_RESPONSE_POLICY)
    lines.append("")
    lines.append(_ESCAPE_HATCH)

    return checkpoint_text("\n".join(lines))
