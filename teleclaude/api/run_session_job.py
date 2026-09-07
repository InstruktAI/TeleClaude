"""Configuration-derived launch facts for canonical scheduled agent jobs."""

from __future__ import annotations

from pathlib import Path

from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api_models import RunSessionRequest
from teleclaude.config.loader import load_project_config
from teleclaude.config.schema import JobScheduleConfig, is_agent_job, job_identity
from teleclaude.constants import SlashCommand
from teleclaude.core.agent_dispatch import AgentDispatchReason, RunSessionThinkingMode
from teleclaude.core.agents import normalize_agent_name
from teleclaude.core.session_startup_message import resolve_command_document
from teleclaude.paths import ConfigFileName

_JOB_COMMAND_ARGUMENTS_INVALID_DETAIL = "next-run-job requires exactly one argument: the job's procedure snippet ID"
_JOB_COMMAND_CONFIGURATION_UNAVAILABLE_DETAIL = "configured job declaration is unavailable"
_JOB_COMMAND_NOT_CONFIGURED_DETAIL = "no configured agent job declares this procedure"
_JOB_COMMAND_AMBIGUOUS_DETAIL = "more than one configured agent job declares this procedure"
_JOB_COMMAND_OVERRIDE_FORBIDDEN_DETAIL = "next-run-job does not accept caller agent or thinking-mode overrides"
_JOB_COMMAND_DOCUMENT_UNAVAILABLE_DETAIL = "next-run-job command document is unavailable"
_JOB_COMMAND_AGENT_UNAVAILABLE_DETAIL = "configured agent job has no agent"
_JOB_COMMAND_DEPRECATED_MESSAGE_DETAIL = "configured agent job uses deprecated message configuration"


def _declared_agent_jobs(project: str, procedure_id: str) -> list[JobScheduleConfig]:
    jobs = load_project_config(Path(project) / ConfigFileName.OVERLAY).jobs
    return [
        schedule
        for name, schedule in jobs.items()
        if is_agent_job(schedule) and job_identity(name, schedule) == procedure_id
    ]


def normalize_job_run_request(request: RunSessionRequest, args: str) -> tuple[str, RunSessionThinkingMode, str]:
    """Derive fixed job-launch facts from the declaration whose `job:` pointer is the argument."""
    parts = args.split()
    if len(parts) != 1:
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
    procedure_id = parts[0]
    try:
        matches = _declared_agent_jobs(request.project, procedure_id)
    except (OSError, ValueError) as exc:
        raise RunSessionRefusal(
            status_code=503,
            detail=_JOB_COMMAND_CONFIGURATION_UNAVAILABLE_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        ) from exc
    if not matches:
        raise RunSessionRefusal(
            status_code=404,
            detail=_JOB_COMMAND_NOT_CONFIGURED_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    if len(matches) > 1:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_AMBIGUOUS_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    schedule = matches[0]
    if schedule.message:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_DEPRECATED_MESSAGE_DETAIL,
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
    return agent, thinking_mode, procedure_id
