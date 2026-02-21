"""Unit tests for notification_scan — mailbox flag pattern."""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from teleclaude.cron.notification_scan import find_undelivered_reports
from teleclaude.cron.state import CronState


def _create_report(jobs_dir: Path, job_name: str, filename: str, content: str = "# Report") -> Path:
    """Create a report file at the expected path."""
    report_dir = jobs_dir / job_name / "runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / filename
    report_path.write_text(content, encoding="utf-8")
    return report_path


def test_finds_undelivered_reports(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    state = CronState.load(tmp_path / "state.json")

    _create_report(jobs_dir, "idea-miner", "2026-02-20.md")
    _create_report(jobs_dir, "idea-miner", "2026-02-21.md")

    result = find_undelivered_reports(jobs_dir, state)
    assert "idea-miner" in result
    assert len(result["idea-miner"]) == 2


def test_skips_already_notified(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    state = CronState.load(tmp_path / "state.json")

    report = _create_report(jobs_dir, "idea-miner", "2026-02-20.md")

    # Set last_notified to after the report's mtime
    mtime = datetime.fromtimestamp(report.stat().st_mtime, tz=timezone.utc)
    state.mark_notified("idea-miner", mtime)

    # Ensure next file has strictly older mtime by backdating
    old_report = _create_report(jobs_dir, "idea-miner", "2026-02-19.md")
    old_ts = mtime.timestamp() - 10
    os.utime(old_report, (old_ts, old_ts))

    result = find_undelivered_reports(jobs_dir, state)
    assert result.get("idea-miner", []) == []


def test_empty_when_no_reports(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    state = CronState.load(tmp_path / "state.json")

    result = find_undelivered_reports(jobs_dir, state)
    assert result == {}


def test_empty_when_jobs_dir_missing(tmp_path: Path) -> None:
    state = CronState.load(tmp_path / "state.json")
    result = find_undelivered_reports(tmp_path / "nonexistent", state)
    assert result == {}


def test_multiple_jobs(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    state = CronState.load(tmp_path / "state.json")

    _create_report(jobs_dir, "idea-miner", "report1.md")
    # Small delay so mtimes differ from any notified timestamp
    time.sleep(0.01)
    _create_report(jobs_dir, "maintenance", "report1.md")

    result = find_undelivered_reports(jobs_dir, state)
    assert "idea-miner" in result
    assert "maintenance" in result
    assert len(result["idea-miner"]) == 1
    assert len(result["maintenance"]) == 1
