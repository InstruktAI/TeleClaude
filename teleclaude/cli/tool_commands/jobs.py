"""Job subcommand handlers for telec jobs <subcommand>."""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Final, NoReturn, cast

from jobs.base import JobResult, JSONState
from teleclaude.api_models import JobDTO
from teleclaude.cli.session_auth import resolve_cli_identity
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import (
    JOBS_DISABLE,
    JOBS_ENABLE,
    JOBS_LIST,
    JOBS_REPORT,
    JOBS_RUN,
    JOBS_STATUS,
    CommandDef,
)
from teleclaude.cli.telec.surface_types import JobsSubcommand
from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.config.jobs import (
    SubscriptionChange,
    load_effective_jobs,
    plan_job_subscription,
)
from teleclaude.config.loader import load_global_config
from teleclaude.config.resource_contract import (
    InvalidCandidate,
    PartialCommitFailure,
    ReadOnlyProjection,
    SubjectNotFound,
    SubjectView,
)
from teleclaude.config.resources import affected_sections, patch_subject, read_subject
from teleclaude.config.revision import StaleRevision
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.configuration_clearance import (
    ConfigurationOperation,
    ConfigurationTarget,
    decide,
    standing_for,
)
from teleclaude.cron.result_store import job_result_transaction, write_job_result_in_transaction
from teleclaude.cron.state import CronState, JobRunStatus, compose_job_key
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.session_identity import get_session_id

_JOB_NAME_REQUIRED_ERROR: Final[str] = "Error: job name required"
_UNEXPECTED_ARGUMENT_ERROR: Final[str] = "Error: unexpected argument: {argument}"
_JOBS_API_PATH: Final[str] = "/jobs"
_JOB_RUN_PATH: Final[str] = "/jobs/{name}/run"
_JOBS_RESPONSE_ERROR: Final[str] = "The jobs API returned an invalid response"
_LAST_RUN_NEVER: Final[str] = "never"
_NEXT_DUE_NONE: Final[str] = "-"
_JOB_LIST_LINE: Final[str] = "{scope} {name}"
_JOB_STATUS_LINE: Final[str] = "{name}: last_run={last_run}; status={status}; next_due={next_due}"
_PROJECT_SECTION: Final[str] = "project"
_JOBS_SECTION: Final[str] = "jobs"
_INVALID_PROJECT_SECTION_ERROR: Final[str] = "Project subject has no writable project section"
_INVALID_JOBS_ARRAY_ERROR: Final[str] = "Project subject has an invalid jobs array"
_REFUSED_MESSAGE: Final[str] = "Error: refused — required standing: {standing} ({reason}) (request {request_id})"
_NOT_FOUND_MESSAGE: Final[str] = "Error: {message} (request {request_id})"
_STALE_MESSAGE: Final[str] = (
    "Error: stale revision — expected {expected}, subject is now at {actual} (request {request_id})"
)
_INVALID_MESSAGE: Final[str] = "Error: {message} (request {request_id})"
_PARTIAL_COMMIT_MESSAGE: Final[str] = (
    "Error: {message} (request {request_id})\n"
    "The affected files may be in a mixed state — read them back before retrying."
)
_SUBSCRIPTION_MESSAGES: Final[dict[SubscriptionChange, str]] = {
    SubscriptionChange.SUBSCRIBED: "Subscribed to job {name}",
    SubscriptionChange.ACTIVATED: "Enabled job {name}",
    SubscriptionChange.DEACTIVATED: "Disabled job {name}",
    SubscriptionChange.UNCHANGED: "Job {name} subscription is unchanged",
    SubscriptionChange.NOT_SUBSCRIBED: "Project does not subscribe to job {name}",
}
_STATE_JSON_INVALID_ERROR: Final[str] = "Error: --state-json must contain valid JSON"
_STATE_JSON_OBJECT_ERROR: Final[str] = "Error: --state-json must contain a JSON object"
_REPORT_RUN_ERROR: Final[str] = "Error: no open run belongs to this reporting session"


