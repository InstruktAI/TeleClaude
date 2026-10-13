"""Configuration-derived launch facts for canonical scheduled agent jobs."""

from __future__ import annotations

from pathlib import Path

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api_models import RunSessionRequest
from teleclaude.config.jobs import EffectiveJob, load_effective_jobs
from teleclaude.config.schema import is_agent_job
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.agent_dispatch import AgentDispatchReason, RunSessionThinkingMode

_JOB_ENTRY_FORBIDDEN_DETAIL = "only the platform starts a scheduled job entry"
_JOB_ARGUMENTS_FORBIDDEN_DETAIL = "a scheduled job entry takes no arguments"
_JOB_PROCEDURE_MISMATCH_DETAIL = "the request names a procedure other than the one the configured job points at"
_PROCEDURE_ID_PREFIX = "/"
_JOB_COMMAND_CONFIGURATION_UNAVAILABLE_DETAIL = "configured job declaration is unavailable"
_JOB_COMMAND_NOT_CONFIGURED_DETAIL = "no configured job declares this name"
_JOB_COMMAND_NOT_AGENT_DETAIL = "configured job name does not identify an agent job"
_JOB_COMMAND_OVERRIDE_FORBIDDEN_DETAIL = "a job run does not accept caller agent or thinking-mode overrides"
_JOB_COMMAND_AGENT_UNAVAILABLE_DETAIL = "configured agent job has no candidates"


def _declared_jobs(project: str, job_name: str) -> list[EffectiveJob]:
    return [job for job in load_effective_jobs(Path(project)) if job.identity == job_name]


def normalize_job_run_request(
    request: RunSessionRequest, identity: CallerIdentity
) -> tuple[tuple[str, ...], RunSessionThinkingMode, str, str]:
    """Derive the declared candidate order, thinking mode, job name and procedure of one scheduled job entry.

    Only the daemon's own credential starts a job entry, the job's declaration is the only source of
    its candidates and mode, and the request names the procedure that declaration points at.
    """
    if identity.principal != SYSTEM_DAEMON_PRINCIPAL or identity.role is not None:
        raise RunSessionRefusal(
            status_code=403,
            detail=_JOB_ENTRY_FORBIDDEN_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    if request.args.strip():
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_ARGUMENTS_FORBIDDEN_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    if "agent" in request.model_fields_set or "thinking_mode" in request.model_fields_set:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_COMMAND_OVERRIDE_FORBIDDEN_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    job_name = (request.job or "").strip()
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
    if request.command.strip().removeprefix(_PROCEDURE_ID_PREFIX) != procedure_id:
        raise RunSessionRefusal(
            status_code=400,
            detail=_JOB_PROCEDURE_MISMATCH_DETAIL,
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
