"""Agent availability and status endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.agent_registry import AgentName, registry_digest
from teleclaude.api.auth import (
    CallerIdentity,
    clearance_agents_availability,
    clearance_agents_status,
)
from teleclaude.api.event_serialization import availability_legacy_fields
from teleclaude.api_models import AgentAvailabilityDTO, AgentStatusRequest, ModelAvailabilityDTO
from teleclaude.config import config
from teleclaude.core.agent_availability import AgentAvailabilityStatus, AvailabilityState
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
    info: AvailabilityState | None,
    models: dict[str, AvailabilityState] | None = None,
) -> AgentAvailabilityDTO:
    """Project typed availability state onto the compatible agent DTO."""
    state = info or AvailabilityState(AgentAvailabilityStatus.AVAILABLE, None, None)
    available, unavailable_until, degraded_until = availability_legacy_fields(state.status, state.status_until)
    return AgentAvailabilityDTO(
        agent=agent,
        available=available,
        status=state.status,
        status_until=state.status_until,
        unavailable_until=unavailable_until,
        degraded_until=degraded_until,
        reason=state.reason,
        models=[
            ModelAvailabilityDTO(
                model=model,
                status=model_state.status,
                status_until=model_state.status_until,
                unavailable_until=availability_legacy_fields(model_state.status, model_state.status_until)[1],
                reason=model_state.reason,
            )
            for model, model_state in (models or {}).items()
        ],
    )


@router.get("/agents/availability")
async def get_agent_availability(
    _identity: CallerIdentity = Depends(clearance_agents_availability),
) -> dict[str, AgentAvailabilityDTO]:
    """Get agent availability."""
    result: dict[str, AgentAvailabilityDTO] = {}
    known_agents = get_known_agents()
    logger.info(
        "agent_runtime.agent_inventory.projected registry_digest=%s agent_count=%s",
        registry_digest(),
        len(known_agents),
    )

    for agent in known_agents:
        cfg = config.agents.get(AgentName.from_str(agent))
        if cfg and not cfg.enabled:
            result[agent] = AgentAvailabilityDTO(
                agent=agent,
                available=False,
                status=AgentAvailabilityStatus.UNAVAILABLE,
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
            agent_config = config.agents[AgentName.from_str(agent_name)]
            known_models = {entry.model for chain in agent_config.mode_chains.values() for entry in chain} | {
                entry.model for chain in agent_config.model_chains.values() for entry in chain
            }
            if model not in known_models:
                allowed_models = ", ".join(sorted(known_models))
                raise HTTPException(status_code=400, detail=f"unknown model '{model}'; allowed: {allowed_models}")
            if not request.clear and request.status != "available" and request.until is None:
                raise HTTPException(status_code=400, detail="non-available model status requires an expiry")
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
                    model=model or "",
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
