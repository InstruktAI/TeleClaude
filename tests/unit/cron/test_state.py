"""Characterization tests for teleclaude.cron.state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from teleclaude.cron.state import CronState, JobState, JobStateDict


class TestJobState:
    @pytest.mark.unit
    def test_from_dict_ignores_invalid_timestamps(self) -> None:
        state = JobState.from_dict(
            cast(
                JobStateDict,
                {
                    "last_run": "not-a-datetime",
                    "last_status": "failed",
                    "last_error": "boom",
                    "last_notified": 123,
                },
            )
        )

        assert state.last_run is None
        assert state.last_status == "failed"
        assert state.last_error == "boom"
        assert state.last_notified is None


class TestCronState:
    @pytest.mark.unit
    def test_load_returns_empty_state_when_file_is_missing(self, tmp_path: Path) -> None:
        state = CronState.load(tmp_path / "missing.json")
        assert state.jobs == {}

    @pytest.mark.unit
    def test_load_ignores_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-state.json"
        path.write_text("{not-json", encoding="utf-8")

        state = CronState.load(path)

        assert state.jobs == {}

    @pytest.mark.unit
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-state.json"
        last_run = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        last_notified = datetime(2024, 1, 3, 9, 0, tzinfo=UTC)
        state = CronState(
            path=path,
            jobs={
                "nightly": JobState(
                    last_run=last_run,
                    last_status="success",
                    last_error=None,
                    last_notified=last_notified,
                )
            },
        )

        state.save()
        loaded = CronState.load(path)

        assert loaded.jobs["nightly"].last_run == last_run
        assert loaded.jobs["nightly"].last_status == "success"
        assert loaded.jobs["nightly"].last_error is None
        assert loaded.jobs["nightly"].last_notified == last_notified

    @pytest.mark.unit
    def test_get_job_creates_default_state(self, tmp_path: Path) -> None:
        state = CronState(path=tmp_path / "cron-state.json")

        job_state = state.get_job("digest")

        assert job_state.last_status == "never"
        assert state.jobs["digest"] is job_state

    @pytest.mark.unit
    def test_mark_methods_update_state_and_persist(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-state.json"
        state = CronState(path=path)

        state.mark_success("nightly")
        after_success = CronState.load(path).jobs["nightly"]
        assert after_success.last_status == "success"
        assert after_success.last_error is None
        assert after_success.last_run is not None
        assert after_success.last_run.tzinfo == UTC

        state.mark_failed("nightly", "boom")
        after_failure = CronState.load(path).jobs["nightly"]
        assert after_failure.last_status == "failed"
        assert after_failure.last_error == "boom"
        assert after_failure.last_run is not None

        notified_at = datetime(2024, 1, 4, 10, 0, tzinfo=UTC)
        state.mark_notified("nightly", notified_at)
        after_notify = CronState.load(path).jobs["nightly"]
        assert after_notify.last_notified == notified_at
