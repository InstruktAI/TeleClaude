"""Shared read model for configured jobs and their run state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from teleclaude.config.job_scope import JobScope
from teleclaude.config.jobs import load_visible_jobs
from teleclaude.config.schema import JobScheduleConfig, JobType
from teleclaude.cron.runner import project_next_due
from teleclaude.cron.state import CronState, JobRunStatus, JobState, compose_job_key
from teleclaude.services.project_catalog import ProjectCatalogService


@dataclass(frozen=True)
class JobListingRow:
    """One project-visible job projected with its existing run state."""

    project: str
    name: str
    type: JobType
    declaration: JobScheduleConfig
    scope: JobScope
    last_run: datetime | None
    status: JobRunStatus
    next_due: datetime | None


def compose_job_listing(
    catalog: ProjectCatalogService,
    state: CronState,
) -> tuple[JobListingRow, ...]:
    """Compose all registered projects' visible jobs without mutating run state."""
    now = datetime.now(UTC)
    rows: list[JobListingRow] = []
    for project in catalog.list_projects():
        for visible in load_visible_jobs(project.root):
            job_type = JobType.AGENT if visible.declaration.job else JobType.SCRIPT
            if visible.scope is JobScope.AVAILABLE:
                rows.append(
                    JobListingRow(
                        project=project.slug,
                        name=visible.name,
                        type=job_type,
                        declaration=visible.declaration,
                        scope=visible.scope,
                        last_run=None,
                        status=JobRunStatus.NEVER,
                        next_due=None,
                    )
                )
                continue

            job_state = state.jobs.get(compose_job_key(project.slug, visible.name))
            current_state = job_state if job_state is not None else JobState()
            rows.append(
                JobListingRow(
                    project=project.slug,
                    name=visible.name,
                    type=job_type,
                    declaration=visible.declaration,
                    scope=visible.scope,
                    last_run=current_state.last_run,
                    status=current_state.last_status,
                    next_due=project_next_due(visible.declaration, current_state, now, root=project.root),
                )
            )
    return tuple(rows)
