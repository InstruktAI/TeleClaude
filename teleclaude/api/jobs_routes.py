"""Scheduled job list and trigger endpoints."""

from __future__ import annotations

import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from instrukt_ai_logging import get_logger

from teleclaude.api_models import JobDTO
from teleclaude.cron import runner as cron_runner_module
from teleclaude.cron import state as cron_state_module
from teleclaude.paths import REPO_ROOT

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs() -> list[JobDTO]:
    """List scheduled jobs."""

    def _get_jobs_sync() -> list[JobDTO]:
        try:
            python_jobs = cron_runner_module.discover_jobs()
            state = cron_state_module.CronState.load()
            schedules = cron_runner_module.load_job_schedules()

            results: list[JobDTO] = []
            python_job_names = {job.name for job in python_jobs}
            agent_job_names = [
                name for name, cfg in schedules.items() if cfg.type == "agent" and name not in python_job_names
            ]

            # Process Python (script) jobs
            for job in python_jobs:
                job_state = state.get_job(job.name)
                sched = schedules.get(job.name)
                schedule_str = sched.schedule if sched and sched.schedule else None
                last_run_ts = job_state.last_run.strftime("%Y-%m-%d %H:%M:%S") if job_state.last_run else None
                results.append(
                    JobDTO(
                        name=job.name,
                        type="script",
                        schedule=schedule_str,
                        last_run=last_run_ts,
                        status=job_state.last_status or "never",
                    )
                )

            # Process Agent jobs
            for name in agent_job_names:
                job_state = state.get_job(name)
                sched = schedules[name]
                schedule_str = sched.schedule if sched.schedule else None
                last_run_ts = job_state.last_run.strftime("%Y-%m-%d %H:%M:%S") if job_state.last_run else None
                results.append(
                    JobDTO(
                        name=name,
                        type="agent",
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


def _spawn_cron_runner(name: str) -> None:
    script = REPO_ROOT / "scripts" / "cron_runner.py"
    # The runner process boundary contains hung in-process jobs; no daemon-native helper can reap that thread.
    subprocess.Popen(
        [str(script), "--job", name, "--force"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


@router.post("/{name}/run", status_code=202)
async def run_job(name: str) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Run a scheduled job immediately (fire-and-forget)."""
    try:
        _spawn_cron_runner(name)
    except OSError as exc:
        logger.error("Failed to start cron runner process (job=%s): %s", name, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to start job runner: {exc}") from exc
    return {"status": "accepted", "job": name}
