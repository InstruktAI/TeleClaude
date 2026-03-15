"""Characterization tests for teleclaude.cron.notification_scan."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from teleclaude.cron.notification_scan import find_undelivered_reports
from teleclaude.cron.state import CronState, JobState


class TestFindUndeliveredReports:
    @pytest.mark.unit
    def test_returns_empty_for_missing_jobs_dir(self, tmp_path: Path) -> None:
        state = CronState(path=tmp_path / "cron-state.json")
        assert find_undelivered_reports(tmp_path / "missing", state) == {}

    @pytest.mark.unit
    def test_groups_reports_newer_than_last_notified(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        alpha_old = jobs_dir / "alpha" / "runs" / "20240101.md"
        alpha_new = jobs_dir / "alpha" / "runs" / "20240103.md"
        beta_report = jobs_dir / "beta" / "runs" / "20240104.md"

        for report in (alpha_old, alpha_new, beta_report):
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(f"{report.name}\n", encoding="utf-8")

        old_time = datetime(2024, 1, 1, 8, 0, tzinfo=UTC)
        cutoff = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
        new_time = datetime(2024, 1, 3, 8, 0, tzinfo=UTC)
        beta_time = datetime(2024, 1, 4, 8, 0, tzinfo=UTC)
        os.utime(alpha_old, (old_time.timestamp(), old_time.timestamp()))
        os.utime(alpha_new, (new_time.timestamp(), new_time.timestamp()))
        os.utime(beta_report, (beta_time.timestamp(), beta_time.timestamp()))

        state = CronState(
            path=tmp_path / "cron-state.json",
            jobs={"alpha": JobState(last_notified=cutoff)},
        )

        reports = find_undelivered_reports(jobs_dir, state)

        assert reports == {
            "alpha": [alpha_new],
            "beta": [beta_report],
        }
