"""Compose a checkpoint result into its semantic body, or return silence when nothing is to be enforced.

The body is unrendered: the delivery path that reaches the agent wraps it in the checkpoint envelope.
"""

import shlex

from teleclaude.hooks.checkpoint._directives import _ESCAPE_HATCH, _RESPONSE_POLICY
from teleclaude.hooks.checkpoint._git import _is_docs_only
from teleclaude.hooks.checkpoint._models import CheckpointResult

__all__ = ["_commit_instruction", "_compose_checkpoint_message", "_undeclared_write_question"]

# The bare call surfaces the commit gate on every branch; the approval flag is
# the committing agent's own act and never part of a checkpoint instruction.
_COMMIT_INSTRUCTION = "Execute `telec repo commit` (no flags) to surface the commit flow."
_UNDECLARED_WRITE_QUESTION_TEMPLATE = (
    "Possible undeclared shell writes?\n"
    "These dirty files were named by successful shell commands: {paths}\n"
    "Do any of these belong to your shell work? If so, declare only those files with `{command}`."
)
_REPO_ADD_COMMAND_PREFIX = ("telec", "repo", "add")
_CHECKPOINT_SECTION_SEPARATOR = "\n\n"
_CHECKPOINT_LINE_SEPARATOR = "\n"
_PATH_LIST_SEPARATOR = ", "
_EMPTY_TEXT = ""
_NO_CODE_CHANGES = "No code changes detected this turn."
_CHECKPOINT_TITLE = "Context-aware checkpoint"
_ALL_CLEAR_MESSAGE = "All expected validations were observed."


def _commit_instruction() -> str:
    """Commit instruction for the checkpoint message."""
    return _COMMIT_INSTRUCTION


def _undeclared_write_question(paths: tuple[str, ...]) -> str:
    """Render the unnumbered advisory question for matched dirty paths."""
    command = shlex.join((*_REPO_ADD_COMMAND_PREFIX, *paths))
    return _UNDECLARED_WRITE_QUESTION_TEMPLATE.format(paths=_PATH_LIST_SEPARATOR.join(paths), command=command)


def _question_checkpoint(lead: str, question: str) -> str:
    """Join a silent-branch lead and the advisory question with the checkpoint contract."""
    return _CHECKPOINT_SECTION_SEPARATOR.join((lead, question, _RESPONSE_POLICY, _ESCAPE_HATCH))


def _compose_checkpoint_message(git_files: list[str], result: CheckpointResult) -> str | None:
    """Compose the checkpoint body, or silence when there is nothing to enforce."""
    commit_line = _commit_instruction()
    commit_lines = [commit_line] if result.commit_action_required else []
    question = _undeclared_write_question(result.undeclared_candidates) if result.undeclared_candidates else _EMPTY_TEXT

    # Special case: docs only (bare *.md/txt/rst with no category and no pending actions)
    if (not git_files or _is_docs_only(git_files)) and not result.required_actions and not result.observations:
        if not commit_lines and not question:
            return None
        if question:
            lead = _NO_CODE_CHANGES if git_files else _CHECKPOINT_TITLE
            body = " ".join(commit_lines)
            return _question_checkpoint(
                _CHECKPOINT_LINE_SEPARATOR.join(part for part in (lead, body) if part), question
            )
        body = " ".join(commit_lines)
        return f"{_NO_CODE_CHANGES}\n{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}"

    # Special case: all clear
    if result.is_all_clear:
        if not result.commit_action_required and not question:
            return None
        if question:
            body = " ".join((_ALL_CLEAR_MESSAGE, *commit_lines))
            return _question_checkpoint(body or _CHECKPOINT_TITLE, question)
        body = " ".join((_ALL_CLEAR_MESSAGE, *commit_lines))
        return f"{body}\n\n{_RESPONSE_POLICY}\n\n{_ESCAPE_HATCH}"

    lines: list[str] = [_CHECKPOINT_TITLE]

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

    if question:
        lines.extend((_EMPTY_TEXT, question))

    lines.append("")
    if not actions:
        lines.append("Review and resolve the observations before responding to the user.")
        lines.append("")
    lines.append(_RESPONSE_POLICY)
    lines.append("")
    lines.append(_ESCAPE_HATCH)

    return "\n".join(lines)
