"""Scheduled job list and trigger endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api_models import JobDTO
from teleclaude.api_models_operations import OperationStatusDTO
from teleclaude.config.schema import JobScheduleConfig
from teleclaude.core.operations._receipt import SerializedOperation
from teleclaude.core.operations.service import get_operations_service
from teleclaude.cron import state as cron_state_module
from teleclaude.cron.listing import compose_job_listing
from teleclaude.services.project_catalog import get_project_catalog_service

logger = get_logger(__name__)

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


@router.post("/{name:path}/run", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def run_job(
    name: str,
    project: str | None = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Ask for one run of a job and answer with the operation receipt that ends with the run's outcome."""
    return await get_operations_service().submit_job_run(
        name=name,
        project=project,
        caller_session_id=identity.session_id or None,
        client_request_id=None,
    )


def _describe_schedule(declaration: JobScheduleConfig) -> str | None:
    when = declaration.when
    if when is None:
        return None
    if when.every:
        return when.every
    if isinstance(when.at, list):
        return ", ".join(when.at)
    return when.at
