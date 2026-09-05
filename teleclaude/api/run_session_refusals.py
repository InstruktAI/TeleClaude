"""Typed validation helpers for the run-session API boundary."""

import re

from fastapi import HTTPException

from teleclaude.api_models import RunSessionRequest
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.agents import normalize_agent_name

_COMMAND_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_COMMAND_SEPARATOR = "/"
_COMMAND_INVALID_TEMPLATE = "invalid command: {command}"


class RunSessionRefusal(HTTPException):
    """A run-session boundary refusal with its semantic reason attached."""

    def __init__(self, *, status_code: int, detail: str, reason: AgentDispatchReason) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.reason = reason


def normalize_run_session_command(command: str) -> str:
    """Validate a run-session command token before normalizing its optional slash."""
    has_leading_slash = command.startswith(_COMMAND_SEPARATOR)
    candidate = command.removeprefix(_COMMAND_SEPARATOR)
    segments = candidate.split(_COMMAND_SEPARATOR)
    valid_segments = all(_COMMAND_SEGMENT_PATTERN.fullmatch(segment) for segment in segments)
    accepts_shape = len(segments) == 1 or (len(segments) == 2 and not has_leading_slash)
    if not accepts_shape or not valid_segments:
        raise RunSessionRefusal(
            status_code=400,
            detail=_COMMAND_INVALID_TEMPLATE.format(command=command),
            reason=AgentDispatchReason.COMMAND_INVALID,
        )
    return candidate


def resolve_run_session_agent(request: RunSessionRequest) -> str | None:
    """Validate supplied identity without applying origin-machine agent policy."""
    if "agent" not in request.model_fields_set:
        return None
    try:
        return normalize_agent_name(request.agent)
    except ValueError as exc:
        raise RunSessionRefusal(status_code=400, detail=str(exc), reason=AgentDispatchReason.UNKNOWN_AGENT) from exc
