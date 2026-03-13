"""Scheduled job list and trigger endpoints."""

from __future__ import annotations

import fastapi
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from instrukt_ai_logging import get_logger

from teleclaude.api_models import JobDTO

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs() -> list[JobDTO]:
    """List scheduled jobs."""
    from teleclaude.cron.runner import _load_job_schedules, discover_jobs
    from teleclaude.cron.state import CronState

    def _get_jobs_sync() -> list[JobDTO]:
        try:
            python_jobs = discover_jobs()
            state = CronState.load()
            schedules = _load_job_schedules()

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
        except Exception as e:
            logger.error("list_jobs inner failed: %s", e, exc_info=True)
            raise

    try:
        return await run_in_threadpool(_get_jobs_sync)
    except Exception as e:
        logger.error("list_jobs failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {e}") from e


@router.post("/{name}/run")
async def run_job(
    name: str,
    background_tasks: fastapi.BackgroundTasks,
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Run a scheduled job immediately (fire-and-forget)."""
    from teleclaude.cron.runner import run_due_jobs

    def _run_sync() -> None:
        try:
            logger.info("Background job triggered: %s", name)
            run_due_jobs(force=True, job_filter=name)
        except Exception as e:
            logger.error("Background job failed (job=%s): %s", name, e, exc_info=True)

    background_tasks.add_task(run_in_threadpool, _run_sync)
    return {"status": "accepted", "job": name}
