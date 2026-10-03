"""Scheduled job list and trigger endpoints."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Final

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from instrukt_ai_logging import get_logger

from teleclaude.api_models import JobDTO
from teleclaude.config.schema import JobScheduleConfig
from teleclaude.cron import state as cron_state_module
from teleclaude.cron.listing import compose_job_listing
from teleclaude.paths import REPO_ROOT
from teleclaude.services.project_catalog import get_project_catalog_service

logger = get_logger(__name__)

_CRON_RUNNER_JOB_FLAG = "--job"
_CRON_RUNNER_FORCE_FLAG = "--force"
_CRON_RUNNER_API_DISPATCH_FLAG = "--api-dispatch"
_CRON_RUNNER_STARTUP_PROBE_SECONDS = 1
_CRON_RUNNER_START_FAILURE_DETAIL = "Failed to start job runner."
_CRON_RUNNER_START_FAILURE_LOG = "Failed to start cron runner process"
_UTC_OFFSET_SUFFIX: Final[str] = "+00:00"
_UTC_MARKER: Final[str] = "Z"

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs() -> list[JobDTO]:
    """List scheduled jobs."""

    def _get_jobs_sync() -> list[JobDTO]:
        try:
            state = cron_state_module.CronState.load()
            results: list[JobDTO] = []
            catalog = get_project_catalog_service()
            catalog.refresh()
            for row in compose_job_listing(catalog, state):
                results.append(
                    JobDTO(
                        name=row.name,
                        project=row.project,
                        type=row.type,
                        schedule=_describe_schedule(row.declaration),
                        last_run=_format_job_timestamp(row.last_run),
                        status=row.status,
                        scope=row.scope,
                        next_due=_format_job_timestamp(row.next_due),
                    )
                )

            results.sort(key=lambda x: x.name)
            return results
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("list_jobs inner failed: %s", exc, exc_info=True)
            raise

    try:
        return await run_in_threadpool(_get_jobs_sync)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("list_jobs failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {exc}") from exc


def _format_job_timestamp(value: datetime | None) -> str | None:
    """Render job instants in UTC so last and projected next times compare directly."""
    if value is None:
        return None
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.isoformat(timespec="seconds").replace(_UTC_OFFSET_SUFFIX, _UTC_MARKER)


class _CronRunnerStartupError(Exception):
    def __init__(self, exit_status: int) -> None:
        super().__init__()
        self.exit_status = exit_status


def _spawn_cron_runner(name: str, project: str | None) -> None:
    """Start a detached runner and check its outcome during a bounded startup probe.

    An API-launched runner returns zero after recording a job outcome. Any
    nonzero early exit therefore means no outcome was recorded by that path.
    """
    script = REPO_ROOT / "scripts" / "cron_runner.py"
    job_filter = f"{project}:{name}" if project else name
    # The runner process boundary contains hung in-process jobs; no daemon-native helper can reap that thread.
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            _CRON_RUNNER_JOB_FLAG,
            job_filter,
            _CRON_RUNNER_FORCE_FLAG,
            _CRON_RUNNER_API_DISPATCH_FLAG,
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=None,
        start_new_session=True,
    )
    try:
        exit_status = process.wait(timeout=_CRON_RUNNER_STARTUP_PROBE_SECONDS)
    except subprocess.TimeoutExpired:
        return
    if exit_status != 0:
        raise _CronRunnerStartupError(exit_status)


@router.post("/{name:path}/run", status_code=202)
async def run_job(name: str, project: str | None = None) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Start a scheduled job and report failures observed during startup."""
    try:
        await run_in_threadpool(_spawn_cron_runner, name, project)
    except _CronRunnerStartupError as exc:
        logger.error(_CRON_RUNNER_START_FAILURE_LOG, job=name, project=project, exit_status=exc.exit_status)
        raise HTTPException(status_code=502, detail=_CRON_RUNNER_START_FAILURE_DETAIL) from exc
    except OSError as exc:
        logger.error(_CRON_RUNNER_START_FAILURE_LOG, job=name, project=project, errno=exc.errno)
        raise HTTPException(status_code=502, detail=_CRON_RUNNER_START_FAILURE_DETAIL) from exc
    return {"status": "accepted", "job": name, "project": project}


def _describe_schedule(declaration: JobScheduleConfig) -> str | None:
    when = declaration.when
    if when is None:
        return None
    if when.every:
        return when.every
    if isinstance(when.at, list):
        return ", ".join(when.at)
    return when.at