def handle_jobs(args: list[str]) -> None:
    """Handle telec jobs <subcommand> [args]."""
    subcommand = args[0]
    rest = args[1:]
    if subcommand == JobsSubcommand.REPORT.value:
        handle_jobs_report(rest)
        return
    if subcommand == JobsSubcommand.LIST.value:
        handle_jobs_list(rest)
        return
    if subcommand == JobsSubcommand.STATUS.value:
        handle_jobs_status(rest)
        return
    if subcommand == JobsSubcommand.ENABLE.value:
        handle_jobs_enable(rest)
        return
    if subcommand == JobsSubcommand.DISABLE.value:
        handle_jobs_disable(rest)
        return
    if subcommand == JobsSubcommand.RUN.value:
        handle_jobs_run(rest)
        return

    print(f"Unknown jobs subcommand: {subcommand}", file=sys.stderr)
    print("Run 'telec jobs --help' for usage.", file=sys.stderr)
    raise SystemExit(1)


def handle_jobs_report(args: list[str]) -> None:
    """Write a structured JobResult record for a configured recurring job.

    Usage: telec jobs report <name> --success true|false --message <text>
                             [--items-processed <n>] [--error <text> ...]

    <name> is the job's declared identity for both agent and script jobs.
    """
    parsed = parse_command_args(JOBS_REPORT, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Error: unexpected argument: {positionals[1]}", file=sys.stderr)
        raise SystemExit(1)
    job_name = positionals[0] if positionals else None
    if not job_name:
        print(_JOB_NAME_REQUIRED_ERROR, file=sys.stderr)
        raise SystemExit(1)

    success_raw = parsed.value(F.FLAG_JOB_SUCCESS)
    message = parsed.value(F.FLAG_JOB_MESSAGE)
    items_processed_raw = parsed.value(F.FLAG_JOB_ITEMS_PROCESSED)
    errors = list(parsed.values(F.FLAG_JOB_ERROR))
    state_raw = parsed.value(F.FLAG_JOB_STATE_JSON)

    if success_raw is None:
        print("Error: --success is required", file=sys.stderr)
        raise SystemExit(1)
    success = _parse_bool(success_raw)
    if message is None:
        print("Error: --message is required", file=sys.stderr)
        raise SystemExit(1)
    items_processed = _parse_non_negative_int(items_processed_raw) if items_processed_raw is not None else 0
    state = _parse_state_json(state_raw) if state_raw is not None else None

    project_root = _invoking_project_root()
    project_slug = _invoking_project_slug(project_root)
    _validate_known_job(job_name, project_root)
    session_id = get_session_id()

    result = JobResult(
        success=success,
        message=message,
        items_processed=items_processed,
        errors=errors or None,
        session_id=session_id,
        state=state,
    )
    with job_result_transaction(project_slug, job_name) as transaction:
        _require_current_open_agent_run(project_slug, job_name, session_id)
        record_path = write_job_result_in_transaction(
            transaction,
            result,
            execution_session_id=session_id,
        )

    print(json.dumps({"status": "ok", "path": str(record_path)}, ensure_ascii=True))


def handle_jobs_list(args: list[str]) -> None:
    """List jobs visible to the invoking project."""
    _require_no_positionals(JOBS_LIST, args)
    project_root = _invoking_project_root()
    project_slug = _invoking_project_slug(project_root)
    for job in _load_project_jobs(project_slug):
        print(_JOB_LIST_LINE.format(scope=job.scope.value, name=job.name))


def handle_jobs_status(args: list[str]) -> None:
    """Show the last and projected next run for each visible job."""
    _require_no_positionals(JOBS_STATUS, args)
    project_root = _invoking_project_root()
    project_slug = _invoking_project_slug(project_root)
    for job in _load_project_jobs(project_slug):
        last_run = job.last_run if job.last_run is not None else _LAST_RUN_NEVER
        next_due = job.next_due if job.next_due is not None else _NEXT_DUE_NONE
        print(
            _JOB_STATUS_LINE.format(
                name=job.name,
                last_run=last_run,
                status=job.status.value,
                next_due=next_due,
            )
        )


def handle_jobs_enable(args: list[str]) -> None:
    """Subscribe the invoking project to one published job."""
    _handle_job_subscription(args, JOBS_ENABLE, enabled=True)


def handle_jobs_disable(args: list[str]) -> None:
    """Deactivate the invoking project's subscription to one published job."""
    _handle_job_subscription(args, JOBS_DISABLE, enabled=False)


def handle_jobs_run(args: list[str]) -> None:
    """Run one effective job through the existing project-scoped endpoint."""
    job_name = _required_job_name(JOBS_RUN, args)
    project_root = _invoking_project_root()
    project_slug = _invoking_project_slug(project_root)
    _validate_known_job(job_name, project_root)
    result = tool_api_call(
        "POST",
        _JOB_RUN_PATH.format(name=job_name),
        params={"project": project_slug},
    )
    print_json(result)


def _handle_job_subscription(args: list[str], command: CommandDef, *, enabled: bool) -> None:
    job_name = _required_job_name(command, args)
    project_root = _invoking_project_root()
    project_slug = _invoking_project_slug(project_root)
    request_id = str(uuid.uuid4())
    subject = SubjectRef(ConfigSubjectKind.PROJECT, project_slug)
    sections = affected_sections(subject, {_JOBS_SECTION: []})
    identity = resolve_cli_identity()
    decision = decide(
        standing_for(identity),
        ConfigurationTarget(
            kind=ConfigSubjectKind.PROJECT,
            instance=project_slug,
            operation=ConfigurationOperation.PATCH,
            sections=sections,
        ),
        request_id=request_id,
    )
    if not decision.allowed:
        _exit_command_error(
            _REFUSED_MESSAGE.format(
                standing=decision.required_standing.value,
                reason=decision.reason,
                request_id=request_id,
            )
        )

    try:
        view = read_subject(subject)
    except SubjectNotFound as error:
        _exit_command_error(_NOT_FOUND_MESSAGE.format(message=str(error), request_id=request_id))

    try:
        jobs = _jobs_array_from_view(view)
    except ValueError as error:
        _exit_command_error(_INVALID_MESSAGE.format(message=str(error), request_id=request_id))

    published = load_global_config().jobs
    try:
        plan = plan_job_subscription(jobs, published, job_name, enabled)
    except ValueError as error:
        _exit_command_error(_INVALID_MESSAGE.format(message=str(error), request_id=request_id))
    if plan.jobs is not None:
        try:
            patch_subject(
                subject,
                {_JOBS_SECTION: list(plan.jobs)},
                expected_revision=view.revision,
                request_id=request_id,
            )
        except (SubjectNotFound, StaleRevision, PartialCommitFailure, InvalidCandidate, ReadOnlyProjection) as error:
            _exit_resource_error(error, request_id)

    print(_SUBSCRIPTION_MESSAGES[plan.change].format(name=job_name))


def _required_job_name(command: CommandDef, args: list[str]) -> str:
    positionals = list(parse_command_args(command, args).positionals)
    if not positionals:
        print(_JOB_NAME_REQUIRED_ERROR, file=sys.stderr)
        raise SystemExit(1)
    if len(positionals) > 1:
        print(_UNEXPECTED_ARGUMENT_ERROR.format(argument=positionals[1]), file=sys.stderr)
        raise SystemExit(1)
    return positionals[0]


def _jobs_array_from_view(view: SubjectView) -> list[Mapping[str, object]]:
    section = view.sections.get(_PROJECT_SECTION)
    if not isinstance(section, Mapping):
        raise ValueError(_INVALID_PROJECT_SECTION_ERROR)
    jobs = section.get(_JOBS_SECTION, [])
    if not isinstance(jobs, list):
        raise ValueError(_INVALID_JOBS_ARRAY_ERROR)
    entries: list[Mapping[str, object]] = []
    for entry in jobs:
        if not isinstance(entry, Mapping) or any(not isinstance(key, str) for key in entry):
            raise ValueError(_INVALID_JOBS_ARRAY_ERROR)
        entries.append(cast(Mapping[str, object], entry))
    return entries


def _exit_resource_error(
    error: SubjectNotFound | StaleRevision | PartialCommitFailure | InvalidCandidate | ReadOnlyProjection,
    request_id: str,
) -> NoReturn:
    if isinstance(error, StaleRevision):
        message = _STALE_MESSAGE.format(expected=error.expected, actual=error.actual, request_id=request_id)
    elif isinstance(error, PartialCommitFailure):
        message = _PARTIAL_COMMIT_MESSAGE.format(message=str(error), request_id=request_id)
    elif isinstance(error, SubjectNotFound):
        message = _NOT_FOUND_MESSAGE.format(message=str(error), request_id=request_id)
    else:
        message = _INVALID_MESSAGE.format(message=str(error), request_id=request_id)
    _exit_command_error(message)


def _exit_command_error(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _require_no_positionals(command: CommandDef, args: list[str]) -> None:
    parsed = parse_command_args(command, args)
    if parsed.positionals:
        print(_UNEXPECTED_ARGUMENT_ERROR.format(argument=parsed.positionals[0]), file=sys.stderr)
        raise SystemExit(1)


def _load_project_jobs(project_slug: str) -> list[JobDTO]:
    response = tool_api_call("GET", _JOBS_API_PATH)
    if not isinstance(response, list) or any(not isinstance(row, Mapping) for row in response):
        raise ValueError(_JOBS_RESPONSE_ERROR)
    jobs = [JobDTO.model_validate(row) for row in response]
    return [job for job in jobs if job.project == project_slug]


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    print("Error: --success must be true or false", file=sys.stderr)
    raise SystemExit(1)


def _parse_non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        print("Error: --items-processed must be an integer", file=sys.stderr)
        raise SystemExit(1) from exc
    if value < 0:
        print("Error: --items-processed must be non-negative", file=sys.stderr)
        raise SystemExit(1)
    return value


def _validate_known_job(job_name: str, project_root: Path) -> None:
    if job_name not in _load_known_job_names(project_root):
        print(f"Error: unknown job: {job_name}", file=sys.stderr)
        raise SystemExit(1)


def _load_known_job_names(project_root: Path) -> set[str]:
    return {job.identity for job in load_effective_jobs(project_root)}


def _invoking_project_root() -> Path:
    return resolve_invocation_roots().require_project_root()


def _invoking_project_slug(project_root: Path) -> str:
    project = get_project_catalog_service().get_by_root(project_root)
    if project is None:
        raise ValueError(f"reporting project is not registered: {project_root}")
    return project.slug


def _parse_state_json(raw: str) -> JSONState:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(_STATE_JSON_INVALID_ERROR, file=sys.stderr)
        raise SystemExit(1) from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        print(_STATE_JSON_OBJECT_ERROR, file=sys.stderr)
        raise SystemExit(1)
    return cast(JSONState, value)


def _require_current_open_agent_run(project_slug: str, job_name: str, session_id: str | None) -> None:
    state = CronState.load(persist_migrations=False)
    job_state = state.jobs.get(compose_job_key(project_slug, job_name))
    if (
        session_id is None
        or job_state is None
        or job_state.last_status is not JobRunStatus.RUNNING
        or job_state.run_started_at is None
        or job_state.run_session_id != session_id
    ):
        print(_REPORT_RUN_ERROR, file=sys.stderr)
        raise SystemExit(1)
