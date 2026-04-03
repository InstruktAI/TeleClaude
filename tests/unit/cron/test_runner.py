"""Unit tests for the cron runner execution model."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from jobs.base import JobResult
from teleclaude.cron import runner


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
def test_run_due_jobs_executes_configured_script_jobs() -> None:
    state = SimpleNamespace(
        get_job=Mock(return_value=SimpleNamespace(last_run=None, last_status="never")),
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
        patch("teleclaude.cron.runner._run_script_job", return_value=JobResult(success=True, message="ok")) as run_mock,
        patch("teleclaude.cron.runner._scan_and_notify"),
    ):
        results = runner.run_due_jobs()

    assert results == {"alpha": True}
    run_mock.assert_called_once_with(script_job, timeout_s=None)
    state.mark_success.assert_called_once_with("alpha")
    state.mark_failed.assert_not_called()
