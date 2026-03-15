"""Characterization tests for job routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import SimpleNamespace
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
            patch("teleclaude.cron.runner._load_job_schedules", return_value=schedules),
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

        assert response == {"status": "accepted", "job": "nightly-review"}
        assert len(background_tasks.tasks) == 1
        assert background_tasks.tasks[0].func is jobs_routes.run_in_threadpool
