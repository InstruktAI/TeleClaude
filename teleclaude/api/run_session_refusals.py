"""Typed validation helpers for the run-session API boundary."""

from fastapi import HTTPException

from teleclaude.api_models import RunSessionRequest
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.agents import normalize_agent_name


class RunSessionRefusal(HTTPException):
    """A run-session boundary refusal with its semantic reason attached."""

    def __init__(self, *, status_code: int, detail: str, reason: AgentDispatchReason) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.reason = reason


def resolve_run_session_agent(request: RunSessionRequest) -> str | None:
    """Validate supplied identity without applying origin-machine agent policy."""
    if "agent" not in request.model_fields_set:
        return None
    try:
        return normalize_agent_name(request.agent)
    except ValueError as exc:
        raise RunSessionRefusal(status_code=400, detail=str(exc), reason=AgentDispatchReason.UNKNOWN_AGENT) from exc
