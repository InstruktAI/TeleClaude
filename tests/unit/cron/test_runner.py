"""Unit tests for the cron runner execution model."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from jobs.base import JobResult
from teleclaude.cron import runner


def _local_timezone():
    tzinfo = datetime.now().astimezone().tzinfo
    assert tzinfo is not None
    return tzinfo


@pytest.mark.unit
def test_discover_jobs_reads_configured_script_jobs(tmp_path: Path) -> None:
    repo_root = tmp_path
    jobs_dir = repo_root / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "alpha.py").write_text("print('alpha')\n", encoding="utf-8")
    (repo_root / "teleclaude.yml").write_text(
        "\n".join(
            [
                "project_name: Demo",
                "jobs:",
                "  alpha:",
                "    category: system",
                "    when:",
                "      every: '60m'",
                "    script: jobs/alpha.py",
                "  beta:",
                "    category: system",
                "    type: agent",
                "    job: beta",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    jobs = runner.discover_jobs(jobs_dir=jobs_dir)

    assert jobs == [runner.ScriptJob(name="alpha", script="jobs/alpha.py")]


@pytest.mark.unit
def test_first_run_waits_for_interval_schedule() -> None:
    schedule = SimpleNamespace(
        when=SimpleNamespace(every="60m", at=None, weekdays=None),
        schedule=None,
        preferred_hour=6,
        preferred_weekday=0,
        preferred_day=1,
    )

    assert (
        runner._is_first_run_due(
            schedule,
            datetime(2026, 4, 4, 9, 0, tzinfo=UTC),
            datetime(2026, 4, 4, 9, 59, tzinfo=UTC),
        )
        is False
    )
    assert (
        runner._is_first_run_due(
            schedule,
            datetime(2026, 4, 4, 9, 0, tzinfo=UTC),
            datetime(2026, 4, 4, 10, 0, tzinfo=UTC),
        )
        is True
    )


@pytest.mark.unit
def test_first_run_waits_for_first_scheduled_time() -> None:
    local_tz = _local_timezone()
    schedule = SimpleNamespace(
        when=SimpleNamespace(every=None, at="06:00", weekdays=None),
        schedule=None,
        preferred_hour=6,
        preferred_weekday=0,
        preferred_day=1,
    )

    assert (
        runner._is_first_run_due(
            schedule,
            datetime(2026, 4, 4, 5, 30, tzinfo=local_tz),
            datetime(2026, 4, 4, 5, 59, tzinfo=local_tz),
        )
        is False
    )
    assert (
        runner._is_first_run_due(
            schedule,
            datetime(2026, 4, 4, 5, 30, tzinfo=local_tz),
            datetime(2026, 4, 4, 6, 0, tzinfo=local_tz),
        )
        is True
    )


@pytest.mark.unit
def test_first_run_waits_for_next_daily_preferred_hour() -> None:
    local_tz = _local_timezone()
    schedule = SimpleNamespace(
        when=None,
        schedule="daily",
        preferred_hour=6,
        preferred_weekday=0,
        preferred_day=1,
    )

    assert (
        runner._is_first_run_due(
            schedule,
            datetime(2026, 4, 4, 19, 0, tzinfo=local_tz),
            datetime(2026, 4, 5, 5, 59, tzinfo=local_tz),
        )
        is False
    )
    assert (
        runner._is_first_run_due(
            schedule,
            datetime(2026, 4, 4, 19, 0, tzinfo=local_tz),
            datetime(2026, 4, 5, 6, 0, tzinfo=local_tz),
        )
        is True
    )


@pytest.mark.unit
def test_run_due_jobs_waits_for_first_script_job_occurrence() -> None:
    state = SimpleNamespace(
        ensure_first_seen=Mock(
            return_value=SimpleNamespace(
                first_seen_at=datetime(2026, 4, 4, 9, 0, tzinfo=UTC),
                last_run=None,
                last_status="never",
            )
        ),
        mark_success=Mock(),
        mark_failed=Mock(),
    )
    schedules = {
        "alpha": SimpleNamespace(
            category="system",
            type=None,
            timeout=None,
            schedule=None,
            when=SimpleNamespace(every="60m", at=None, weekdays=None),
        )
    }
    script_job = runner.ScriptJob(name="alpha", script="jobs/alpha.py")

    with (
        patch("teleclaude.cron.runner._acquire_pidlock", return_value=True),
        patch("teleclaude.cron.runner.CronState.load", return_value=state),
        patch("teleclaude.cron.runner.discover_jobs", return_value=[script_job]),
        patch("teleclaude.cron.runner._load_job_schedules", return_value=schedules),
        patch("teleclaude.cron.runner.datetime") as datetime_mock,
        patch("teleclaude.cron.runner._run_script_job", return_value=JobResult(success=True, message="ok")) as run_mock,
        patch("teleclaude.cron.runner._scan_and_notify"),
    ):
        datetime_mock.now.return_value = datetime(2026, 4, 4, 9, 30, tzinfo=UTC)
        results = runner.run_due_jobs()

    assert results == {}
    run_mock.assert_not_called()
    state.mark_success.assert_not_called()
    state.mark_failed.assert_not_called()


@pytest.mark.unit
def test_run_due_jobs_executes_script_job_after_first_interval_elapsed() -> None:
    state = SimpleNamespace(
        ensure_first_seen=Mock(
            return_value=SimpleNamespace(
                first_seen_at=datetime(2026, 4, 4, 9, 0, tzinfo=UTC),
                last_run=None,
                last_status="never",
            )
        ),
        mark_success=Mock(),
        mark_failed=Mock(),
    )
    schedules = {
        "alpha": SimpleNamespace(
            category="system",
            type=None,
            timeout=None,
            schedule=None,
            when=SimpleNamespace(every="60m", at=None, weekdays=None),
        )
    }
    script_job = runner.ScriptJob(name="alpha", script="jobs/alpha.py")

    with (
        patch("teleclaude.cron.runner._acquire_pidlock", return_value=True),
        patch("teleclaude.cron.runner.CronState.load", return_value=state),
        patch("teleclaude.cron.runner.discover_jobs", return_value=[script_job]),
        patch("teleclaude.cron.runner._load_job_schedules", return_value=schedules),
        patch("teleclaude.cron.runner.datetime") as datetime_mock,
        patch("teleclaude.cron.runner._run_script_job", return_value=JobResult(success=True, message="ok")) as run_mock,
        patch("teleclaude.cron.runner._scan_and_notify"),
    ):
        datetime_mock.now.return_value = datetime(2026, 4, 4, 10, 1, tzinfo=UTC)
        results = runner.run_due_jobs()

    assert results == {"alpha": True}
    run_mock.assert_called_once_with(script_job, timeout_s=None)
    state.mark_success.assert_called_once_with("alpha")
    state.mark_failed.assert_not_called()
