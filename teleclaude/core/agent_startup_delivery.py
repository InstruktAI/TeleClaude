"""Core-owned evidence for startup-message delivery."""

from __future__ import annotations

from asyncio import Future
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_io
from teleclaude.core.agent_readiness import await_agent_readiness

logger = get_logger(__name__)

AGENT_STARTUP_DELIVERY_DECIDED_EVENT = "agent_startup_delivery_decided"
AGENT_STARTUP_DELIVERY_PROCESS_EXITED_ERROR = "agent process exited before startup message delivery"


class AgentStartupDeliveryMode(StrEnum):
    """Closed delivery modes for startup-message placement."""

    FRESH_START = "fresh_start"
    HANDOFF = "handoff"


if TYPE_CHECKING:
    from teleclaude.core.models import Session
    from teleclaude.core.tmux_io import UserTurnDeliveryResult


def emit_agent_startup_delivery_decision(
    *,
    session_id: str,
    agent_name: str,
    delivery_mode: AgentStartupDeliveryMode,
    outcome: str,
    reason: str,
    stage: str,
    paste_performed: bool,
    platform_enter_sent: bool,
    existing_input_preserved: bool,
) -> None:
    """Emit the single structured record for a decided startup delivery."""
    logger.info(
        AGENT_STARTUP_DELIVERY_DECIDED_EVENT,
        session_id=session_id,
        agent_name=agent_name,
        delivery_mode=delivery_mode.value,
        composer_observed=True,
        outcome=outcome,
        reason=reason,
        stage=stage,
        paste_performed=paste_performed,
        platform_enter_sent=platform_enter_sent,
        existing_input_preserved=existing_input_preserved,
    )


async def deliver_startup_message(
    *,
    session: Session,
    agent_name: str,
    message: str,
    ready_future: Future[None],
    quiet_s: float,
    timeout_s: float,
    delivery_mode: AgentStartupDeliveryMode,
) -> UserTurnDeliveryResult:
    """Wait on the provider's readiness authority, then submit one startup message."""
    await await_agent_readiness(
        agent_name=agent_name,
        session=session,
        session_id=session.session_id,
        ready_future=ready_future,
        quiet_s=quiet_s,
        timeout_s=timeout_s,
    )
    if not await tmux_io.is_process_running(session):
        raise RuntimeError(AGENT_STARTUP_DELIVERY_PROCESS_EXITED_ERROR)
    result = await tmux_io.inject_user_turn(session, message, active_agent=agent_name)
    emit_agent_startup_delivery_decision(
        session_id=session.session_id,
        agent_name=agent_name,
        delivery_mode=delivery_mode,
        outcome=result.outcome.value,
        reason=result.reason.value,
        stage=result.stage.value,
        paste_performed=result.paste_performed,
        platform_enter_sent=result.platform_enter_sent,
        existing_input_preserved=result.existing_input_preserved,
    )
    return result
