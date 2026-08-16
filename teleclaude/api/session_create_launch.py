"""Shared launch-intent helpers for session creation endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from teleclaude.api_models import CreateSessionRequest, ScheduledSessionRequest
from teleclaude.config.loader import load_project_config
from teleclaude.constants import ROLE_JOB_RUNNER
from teleclaude.core.agents import normalize_agent_name
from teleclaude.core.models import AgentDispatchMode, SessionEntryPoint, SessionLaunchKind
from teleclaude.paths import ConfigFileName


def resolve_enabled_agent(requested_agent: str | None) -> str:
    """Validate agent identity without applying origin-machine policy."""
    if requested_agent:
        try:
            return normalize_agent_name(requested_agent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail="agent required for a fixed launch")


def resolve_launch_kind(request: CreateSessionRequest) -> SessionLaunchKind:
    """Normalize implicit message launch without inferring resume from native IDs."""
    launch_kind = SessionLaunchKind(request.launch_kind)
    if launch_kind == SessionLaunchKind.AGENT and request.message:
        return SessionLaunchKind.AGENT_THEN_MESSAGE
    return launch_kind


@dataclass(frozen=True)
class ScheduledLaunch:
    """Daemon-derived scheduled launch facts; no client routing field participates."""

    agent: str | None
    thinking_mode: str
    message: str
    job: str
    entry_point: SessionEntryPoint = SessionEntryPoint.CRON
    dispatch_mode: AgentDispatchMode = AgentDispatchMode.AUTOMATIC
    system_role: str = ROLE_JOB_RUNNER


def resolve_scheduled_launch(request: ScheduledSessionRequest) -> ScheduledLaunch:
    """Load a configured agent job and derive its closed routing intent."""
    config_path = Path(request.project_path) / ConfigFileName.OVERLAY
    try:
        schedule = load_project_config(config_path).jobs.get(request.job)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="scheduled job configuration unavailable") from exc
    if schedule is None or schedule.type != "agent":
        raise HTTPException(status_code=404, detail="scheduled agent job not configured")
    if schedule.message:
        raise HTTPException(status_code=400, detail="scheduled agent job uses deprecated message configuration")
    if not str(schedule.job or "").strip():
        raise HTTPException(status_code=400, detail="scheduled agent job has no job configuration")
    agent = normalize_agent_name(schedule.agent) if schedule.agent else None
    return ScheduledLaunch(
        agent=agent,
        thinking_mode=str(schedule.thinking_mode or "fast"),
        message=f"/next-run-job {request.job}",
        job=request.job,
        dispatch_mode=AgentDispatchMode.FIXED if agent else AgentDispatchMode.AUTOMATIC,
    )


def scheduled_create_request(request: ScheduledSessionRequest, launch: ScheduledLaunch) -> CreateSessionRequest:
    """Build the generic shape only after scheduled facts are daemon-derived."""
    return CreateSessionRequest(
        computer=request.computer,
        project_path=request.project_path,
        launch_kind="agent_then_message",
        agent=launch.agent,
        thinking_mode=launch.thinking_mode,
        title=f"Job: {request.job}",
        message=launch.message,
    )
