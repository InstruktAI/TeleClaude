"""Configuration-derived launch facts for canonical scheduled agent jobs."""

from __future__ import annotations

from pathlib import Path

from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api_models import RunSessionRequest
from teleclaude.config.jobs import EffectiveJob, load_effective_jobs
from teleclaude.config.schema import is_agent_job
from teleclaude.constants import SlashCommand
from teleclaude.core.agent_dispatch import AgentDispatchReason, RunSessionThinkingMode
from teleclaude.core.session_startup_message import resolve_command_document

_JOB_COMMAND_ARGUMENTS_INVALID_DETAIL = "run-job requires exactly one argument: the job name"
_JOB_COMMAND_CONFIGURATION_UNAVAILABLE_DETAIL = "configured job declaration is unavailable"
_JOB_COMMAND_NOT_CONFIGURED_DETAIL = "no configured job declares this name"
_JOB_COMMAND_NOT_AGENT_DETAIL = "configured job name does not identify an agent job"
_JOB_COMMAND_OVERRIDE_FORBIDDEN_DETAIL = "run-job does not accept caller agent or thinking-mode overrides"
_JOB_COMMAND_DOCUMENT_UNAVAILABLE_DETAIL = "run-job command document is unavailable"
_JOB_COMMAND_AGENT_UNAVAILABLE_DETAIL = "configured agent job has no candidates"


def _declared_jobs(project: str, job_name: str) -> list[EffectiveJob]:
    return [job for job in load_effective_jobs(Path(project)) if job.identity == job_name]


def normalize_job_run_request(
    request: RunSessionRequest, args: str
) -> tuple[tuple[str, ...], RunSessionThinkingMode, str, str]:
    """Derive declarative candidate order and launch facts for one named job."""
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
    job_name = parts[0]
    try:
        matches = _declared_jobs(request.project, job_name)
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
    schedule = matches[0].declaration
    if not is_agent_job(schedule) or schedule.job is None:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_NOT_AGENT_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    procedure_id = schedule.job.strip()
    if resolve_command_document(SlashCommand.RUN_JOB.value) is None:
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
        candidates = tuple(agent.value for agent in schedule.agent or [])
        thinking_mode = RunSessionThinkingMode(str(schedule.thinking_mode or RunSessionThinkingMode.FAST.value))
    except ValueError as exc:
        raise RunSessionRefusal(
            status_code=503,
            detail=_JOB_COMMAND_CONFIGURATION_UNAVAILABLE_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        ) from exc
    return candidates, thinking_mode, job_name, procedure_id
