"""Configuration-derived launch facts for canonical scheduled agent jobs."""

from __future__ import annotations

from pathlib import Path

from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api_models import RunSessionRequest
from teleclaude.config.loader import load_project_config
from teleclaude.constants import JOB_SPEC_ID_PREFIX, SlashCommand
from teleclaude.core.agent_dispatch import AgentDispatchReason, RunSessionThinkingMode
from teleclaude.core.agents import normalize_agent_name
from teleclaude.core.session_startup_message import resolve_command_document
from teleclaude.paths import ConfigFileName

_JOB_COMMAND_ARGUMENTS_INVALID_DETAIL = "next-run-job requires configured job and job specification arguments"
_JOB_COMMAND_CONFIGURATION_UNAVAILABLE_DETAIL = "configured job declaration is unavailable"
_JOB_COMMAND_NOT_CONFIGURED_DETAIL = "configured agent job is unavailable"
_JOB_COMMAND_SPEC_MISMATCH_DETAIL = "job specification does not match the configured declaration"
_JOB_COMMAND_OVERRIDE_FORBIDDEN_DETAIL = "next-run-job does not accept caller agent or thinking-mode overrides"
_JOB_COMMAND_DOCUMENT_UNAVAILABLE_DETAIL = "next-run-job command document is unavailable"
_JOB_COMMAND_AGENT_UNAVAILABLE_DETAIL = "configured agent job has no agent"
_JOB_COMMAND_DEPRECATED_MESSAGE_DETAIL = "configured agent job uses deprecated message configuration"
_AGENT_JOB_TYPE = "agent"


def normalize_job_run_request(request: RunSessionRequest, args: str) -> tuple[str, RunSessionThinkingMode, str]:
    """Derive fixed job-launch facts from the authoritative project declaration."""
    parts = args.split()
    if len(parts) != 2:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_ARGUMENTS_INVALID_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    if "agent" in request.model_fields_set or "thinking_mode" in request.model_fields_set:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_OVERRIDE_FORBIDDEN_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    job_name, job_spec_id = parts
    try:
        schedule = load_project_config(Path(request.project) / ConfigFileName.OVERLAY).jobs.get(job_name)
    except (OSError, ValueError) as exc:
        raise RunSessionRefusal(
            status_code=503,
            detail=_JOB_COMMAND_CONFIGURATION_UNAVAILABLE_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        ) from exc
    if schedule is None or schedule.type != _AGENT_JOB_TYPE:
        raise RunSessionRefusal(
            status_code=404,
            detail=_JOB_COMMAND_NOT_CONFIGURED_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    if schedule.message:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_DEPRECATED_MESSAGE_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    if not schedule.job:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_NOT_CONFIGURED_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    expected_spec_id = f"{JOB_SPEC_ID_PREFIX}{schedule.job}"
    if job_spec_id != expected_spec_id:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_SPEC_MISMATCH_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    if resolve_command_document(SlashCommand.NEXT_RUN_JOB.value) is None:
        raise RunSessionRefusal(
            status_code=503,
            detail=_JOB_COMMAND_DOCUMENT_UNAVAILABLE_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    if not schedule.agent:
        raise RunSessionRefusal(
            status_code=503,
            detail=_JOB_COMMAND_AGENT_UNAVAILABLE_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    try:
        agent = normalize_agent_name(schedule.agent)
        thinking_mode = RunSessionThinkingMode(str(schedule.thinking_mode or RunSessionThinkingMode.FAST.value))
    except ValueError as exc:
        raise RunSessionRefusal(
            status_code=503,
            detail=_JOB_COMMAND_CONFIGURATION_UNAVAILABLE_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        ) from exc
    return agent, thinking_mode, job_name
