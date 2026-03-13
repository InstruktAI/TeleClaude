"""Agent availability and status endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import (
    CLEARANCE_AGENTS_AVAILABILITY,
    CLEARANCE_AGENTS_STATUS,
    CallerIdentity,
)
from teleclaude.api_models import AgentAvailabilityDTO, AgentStatusRequest
from teleclaude.config import config
from teleclaude.core.agents import get_known_agents, normalize_agent_name
from teleclaude.core.db import db

logger = get_logger(__name__)

router = APIRouter(tags=["agents"])


def _build_agent_dto(agent: str, info: dict[str, bool | str | None] | None) -> AgentAvailabilityDTO:
    """Convert db agent availability info dict to DTO."""
    if info:
        unavail_until = info.get("unavailable_until")
        degraded_until = info.get("degraded_until")
        reason_val = info.get("reason")
        status_val = info.get("status")
        status_text = str(status_val) if status_val in {"available", "unavailable", "degraded"} else None
        return AgentAvailabilityDTO(
            agent=agent,
            available=bool(info.get("available", True)),
            status=status_text,
            unavailable_until=str(unavail_until) if unavail_until and unavail_until is not True else None,
            degraded_until=str(degraded_until) if degraded_until and degraded_until is not True else None,
            reason=str(reason_val) if reason_val and reason_val is not True else None,
        )
    # No record means agent is available (never marked unavailable)
    return AgentAvailabilityDTO(
        agent=agent,
        available=True,
        status="available",
    )


@router.get("/agents/availability")
async def get_agent_availability(
    identity: CallerIdentity = Depends(CLEARANCE_AGENTS_AVAILABILITY),
) -> dict[str, AgentAvailabilityDTO]:
    """Get agent availability."""
    result: dict[str, AgentAvailabilityDTO] = {}

    for agent in get_known_agents():
        cfg = config.agents.get(agent)
        if cfg and not cfg.enabled:
            result[agent] = AgentAvailabilityDTO(
                agent=agent,
                available=False,
                status="unavailable",
                reason="Disabled in config.yml",
            )
            continue

        try:
            info = await db.get_agent_availability(agent)
        except Exception as e:
            logger.error("Failed to get availability for agent %s: %s", agent, e)
            result[agent] = AgentAvailabilityDTO(
                agent=agent,
                available=None,  # Unknown due to DB error
                error=str(e),
            )
            continue

        result[agent] = _build_agent_dto(agent, info)

    return result


@router.post("/agents/{agent}/status")
async def set_agent_status(
    agent: str,
    request: AgentStatusRequest,
    identity: CallerIdentity = Depends(CLEARANCE_AGENTS_STATUS),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Set agent dispatch status (available/unavailable/degraded).

    Marks an agent as available, unavailable (with optional expiry), or degraded.
    Use clear=true to reset to available. Requires admin clearance.
    """
    try:
        agent_name = normalize_agent_name(agent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        if request.clear:
            await db.mark_agent_available(agent_name)
        else:
            normalized_status = (request.status or "unavailable").strip().lower()
            if normalized_status not in {"available", "unavailable", "degraded"}:
                raise HTTPException(
                    status_code=400,
                    detail="status must be one of: available, unavailable, degraded",
                )

            if normalized_status == "available":
                await db.mark_agent_available(agent_name)
            elif normalized_status == "degraded":
                degraded_until: str | None = None
                if request.duration_minutes is not None:
                    degraded_until = (datetime.now(UTC) + timedelta(minutes=request.duration_minutes)).isoformat()
                await db.mark_agent_degraded(
                    agent_name,
                    request.reason or "degraded",
                    degraded_until=degraded_until,
                )
            else:
                if not request.reason:
                    raise HTTPException(status_code=400, detail="reason required when marking unavailable")
                minutes = request.duration_minutes or 30
                expiry = request.unavailable_until or (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()
                await db.mark_agent_unavailable(agent_name, expiry, request.reason)

        info = await db.get_agent_availability(agent_name)
        return _build_agent_dto(agent_name, info).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("set_agent_status failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to set agent status: {e}") from e
