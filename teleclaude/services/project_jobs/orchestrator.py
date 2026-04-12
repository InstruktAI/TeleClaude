"""Generic project-job orchestrator.

Walks the :class:`ProjectCatalogService`, filters projects by their
``config.jobs`` subscription, and dispatches a per-project executor for each
subscriber. Execution errors are isolated per project so one failing project
cannot stop the rest.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.services.project_catalog import ProjectCatalogService, ProjectNode

logger = get_logger(__name__)

ProjectJobRunner = Callable[[ProjectNode], Awaitable[bool]]


class ProjectJobOrchestrator:  # pylint: disable=too-few-public-methods
    """Iterate catalog projects subscribed to ``job_slug`` and run them.

    The orchestrator is intentionally generic — it knows nothing about what a
    specific job does. Callers inject a ``run_for_project`` coroutine that
    owns the per-project executor. The orchestrator's job is iteration,
    subscription filtering, and failure isolation.
    """

    def __init__(
        self,
        *,
        catalog: ProjectCatalogService,
        job_slug: str,
        run_for_project: ProjectJobRunner,
    ) -> None:
        self._catalog = catalog
        self._job_slug = job_slug
        self._run_for_project = run_for_project

    async def run_once(self) -> list[tuple[str, bool]]:
        """Run ``run_for_project`` for each subscribed project.

        Returns a list of ``(project_slug, dispatched)`` tuples. A project
        whose runner raises is recorded as ``(slug, False)`` so one broken
        project cannot hide subsequent successes.
        """
        results: list[tuple[str, bool]] = []
        for node in self._catalog.iter_projects_with_job(self._job_slug):
            try:
                dispatched = await self._run_for_project(node)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(
                    "project-job runner failed",
                    job_slug=self._job_slug,
                    project_slug=node.slug,
                    error=str(exc),
                )
                results.append((node.slug, False))
                continue
            results.append((node.slug, dispatched))
        return results
