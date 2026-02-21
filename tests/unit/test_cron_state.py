"""Unit tests for CronState last_notified field and mark_notified method."""

from datetime import datetime, timezone

from teleclaude.cron.state import CronState, JobState


def test_job_state_last_notified_default_none():
    state = JobState()
    assert state.last_notified is None


def test_job_state_roundtrip_with_last_notified():
    ts = datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc)
    state = JobState(last_notified=ts)
    d = state.to_dict()
    assert d["last_notified"] == ts.isoformat()

    restored = JobState.from_dict(d)
    assert restored.last_notified == ts


def test_job_state_roundtrip_without_last_notified():
    state = JobState()
    d = state.to_dict()
    assert d["last_notified"] is None

    restored = JobState.from_dict(d)
    assert restored.last_notified is None


def test_mark_notified_creates_job_if_missing(tmp_path):
    state_path = tmp_path / "cron_state.json"
    state = CronState.load(state_path)
    assert "new_job" not in state.jobs

    ts = datetime(2026, 2, 20, 14, 30, 0, tzinfo=timezone.utc)
    state.mark_notified("new_job", ts)

    assert "new_job" in state.jobs
    assert state.jobs["new_job"].last_notified == ts

    # Verify persistence
    reloaded = CronState.load(state_path)
    assert reloaded.jobs["new_job"].last_notified == ts


def test_mark_notified_updates_existing_job(tmp_path):
    state_path = tmp_path / "cron_state.json"
    state = CronState.load(state_path)
    state.mark_success("existing_job")

    ts = datetime(2026, 2, 20, 15, 0, 0, tzinfo=timezone.utc)
    state.mark_notified("existing_job", ts)

    assert state.jobs["existing_job"].last_notified == ts
    assert state.jobs["existing_job"].last_status == "success"
