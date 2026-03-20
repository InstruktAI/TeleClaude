"""Characterization tests for job routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from teleclaude.api import jobs_routes


async def _run_sync_immediately(func: Callable[[], object]) -> object:
    return func()


class TestJobsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_jobs_merges_script_and_agent_jobs(self) -> None:
        """Job listing merges discovered script jobs with agent schedules missing from discovery."""
        discovered_jobs = [SimpleNamespace(name="backup")]
        backup_state = SimpleNamespace(last_run=datetime(2025, 3, 15, 12, 0, 0), last_status="success")
        agent_state = SimpleNamespace(last_run=None, last_status=None)
        schedules = {
            "backup": SimpleNamespace(type="script", schedule="0 * * * *"),
            "nightly-review": SimpleNamespace(type="agent", schedule="30 1 * * *"),
        }
        state = SimpleNamespace(get_job=MagicMock(side_effect=[backup_state, agent_state]))

        with (
            patch("teleclaude.api.jobs_routes.run_in_threadpool", new=_run_sync_immediately),
            patch("teleclaude.cron.runner.discover_jobs", return_value=discovered_jobs),
            patch("teleclaude.cron.runner.load_job_schedules", return_value=schedules),
            patch("teleclaude.cron.state.CronState.load", return_value=state),
        ):
            response = await jobs_routes.list_jobs()

        assert [job.model_dump() for job in response] == [
            {
                "name": "backup",
                "type": "script",
                "schedule": "0 * * * *",
                "last_run": "2025-03-15 12:00:00",
                "status": "success",
            },
            {
                "name": "nightly-review",
                "type": "agent",
                "schedule": "30 1 * * *",
                "last_run": None,
                "status": "never",
            },
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_job_schedules_background_execution(self) -> None:
        """Run requests enqueue the background runner instead of awaiting the job inline."""
        background_tasks = BackgroundTasks()

        response = await jobs_routes.run_job("nightly-review", background_tasks=background_tasks)

        assert response == {"status": "accepted", "job": "nightly-review", "completion_event": "job.completed"}
        assert len(background_tasks.tasks) == 1
        assert background_tasks.tasks[0].func is jobs_routes.run_in_threadpool

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_job_background_task_emits_started_and_completed_events(self) -> None:
        """The job background closure emits job.started then job.completed on success.

        A regression that removes either emit call would pass the HTTP-shape test above
        but fail here — this is the exact failure mode that caused C-4 in review round 1.
        """
        from teleclaude.core.event_bus import event_bus
        from teleclaude.core.events import JobCompletedPayload, JobStartedPayload

        background_tasks = BackgroundTasks()
        emitted: list[tuple[str, object]] = []

        def capture_emit(event: str, context: object) -> None:
            emitted.append((event, context))

        with (
            patch.object(event_bus, "emit", side_effect=capture_emit),
            patch("teleclaude.api.jobs_routes.cron_runner_module.run_due_jobs"),
        ):
            await jobs_routes.run_job("test-job", background_tasks=background_tasks)
            # Extract and run the _run_sync closure directly (bypasses threadpool)
            run_sync = cast(Callable[[], None], background_tasks.tasks[0].args[0])
            run_sync()

        started = [(e, p) for e, p in emitted if e == "job.started"]
        completed = [(e, p) for e, p in emitted if e == "job.completed"]

        assert len(started) == 1, f"Expected job.started, got events: {[e[0] for e in emitted]}"
        assert isinstance(started[0][1], JobStartedPayload)
        assert started[0][1].job_name == "test-job"

        assert len(completed) == 1, f"Expected job.completed, got events: {[e[0] for e in emitted]}"
        assert isinstance(completed[0][1], JobCompletedPayload)
        assert completed[0][1].job_name == "test-job"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_job_background_task_emits_failed_event_on_error(self) -> None:
        """The job background closure emits job.started then job.failed when the runner raises."""
        from teleclaude.core.event_bus import event_bus
        from teleclaude.core.events import JobFailedPayload, JobStartedPayload

        background_tasks = BackgroundTasks()
        emitted: list[tuple[str, object]] = []

        def capture_emit(event: str, context: object) -> None:
            emitted.append((event, context))

        with (
            patch.object(event_bus, "emit", side_effect=capture_emit),
            patch(
                "teleclaude.api.jobs_routes.cron_runner_module.run_due_jobs",
                side_effect=RuntimeError("disk full"),
            ),
        ):
            await jobs_routes.run_job("failing-job", background_tasks=background_tasks)
            run_sync = cast(Callable[[], None], background_tasks.tasks[0].args[0])
            run_sync()

        started = [(e, p) for e, p in emitted if e == "job.started"]
        failed = [(e, p) for e, p in emitted if e == "job.failed"]

        assert len(started) == 1
        assert isinstance(started[0][1], JobStartedPayload)

        assert len(failed) == 1, f"Expected job.failed, got events: {[e[0] for e in emitted]}"
        assert isinstance(failed[0][1], JobFailedPayload)
        assert failed[0][1].job_name == "failing-job"
