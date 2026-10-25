"""The job_run operation: one manual run of one job, ended with the run's outcome.

The operation launches the standalone cron runner for the job, reads from it which run it opened, and
waits for that run to close through its normal outcome path. The runner stays the only writer of run state;
the operation only reads it. A runner that opens no run, or cannot be launched, fails the operation naming
why, and the run itself outlives a daemon restart that makes the operation stale.
"""

from __future__ import annotations

import asyncio
import json
import sys
from asyncio.subprocess import PIPE
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.db_models import Operation
from teleclaude.core.operations._outcome import OperationCompletion
from teleclaude.core.todos_db._exceptions import OperationErrorPayload, OperationFailure
from teleclaude.cron.dispatch_record import DispatchRefusal, JobDispatchRecord, parse_dispatch_line
from teleclaude.cron.state import JobRunStatus, RunLookup, read_run_state
from teleclaude.paths import REPO_ROOT, TELECLAUDE_HOME
from teleclaude.services.project_catalog import get_project_catalog_service

logger = get_logger(__name__)

RUN_POLL_INTERVAL_SECONDS: Final = 2.0
DISPATCH_RECORD_TIMEOUT_SECONDS: Final = 120.0
_RUNNER_JOB_FLAG: Final = "--job"
_RUNNER_FORCE_FLAG: Final = "--force"
_RUNNER_API_DISPATCH_FLAG: Final = "--api-dispatch"
_JOB_KEY_SEPARATOR: Final = ":"
_PAYLOAD_NAME_FIELD: Final = "name"
_PAYLOAD_PROJECT_FIELD: Final = "project"
_PAYLOAD_KIND_FIELD: Final = "kind"
_RUN_COMPLETED: Final = "{job} completed"
_RUN_FAILED: Final = "{job} {status}: {error}"
_RUN_FAILED_WITHOUT_ERROR: Final = "{job} {status}"
_RUN_RECORD_GONE: Final = "the run of {job} is no longer in the runner's state"
_REFUSAL_DETAIL: Final[dict[DispatchRefusal, str]] = {
    DispatchRefusal.RUNNER_LOCK_HELD: "another runner pass holds the runner lock",
    DispatchRefusal.RUN_ALREADY_OPEN: "{job} already has an open run",
    DispatchRefusal.UNDELIVERED_OUTCOME: "{job} has an actionable outcome that is not yet delivered",
    DispatchRefusal.NO_SUCH_JOB: "the project declares no job {job}",
    DispatchRefusal.START_FAILED: "{job} could not start",
}
_LAUNCH_FAILED: Final = "the cron runner could not be launched: {error}"
_RUNNER_EXITED: Final = "the cron runner exited with status {status} without opening a run"
_RUNNER_SILENT: Final = "the cron runner did not report a run within {seconds:.0f}s"
_DETAIL_SUFFIX: Final = ": {detail}"
_NO_DETAIL: Final = ""
_FAILURE_KIND: Final = "job_run_failed"
_RUNNER_SCRIPT: Final = REPO_ROOT / "scripts" / "cron_runner.py"
_STDOUT_DECODE_ERRORS: Final = "replace"
_LAUNCH_FAILED_LOG: Final = "job run: cron runner could not be launched"


class JobRunFailure(OperationFailure):
    """A manual job run that opened no run, or whose run did not succeed."""

    error_kind = _FAILURE_KIND

    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.work_feedback = reason
        super().__init__(reason)

    def to_error_payload(self) -> OperationErrorPayload:
        return OperationErrorPayload(kind=self.error_kind)

    def summary(self) -> str:
        return self.reason


@dataclass(frozen=True)
class JobRunRequest:
    """The one job and project a manual run asks for."""

    name: str
    project: str | None

    @property
    def runner_filter(self) -> str:
        """The runner's job filter: project-qualified when a project is named."""
        return f"{self.project}{_JOB_KEY_SEPARATOR}{self.name}" if self.project else self.name


def job_project_path(request: JobRunRequest) -> str | None:
    """The root of the project a run is for, so the receipt records that project's subject and owner.

    The named project, else the platform's own project found through the registry; None when it is not registered,
    as the runner then opens no run.
    """
    catalog = get_project_catalog_service()
    node = catalog.get_by_slug(request.project) if request.project else catalog.get_platform_project()
    return str(node.root) if node is not None else None


