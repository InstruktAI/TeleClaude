"""Core-owned evidence for startup-message delivery."""

from __future__ import annotations

from enum import StrEnum

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

AGENT_STARTUP_DELIVERY_DECIDED_EVENT = "agent_startup_delivery_decided"


class AgentStartupDeliveryMode(StrEnum):
    """Closed delivery modes for startup-message placement."""

    FRESH_START = "fresh_start"
    HANDOFF = "handoff"


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
