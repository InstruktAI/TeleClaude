from __future__ import annotations

from pathlib import Path

import pytest

from jobs.base import JobResult
from teleclaude.cli.tool_commands import jobs as jobs_cmd

pytestmark = pytest.mark.functional


def test_jobs_report_writes_job_result_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_cmd, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs_cmd, "_load_known_job_names", lambda: {"daily_digest"})

    jobs_cmd.handle_jobs(
        [
            "report",
            "daily_digest",
            "--success",
            "true",
            "--message",
            "completed",
            "--items-processed",
            "3",
        ]
    )

    records = list((tmp_path / "jobs" / "daily_digest" / "runs").glob("*.json"))
    assert len(records) == 1
    result = JobResult.from_json(records[0].read_text(encoding="utf-8"))
    assert result.success is True
    assert result.items_processed == 3
    assert result.message
    assert result.errors is None


def test_jobs_report_rejects_path_traversal_before_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_cmd, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs_cmd, "_load_known_job_names", lambda: {"../escape"})

    with pytest.raises(SystemExit):
        jobs_cmd.handle_jobs(["report", "../escape", "--success", "false", "--message", "failed"])

    assert not (tmp_path / "jobs").exists()


def test_jobs_report_rejects_absolute_path_before_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job_name = str(tmp_path / "escape")
    monkeypatch.setattr(jobs_cmd, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs_cmd, "_load_known_job_names", lambda: {job_name})

    with pytest.raises(SystemExit):
        jobs_cmd.handle_jobs(["report", job_name, "--success", "false", "--message", "failed"])

    assert not (tmp_path / "jobs").exists()


def test_jobs_report_rejects_unknown_job_before_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_cmd, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs_cmd, "_load_known_job_names", lambda: {"daily_digest"})

    with pytest.raises(SystemExit):
        jobs_cmd.handle_jobs(["report", "unknown_job", "--success", "false", "--message", "failed"])

    assert not (tmp_path / "jobs").exists()
