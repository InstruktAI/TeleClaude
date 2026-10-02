"""Scheduled job list and trigger endpoints."""

from __future__ import annotations

import subprocess
import sys

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from instrukt_ai_logging import get_logger

from teleclaude.api_models import JobDTO
from teleclaude.config.jobs import load_effective_jobs
from teleclaude.config.schema import JobScheduleConfig
from teleclaude.cron import state as cron_state_module
from teleclaude.paths import REPO_ROOT
from teleclaude.services.project_catalog import get_project_catalog_service

logger = get_logger(__name__)

_CRON_RUNNER_JOB_FLAG = "--job"
_CRON_RUNNER_FORCE_FLAG = "--force"
_CRON_RUNNER_STARTUP_PROBE_SECONDS = 1
_CRON_RUNNER_START_FAILURE_DETAIL = "Failed to start job runner."
_CRON_RUNNER_START_FAILURE_LOG = "Failed to start cron runner process"

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
            for project in catalog.list_projects():
                for job in load_effective_jobs(project.root):
                    state_name = f"{project.slug}:{job.identity}"
                    job_state = state.get_job(state_name)
                    schedule_str = _describe_schedule(job.declaration)
                    last_run_ts = job_state.last_run.strftime("%Y-%m-%d %H:%M:%S") if job_state.last_run else None
                    results.append(
                        JobDTO(
                            name=job.identity,
                            project=project.slug,
                            type="agent" if job.declaration.job else "script",
                            schedule=schedule_str,
                            last_run=last_run_ts,
                            status=job_state.last_status or "never",
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


class _CronRunnerStartupError(Exception):
    def __init__(self, exit_status: int) -> None:
        super().__init__()
        self.exit_status = exit_status


def _spawn_cron_runner(name: str, project: str | None) -> None:
    """Start a detached runner and check its outcome during a bounded startup probe.

    A clean quick exit or a runner still active when the probe expires is accepted;
    a nonzero exit during the probe is a start failure.
    """
    script = REPO_ROOT / "scripts" / "cron_runner.py"
    job_filter = f"{project}:{name}" if project else name
    # The runner process boundary contains hung in-process jobs; no daemon-native helper can reap that thread.
    process = subprocess.Popen(
        [sys.executable, str(script), _CRON_RUNNER_JOB_FLAG, job_filter, _CRON_RUNNER_FORCE_FLAG],
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
    except (_CronRunnerStartupError, OSError) as exc:
        if isinstance(exc, _CronRunnerStartupError):
            if project is None:
                logger.error(_CRON_RUNNER_START_FAILURE_LOG, job=name, exit_status=exc.exit_status)
            else:
                logger.error(
                    _CRON_RUNNER_START_FAILURE_LOG,
                    job=name,
                    project=project,
                    exit_status=exc.exit_status,
                )
        else:
            if project is None:
                logger.error(_CRON_RUNNER_START_FAILURE_LOG, job=name, errno=exc.errno)
            else:
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
