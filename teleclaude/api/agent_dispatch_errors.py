"""HTTP translation for typed agent-dispatch refusals."""

from fastapi import HTTPException

from teleclaude.core.agent_dispatch import (
    AgentDispatchFailure,
    AgentDispatchOutcome,
    AgentDispatchReason,
    AgentDispatchStage,
    emit_agent_dispatch_decision,
)
from teleclaude.core.command_dispatch import RemoteDispatchError, RemoteDispatchReason
from teleclaude.core.models import AgentDispatchMode, JsonDict, SessionEntryPoint
from teleclaude.core.session_startup_message import StartupMessageError

_BAD_REQUEST_REASONS = frozenset(
    {
        AgentDispatchReason.FIXED_AGENT_REQUIRED,
        AgentDispatchReason.PREFERRED_AGENT_REQUIRED,
        AgentDispatchReason.UNKNOWN_AGENT,
        AgentDispatchReason.DISABLED_AGENT,
    }
)
_CONFLICT_REASONS = frozenset(
    {
        AgentDispatchReason.FIXED_AGENT_UNAVAILABLE,
        AgentDispatchReason.NO_ELIGIBLE_CANDIDATE,
    }
)


def agent_dispatch_http_refusal(error: Exception) -> HTTPException | None:
    """Map expected dispatch refusals to clear, typed client responses."""
    if isinstance(error, AgentDispatchFailure):
        if error.reason in _BAD_REQUEST_REASONS:
            status_code = 400
        elif error.reason in _CONFLICT_REASONS:
            status_code = 409
        elif error.reason is AgentDispatchReason.AVAILABILITY_READ_FAILED:
            status_code = 503
        else:
            return None
        return HTTPException(status_code=status_code, detail=f"{error.reason.value}: {error}")
    if isinstance(error, RemoteDispatchError):
        status_code = 409 if error.reason is RemoteDispatchReason.TARGET_DISPATCH_CAPABILITY_REQUIRED else 502
        return HTTPException(status_code=status_code, detail=f"{error.reason.value}: {error}")
    if isinstance(error, StartupMessageError):
        return HTTPException(status_code=400, detail=f"startup_message_invalid: {error}")
    return None


def run_dispatch_refusal_reason(error: Exception) -> AgentDispatchReason | None:
    """Return the closed RUN_OUTCOME reason for a dispatch-boundary refusal."""

    if isinstance(error, AgentDispatchFailure):
        return error.reason
    if isinstance(error, RemoteDispatchError):
        if error.reason is RemoteDispatchReason.TARGET_DISPATCH_CAPABILITY_REQUIRED:
            return AgentDispatchReason.TARGET_CAPABILITY_MISSING
        return AgentDispatchReason.RUN_REQUEST_REJECTED
    return None


def present_routing_explanation(
    data: JsonDict,
    *,
    human_facing: bool,
    request_id: str | None,
    session_id: str | None,
    entry_point: SessionEntryPoint,
) -> str | None:
    """Return a fallback explanation only to an authorized human-facing client."""
    selected_agent = data.get("agent")
    routing_reason = data.get("routing_reason")
    try:
        fallback_reason = AgentDispatchReason(str(routing_reason))
    except ValueError:
        fallback_reason = None
    fallback = fallback_reason in {
        AgentDispatchReason.MANUAL_PREFERENCE_UNAVAILABLE,
        AgentDispatchReason.DETERMINISTIC_INELIGIBILITY,
    }
    included = human_facing and fallback
    emit_agent_dispatch_decision(
        stage=AgentDispatchStage.RESPONSE_PRESENTED,
        outcome=AgentDispatchOutcome.FALLBACK if fallback else AgentDispatchOutcome.SELECTED,
        reason=(fallback_reason or AgentDispatchReason.RESPONSE_PRESENTED),
        selected_agent=selected_agent if isinstance(selected_agent, str) else None,
        request_id=request_id,
        session_id=session_id,
        entry_point=entry_point,
        routing_explanation_included=included,
    )
    if not included:
        return None
    return f"Selected '{selected_agent}' using the configured fallback order because the preferred candidate was unavailable."


def emit_run_outcome(
    *,
    selected_agent: str | None,
    request_id: str | None,
    session_id: str | None = None,
    entry_point: SessionEntryPoint,
    dispatch_mode: AgentDispatchMode,
    outcome: AgentDispatchOutcome = AgentDispatchOutcome.PREPARED,
    reason: AgentDispatchReason | None = None,
    working_slug_present: bool | None = None,
) -> None:
    """Record the completed run-session API boundary."""
    emit_agent_dispatch_decision(
        stage=AgentDispatchStage.RUN_OUTCOME,
        outcome=outcome,
        reason=reason
        or (
            AgentDispatchReason.RUN_REQUEST_ACCEPTED
            if outcome is AgentDispatchOutcome.PREPARED
            else AgentDispatchReason.RUN_REQUEST_REJECTED
        ),
        selected_agent=selected_agent,
        request_id=request_id,
        session_id=session_id,
        entry_point=entry_point,
        dispatch_mode=dispatch_mode,
        working_slug_present=working_slug_present,
    )


def run_refusal_outcome(reason: AgentDispatchReason) -> AgentDispatchOutcome:
    """Map typed run guards to their closed terminal outcome vocabulary."""
    if reason is AgentDispatchReason.REVIEWER_CONFLICT:
        return AgentDispatchOutcome.CONFLICT
    return AgentDispatchOutcome.REJECTED


def emit_run_accepted(
    *,
    request_id: str,
    agent_supplied: bool,
    entry_point: SessionEntryPoint,
    command_kind: str | None,
    working_slug_present: bool,
    caller_kind_present: bool,
    producer_agent: str | None,
    preferred_agent: str | None,
    fixed_agent: str | None,
    decision_basis_digest: str,
) -> AgentDispatchMode:
    """Record a run request before any run guard may reject it."""
    mode = AgentDispatchMode.MANUAL_PREFERENCE if agent_supplied else AgentDispatchMode.AUTOMATIC
    emit_agent_dispatch_decision(
        stage=AgentDispatchStage.ACCEPTED,
        outcome=AgentDispatchOutcome.PREPARED,
        reason=AgentDispatchReason.RECEIVED,
        request_id=request_id,
        dispatch_mode=mode,
        entry_point=entry_point,
        agent_supplied=agent_supplied,
        command_kind=command_kind,
        working_slug_present=working_slug_present,
        caller_kind_present=caller_kind_present,
        producer_agent=producer_agent,
        preferred_agent=preferred_agent,
        fixed_agent=fixed_agent,
        decision_basis_digest=decision_basis_digest,
    )
    return mode
