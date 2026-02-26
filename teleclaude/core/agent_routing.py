"""Canonical routable-agent resolver for runtime launch paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NoReturn

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.agents import get_enabled_agents, get_known_agents, normalize_agent_name
from teleclaude.core.db import db

logger = get_logger(__name__)

RoutingErrorCode = Literal["unknown", "disabled", "unavailable", "degraded", "no_routable_agent"]
RoutingStatus = Literal["unknown", "disabled", "unavailable", "degraded", "none"]


@dataclass(frozen=True)
class AgentRoutingError(ValueError):
    """Deterministic routing rejection with stable error metadata."""

    message: str
    code: RoutingErrorCode
    source: str
    requested_agent: str | None = None
    status: RoutingStatus = "none"

    def __str__(self) -> str:
        return self.message


def _raise_routing_error(
    *,
    message: str,
    code: RoutingErrorCode,
    source: str,
    requested_agent: str | None,
    status: RoutingStatus,
) -> NoReturn:
    logger.warning(
        "agent routing rejected",
        source=source,
        requested_agent=requested_agent,
        reason=code,
        status=status,
        detail=message,
    )
    raise AgentRoutingError(
        message=message,
        code=code,
        source=source,
        requested_agent=requested_agent,
        status=status,
    )


def _disabled_message(agent: str) -> str:
    enabled = ", ".join(get_enabled_agents()) or "none"
    return (
        f"Agent '{agent}' is disabled by `config.yml:agents.{agent}.enabled`. "
        f"Enable it in config.yml or choose an enabled agent ({enabled})."
    )


async def _availability_status(agent: str, *, source: str) -> Literal["available", "unavailable", "degraded"]:
    try:
        availability = await db.get_agent_availability(agent)
    except Exception as exc:  # noqa: BLE001 - keep routing resilient when DB is temporarily unavailable.
        logger.warning(
            "agent routing availability lookup failed; assuming available",
            source=source,
            agent=agent,
            error=str(exc),
        )
        return "available"

    if not availability:
        return "available"

    status = str(availability.get("status") or "available").strip().lower()
    if status == "unavailable":
        return "unavailable"
    if status == "degraded":
        return "degraded"
    return "available"


async def _resolve_explicit_agent(requested_agent: str, *, source: str) -> str:
    try:
        normalized = normalize_agent_name(requested_agent)
    except ValueError:
        allowed = ", ".join(get_known_agents())
        _raise_routing_error(
            message=f"Unknown agent '{requested_agent}'. Allowed agents: {allowed}.",
            code="unknown",
            source=source,
            requested_agent=requested_agent,
            status="unknown",
        )

    cfg = config.agents.get(normalized)
    if not cfg or not cfg.enabled:
        _raise_routing_error(
            message=_disabled_message(normalized),
            code="disabled",
            source=source,
            requested_agent=normalized,
            status="disabled",
        )

    status = await _availability_status(normalized, source=source)
    if status == "unavailable":
        _raise_routing_error(
            message=f"Agent '{normalized}' is currently unavailable for runtime routing.",
            code="unavailable",
            source=source,
            requested_agent=normalized,
            status="unavailable",
        )
    if status == "degraded":
        _raise_routing_error(
            message=f"Agent '{normalized}' is currently degraded and blocked for runtime routing.",
            code="degraded",
            source=source,
            requested_agent=normalized,
            status="degraded",
        )

    return normalized


async def _resolve_implicit_agent(*, source: str) -> str:
    enabled_agents = get_enabled_agents()
    if not enabled_agents:
        _raise_routing_error(
            message="No enabled agents configured. Set config.yml:agents.<agent>.enabled to true.",
            code="no_routable_agent",
            source=source,
            requested_agent=None,
            status="none",
        )

    blocked: list[str] = []
    for candidate in enabled_agents:
        status = await _availability_status(candidate, source=source)
        if status == "available":
            return candidate
        blocked.append(f"{candidate}:{status}")

    details = ", ".join(blocked) if blocked else "none"
    _raise_routing_error(
        message=f"No routable agents are currently available (enabled candidates: {details}).",
        code="no_routable_agent",
        source=source,
        requested_agent=None,
        status="none",
    )


async def resolve_routable_agent(requested_agent: str | None, *, source: str) -> str:
    """Resolve a runtime-routable agent according to known/enabled/availability policy."""
    requested = requested_agent.strip() if isinstance(requested_agent, str) else ""
    if requested:
        return await _resolve_explicit_agent(requested, source=source)
    return await _resolve_implicit_agent(source=source)
