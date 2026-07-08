from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from jobs.base import JobResult
from teleclaude.cron.state import CronState, JobRunStatus, PendingEmission

pytestmark = pytest.mark.functional


def test_open_run_then_close_success_records_real_outcome(tmp_path) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    started_at = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)

    state.open_run("daily_digest", started_at=started_at, session_id="sess-job")
    state.close_run("daily_digest", JobResult(success=True, message="completed"))

    job = state.get_job("daily_digest")
    assert job.last_status is JobRunStatus.SUCCESS
    assert job.last_run is not None
    assert job.run_started_at is None
    assert job.run_session_id is None
    assert job.last_error is None


def test_open_run_is_markable_stalled(tmp_path) -> None:
    state = CronState(path=tmp_path / "cron_state.json")

    state.open_run("feed_monitor", started_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC))
    state.mark_stalled("feed_monitor", "run did not close")

    job = state.get_job("feed_monitor")
    assert job.last_status is JobRunStatus.STALLED
    assert job.last_run is not None
    assert job.last_error is not None
    assert job.run_started_at is None


def test_pending_emission_survives_later_run_until_removed(tmp_path) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    first_started = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    second_started = datetime(2026, 7, 7, 13, 0, tzinfo=UTC)
    emission = PendingEmission(
        idempotency_key="feed_monitor:2026-07-07T12:00:00+00:00",
        event_type="job.run.failed",
        job_name="feed_monitor",
        status=JobRunStatus.FAILED,
        message="failed",
        items=0,
        actionable=True,
    )

    state.open_run("feed_monitor", started_at=first_started)
    state.close_run("feed_monitor", JobResult(success=False, message="failed"))
    state.add_pending_emission(emission)
    state.open_run("feed_monitor", started_at=second_started)
    state.close_run("feed_monitor", JobResult(success=True, message="recovered"))

    assert state.has_unnotified_actionable("feed_monitor") is True
    assert state.iter_pending_emissions() == [emission]

    state.remove_pending_emission(emission.idempotency_key)

    assert state.has_unnotified_actionable("feed_monitor") is False
    assert state.iter_pending_emissions() == []


def test_old_shape_cron_state_loads_and_normalizes(tmp_path, snapshot) -> None:
    path = tmp_path / "cron_state.json"
    path.write_text(
        json.dumps(
            {
                "jobs": {
                    "legacy_job": {
                        "first_seen_at": "2026-07-07T11:00:00+00:00",
                        "last_run": "2026-07-07T12:00:00+00:00",
                        "last_status": "success",
                        "last_error": None,
                        "last_notified": "2026-07-07T12:05:00+00:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    state = CronState.load(path)

    assert state.get_job("legacy_job").last_status is JobRunStatus.SUCCESS
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted == snapshot
