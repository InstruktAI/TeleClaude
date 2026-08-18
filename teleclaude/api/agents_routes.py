"""Agent availability and status endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.api.auth import (
    CallerIdentity,
    clearance_agents_availability,
    clearance_agents_status,
)
from teleclaude.api_models import AgentAvailabilityDTO, AgentStatusRequest, ModelAvailabilityDTO
from teleclaude.config import config
from teleclaude.core.agents import get_known_agents, normalize_agent_name
from teleclaude.core.db import db

logger = get_logger(__name__)

router = APIRouter(tags=["agents"])
_AGENT_AVAILABILITY_EXCEPTIONS = (OSError, RuntimeError, SQLAlchemyError, ValueError)


def _normalize_model_unavailability_until(value: str) -> str:
    """Validate and normalize a model outage expiry to an explicit UTC instant."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="model unavailability expiry must be ISO8601 UTC") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=400, detail="model unavailability expiry must include a UTC offset")
    return parsed.astimezone(UTC).isoformat()


def _build_agent_dto(
    agent: str,
    info: dict[str, bool | str | None] | None,
    models: list[dict[str, str]] | None = None,
) -> AgentAvailabilityDTO:
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
            models=[ModelAvailabilityDTO(**row) for row in models or []],
        )
    # No record means agent is available (never marked unavailable)
    return AgentAvailabilityDTO(
        agent=agent,
        available=True,
        status="available",
        models=[ModelAvailabilityDTO(**row) for row in models or []],
    )


@router.get("/agents/availability")
async def get_agent_availability(
    _identity: CallerIdentity = Depends(clearance_agents_availability),
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
            models = await db.list_model_availability(agent)
        except _AGENT_AVAILABILITY_EXCEPTIONS as exc:
            logger.error("Failed to get availability for agent %s: %s", agent, exc)
            result[agent] = AgentAvailabilityDTO(
                agent=agent,
                available=None,  # Unknown due to DB error
                error=str(exc),
            )
            continue

        result[agent] = _build_agent_dto(agent, info, models)

    return result


@router.post("/agents/{agent}/status")
async def set_agent_status(
    agent: str,
    request: AgentStatusRequest,
    _identity: CallerIdentity = Depends(clearance_agents_status),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Set agent dispatch status (available/unavailable/degraded).

    Marks an agent as available, unavailable, or degraded, each with an optional expiry.
    Use clear=true to reset to available. Requires admin clearance.
    """
    try:
        agent_name = normalize_agent_name(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        model = request.model
        if model is not None:
            agent_config = config.agents[agent_name]
            known_models = {entry.model for chain in agent_config.mode_chains.values() for entry in chain} | {
                entry.model for chain in agent_config.model_chains.values() for entry in chain
            }
            if model not in known_models:
                allowed_models = ", ".join(sorted(known_models))
                raise HTTPException(status_code=400, detail=f"unknown model '{model}'; allowed: {allowed_models}")
            if request.status not in {None, "unavailable"}:
                raise HTTPException(status_code=400, detail="model status must be unavailable")
            if not request.clear and request.until is None:
                raise HTTPException(status_code=400, detail="model unavailability requires an expiry")
            if request.duration_minutes is not None:
                raise HTTPException(status_code=400, detail="model availability requires an absolute expiry")
            if not request.clear and request.until is not None:
                request = request.model_copy(update={"until": _normalize_model_unavailability_until(request.until)})
        if request.clear:
            await db.mark_agent_available(agent_name, model=model or "")
        else:
            normalized_status = (request.status or "unavailable").strip().lower()
            if normalized_status not in {"available", "unavailable", "degraded"}:
                raise HTTPException(
                    status_code=400,
                    detail="status must be one of: available, unavailable, degraded",
                )

            if normalized_status == "available":
                await db.mark_agent_available(agent_name, model=model or "")
            elif normalized_status == "degraded":
                degraded_until = request.until
                if degraded_until is None and request.duration_minutes is not None:
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
                expiry = (
                    request.until
                    if model
                    else (request.until or (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat())
                )
                await db.mark_agent_unavailable(agent_name, expiry, request.reason, model=model or "")

        info = await db.get_agent_availability(agent_name)
        models = await db.list_model_availability(agent_name)
        return _build_agent_dto(agent_name, info, models).model_dump()
    except _AGENT_AVAILABILITY_EXCEPTIONS as exc:
        logger.error("set_agent_status failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to set agent status: {exc}") from exc
