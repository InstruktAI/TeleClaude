"""Characterization tests for teleclaude.cli.tui.widgets.job_row."""

from __future__ import annotations

import pytest

from teleclaude.cli.models import JobInfo
from teleclaude.cli.tui.widgets.job_row import JobRow


def _make_job(*, name: str = "test-job", status: str = "running", job_type: str = "agent") -> JobInfo:
    return JobInfo(name=name, type=job_type, status=status)


@pytest.mark.unit
def test_job_row_is_importable() -> None:
    assert JobRow is not None


@pytest.mark.unit
def test_job_row_stores_job() -> None:
    job = _make_job()
    row = JobRow(job=job)
    assert row.job is job


@pytest.mark.unit
def test_job_row_accepts_running_status() -> None:
    job = _make_job(status="running")
    row = JobRow(job=job)
    assert row.job.status == "running"


@pytest.mark.unit
def test_job_row_accepts_failed_status() -> None:
    job = _make_job(status="failed")
    row = JobRow(job=job)
    assert row.job.status == "failed"