def job_run_payload(kind: str, request: JobRunRequest) -> str:
    """The stored payload of a manual run operation."""
    return json.dumps(
        {_PAYLOAD_KIND_FIELD: kind, _PAYLOAD_NAME_FIELD: request.name, _PAYLOAD_PROJECT_FIELD: request.project},
        sort_keys=True,
    )


def _request_of(operation: Operation) -> JobRunRequest:
    payload = json.loads(operation.payload_json)
    project = payload.get(_PAYLOAD_PROJECT_FIELD)
    return JobRunRequest(name=str(payload[_PAYLOAD_NAME_FIELD]), project=project if isinstance(project, str) else None)


async def _read_dispatch_record(process: asyncio.subprocess.Process) -> JobDispatchRecord | None:
    """The record the runner writes about its dispatch, or None when its output ends without one."""
    assert process.stdout is not None
    while True:
        line = await process.stdout.readline()
        if not line:
            return None
        record = parse_dispatch_line(line.decode(errors=_STDOUT_DECODE_ERRORS))
        if record is not None:
            return record


def _refusal_reason(record: JobDispatchRecord, request: JobRunRequest) -> str:
    refusal = record.refusal or DispatchRefusal.START_FAILED
    reason = _REFUSAL_DETAIL[refusal].format(job=record.job_key or request.runner_filter)
    return reason + (_DETAIL_SUFFIX.format(detail=record.detail) if record.detail else _NO_DETAIL)


async def _launch_runner(request: JobRunRequest) -> asyncio.subprocess.Process:
    # The runner process boundary contains hung in-process jobs; no daemon-native helper can reap that thread.
    try:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            str(_RUNNER_SCRIPT),
            _RUNNER_JOB_FLAG,
            request.runner_filter,
            _RUNNER_FORCE_FLAG,
            _RUNNER_API_DISPATCH_FLAG,
            cwd=str(TELECLAUDE_HOME),
            stdout=PIPE,
            stderr=None,
            start_new_session=True,
        )
    except OSError as error:
        logger.error(_LAUNCH_FAILED_LOG, errno=error.errno)
        raise JobRunFailure(_LAUNCH_FAILED.format(error=error.strerror or error.errno)) from error


async def _opened_run(request: JobRunRequest) -> JobDispatchRecord:
    """Launch the runner and learn which run it opened; a runner that opened none fails the operation."""
    process = await _launch_runner(request)
    try:
        record = await asyncio.wait_for(_read_dispatch_record(process), timeout=DISPATCH_RECORD_TIMEOUT_SECONDS)
    except TimeoutError as error:
        raise JobRunFailure(_RUNNER_SILENT.format(seconds=DISPATCH_RECORD_TIMEOUT_SECONDS)) from error
    if record is None:
        raise JobRunFailure(_RUNNER_EXITED.format(status=await process.wait()))
    if not record.opened:
        raise JobRunFailure(_refusal_reason(record, request))
    return record


async def _await_closure(job_key: str, run_started_at: datetime) -> OperationCompletion:
    """Wait for the run to close, then end the operation with its outcome."""
    while True:
        state = await asyncio.to_thread(read_run_state, job_key, run_started_at)
        if state.lookup is RunLookup.OPEN:
            await asyncio.sleep(RUN_POLL_INTERVAL_SECONDS)
            continue
        if state.lookup is RunLookup.UNKNOWN:
            raise JobRunFailure(_RUN_RECORD_GONE.format(job=job_key))
        if state.status is JobRunStatus.SUCCESS:
            return OperationCompletion(_RUN_COMPLETED.format(job=job_key))
        status = state.status.value if state.status is not None else JobRunStatus.FAILED.value
        if state.error:
            raise JobRunFailure(_RUN_FAILED.format(job=job_key, status=status, error=state.error))
        raise JobRunFailure(_RUN_FAILED_WITHOUT_ERROR.format(job=job_key, status=status))


async def run_job_run_operation(operation: Operation) -> OperationCompletion:
    """Run one manual job run to its outcome."""
    request = _request_of(operation)
    record = await _opened_run(request)
    assert record.job_key is not None and record.run_started_at is not None
    return await _await_closure(record.job_key, datetime.fromisoformat(record.run_started_at))
