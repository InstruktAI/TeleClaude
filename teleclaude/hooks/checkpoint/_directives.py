"""Agent-facing directive text shared by checkpoint message composers."""

from teleclaude.constants import CheckpointAction

__all__ = ["_ESCAPE_HATCH", "_RESPONSE_POLICY", "_surface_run"]

_RESPONSE_POLICY = (
    "Response policy: complete ALL required actions first. "
    "Do not compose the debrief until every action is done. "
    "Then end with a short user-relevant debrief about actual task outcome, blocker, or decision needed. "
    "Do not mention checkpoint chores."
)
_ESCAPE_HATCH = (
    "Escape hatch (last resort only, and only when there is no actionable information left): "
    'run `touch "$TMPDIR/teleclaude_checkpoint_clear"` to skip checkpoints for this turn; '
    "it clears at the next user prompt. If the same checkpoint recurs across turns, "
    "surface it as a bug instead of clearing it again."
)


def _surface_run(action: CheckpointAction, log_since_window: str) -> str:
    """Render an action's surfaced instruction, filling the {window} placeholder."""
    return action.run.replace("{window}", log_since_window)
