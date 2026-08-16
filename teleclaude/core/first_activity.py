"""Launch provenance that settles only when the output poller observes activity."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from teleclaude.core.agent_dispatch import (
    AgentDispatchOutcome,
    AgentDispatchReason,
    AgentDispatchStage,
    emit_agent_dispatch_decision,
)
from teleclaude.core.models import SessionLaunchIntent

FIRST_ACTIVITY_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class FirstActivityContext:
    launch_intent: SessionLaunchIntent


_contexts: dict[str, FirstActivityContext] = {}
_timeouts: dict[str, asyncio.Task[None]] = {}


def arm_first_activity(session_id: str, launch_intent: SessionLaunchIntent) -> None:
    """Wait for a true output observation after the launch is dispatched."""
    _contexts[session_id] = FirstActivityContext(launch_intent)
    if prior := _timeouts.pop(session_id, None):
        prior.cancel()

    async def _timeout() -> None:
        try:
            await asyncio.sleep(FIRST_ACTIVITY_TIMEOUT_S)
        except asyncio.CancelledError:
            return
        context = _contexts.pop(session_id, None)
        if context:
            _emit(
                session_id,
                context.launch_intent,
                AgentDispatchOutcome.FAILED,
                AgentDispatchReason.FIRST_ACTIVITY_TIMEOUT,
            )

    _timeouts[session_id] = asyncio.create_task(_timeout(), name=f"first-activity-{session_id}")


def record_first_activity(session_id: str) -> None:
    """Settle once on an OutputChanged event, not when polling is scheduled."""
    context = _contexts.pop(session_id, None)
    if context is None:
        return
    if timeout := _timeouts.pop(session_id, None):
        timeout.cancel()
    _emit(session_id, context.launch_intent, AgentDispatchOutcome.STARTED, AgentDispatchReason.FIRST_ACTIVITY)


def _emit(
    session_id: str, intent: SessionLaunchIntent, outcome: AgentDispatchOutcome, reason: AgentDispatchReason
) -> None:
    emit_agent_dispatch_decision(
        stage=AgentDispatchStage.LAUNCH_OUTCOME,
        outcome=outcome,
        reason=reason,
        selected_agent=intent.agent,
        request_id=intent.request_id,
        session_id=session_id,
        dispatch_mode=intent.dispatch_mode,
        entry_point=intent.entry_point,
        job_role=intent.job_role,
    )
