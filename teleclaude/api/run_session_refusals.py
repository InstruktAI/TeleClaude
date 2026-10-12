"""Typed validation helpers for the run-session API boundary."""

from fastapi import HTTPException

from teleclaude.api_models import RunSessionRequest
from teleclaude.constants import SlashCommand
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.agents import normalize_agent_name
from teleclaude.core.command_input import CommandInputError, normalize_command_input_token
from teleclaude.core.session_startup_message import AmbiguousCommandError, resolve_command_document


class RunSessionRefusal(HTTPException):
    """A run-session boundary refusal with its semantic reason attached."""

    def __init__(self, *, status_code: int, detail: str, reason: AgentDispatchReason) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.reason = reason


def normalize_run_session_command(command: str) -> str:
    """Validate a run-session command token before normalizing its optional slash."""
    try:
        return normalize_command_input_token(command)
    except CommandInputError as exc:
        raise RunSessionRefusal(
            status_code=400,
            detail=str(exc),
            reason=AgentDispatchReason.COMMAND_INVALID,
        ) from exc


def resolve_run_session_command(command: str) -> tuple[str, SlashCommand | None]:
    """Normalize a run-session command token to its canonical name and the slash command it names, if any."""
    normalized = normalize_run_session_command(command)
    try:
        resolved = resolve_command_document(normalized)
    except AmbiguousCommandError as exc:
        raise RunSessionRefusal(
            status_code=400,
            detail=str(exc),
            reason=AgentDispatchReason.COMMAND_INVALID,
        ) from exc
    if resolved is not None:
        normalized = resolved.canonical_name
    try:
        return normalized, SlashCommand(normalized)
    except ValueError:
        return normalized, None


def resolve_run_session_agent(request: RunSessionRequest) -> str | None:
    """Validate supplied identity without applying origin-machine agent policy."""
    if "agent" not in request.model_fields_set:
        return None
    try:
        return normalize_agent_name(request.agent)
    except ValueError as exc:
        raise RunSessionRefusal(status_code=400, detail=str(exc), reason=AgentDispatchReason.UNKNOWN_AGENT) from exc
