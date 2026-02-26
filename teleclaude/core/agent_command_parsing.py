"""Shared parsing helpers for agent command leading-token semantics."""

from collections.abc import Sequence

from teleclaude.core.agents import get_known_agents
from teleclaude.helpers.agent_types import ThinkingMode

_THINKING_MODES = set(ThinkingMode.choices())


def split_leading_agent_token(
    args: Sequence[str],
    *,
    allow_implicit_mode: bool,
) -> tuple[str | None, list[str]]:
    """Split agent command args into requested agent and remaining args.

    Behavior:
    - Known first token -> explicit agent.
    - Thinking-mode first token (when allowed) -> implicit agent selection.
    - Any other non-empty first token -> explicit agent candidate (validated downstream).
    """
    if not args:
        return None, []

    first_raw = args[0].strip()
    if not first_raw:
        return None, list(args)

    first = first_raw.lower()
    if first in set(get_known_agents()):
        return first, list(args[1:])

    if allow_implicit_mode and first in _THINKING_MODES:
        return None, list(args)

    return first_raw, list(args[1:])
