"""Behavioral tests for _is_due() scheduler logic."""

from datetime import datetime, timezone

import pytest

from teleclaude.config.schema import JobScheduleConfig, JobWhenConfig
from teleclaude.cron.runner import _is_due


@pytest.mark.unit
def test_is_due_when_every_returns_true_when_elapsed_exceeds_interval() -> None:
    """when.every triggers when elapsed time exceeds the interval."""
    schedule = JobScheduleConfig(
        type="agent",
        job="test",
        when=JobWhenConfig(every="1h"),
    )
    now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)  # 1.5 hours ago

    assert _is_due(schedule, last_run, now) is True


@pytest.mark.unit
def test_is_due_when_every_returns_false_when_elapsed_below_interval() -> None:
    """when.every does not trigger when elapsed time is below the interval."""
    schedule = JobScheduleConfig(
        type="agent",
        job="test",
        when=JobWhenConfig(every="2h"),
    )
    now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    last_run = datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)  # 1 hour ago

    assert _is_due(schedule, last_run, now) is False


@pytest.mark.unit
def test_is_due_when_at_single_time_triggers_when_past_scheduled_time_and_not_run_today() -> None:
    """when.at (single time) triggers when current time is past scheduled time and hasn't run today."""
    schedule = JobScheduleConfig(
        type="agent",
        job="test",
        when=JobWhenConfig(at="09:00"),
    )
    # Current time: 10:00 local
    now = datetime(2025, 1, 15, 10, 0, 0).astimezone()
    # Last run: yesterday at 10:00 local
    last_run = (datetime(2025, 1, 14, 10, 0, 0).astimezone()).astimezone(timezone.utc)

    assert _is_due(schedule, last_run, now.astimezone(timezone.utc)) is True


@pytest.mark.unit
def test_is_due_when_at_single_time_does_not_trigger_when_already_run_today() -> None:
    """when.at (single time) does not trigger when already run today after scheduled time."""
    schedule = JobScheduleConfig(
        type="agent",
        job="test",
        when=JobWhenConfig(at="09:00"),
    )
    # Current time: 10:00 local
    now = datetime(2025, 1, 15, 10, 0, 0).astimezone()
    # Last run: today at 09:30 local (after scheduled 09:00)
    last_run = (datetime(2025, 1, 15, 9, 30, 0).astimezone()).astimezone(timezone.utc)

    assert _is_due(schedule, last_run, now.astimezone(timezone.utc)) is False


@pytest.mark.unit
def test_is_due_when_at_multiple_times_triggers_on_any_eligible_time() -> None:
    """when.at (list) triggers if any time matches and hasn't been run since that time."""
    schedule = JobScheduleConfig(
        type="agent",
        job="test",
        when=JobWhenConfig(at=["09:00", "17:00"]),
    )
    # Current time: 17:30 local
    now = datetime(2025, 1, 15, 17, 30, 0).astimezone()
    # Last run: today at 09:15 local (after 09:00 but before 17:00)
    last_run = (datetime(2025, 1, 15, 9, 15, 0).astimezone()).astimezone(timezone.utc)

    assert _is_due(schedule, last_run, now.astimezone(timezone.utc)) is True


@pytest.mark.unit
def test_is_due_when_at_with_weekdays_triggers_only_on_matching_days() -> None:
    """when.at with weekdays only triggers on specified weekdays."""
    schedule = JobScheduleConfig(
        type="agent",
        job="test",
        when=JobWhenConfig(at="09:00", weekdays=["mon", "wed", "fri"]),
    )
    # Wednesday 2025-01-15 at 10:00 local
    wed_now = datetime(2025, 1, 15, 10, 0, 0).astimezone()
    # Last run: Tuesday at 10:00 local
    last_run_tue = (datetime(2025, 1, 14, 10, 0, 0).astimezone()).astimezone(timezone.utc)

    # Should trigger on Wednesday
    assert _is_due(schedule, last_run_tue, wed_now.astimezone(timezone.utc)) is True

    # Thursday 2025-01-16 at 10:00 local (not in weekdays list)
    thu_now = datetime(2025, 1, 16, 10, 0, 0).astimezone()
    # Last run: Wednesday at 10:00 local
    last_run_wed = (datetime(2025, 1, 15, 10, 0, 0).astimezone()).astimezone(timezone.utc)

    # Should NOT trigger on Thursday
    assert _is_due(schedule, last_run_wed, thu_now.astimezone(timezone.utc)) is False


@pytest.mark.unit
def test_is_due_when_at_respects_local_timezone_boundaries() -> None:
    """when.at uses local timezone for wall-clock time comparisons."""
    schedule = JobScheduleConfig(
        type="agent",
        job="test",
        when=JobWhenConfig(at="09:00"),
    )
    # Current time: 09:30 local (whatever the system timezone is)
    now = datetime(2025, 1, 15, 9, 30, 0).astimezone()
    # Last run: yesterday at 10:00 local
    last_run = (datetime(2025, 1, 14, 10, 0, 0).astimezone()).astimezone(timezone.utc)

    # Should trigger because local time is past 09:00 and hasn't run since 09:00 today
    assert _is_due(schedule, last_run, now.astimezone(timezone.utc)) is True


@pytest.mark.unit
def test_is_due_when_at_does_not_trigger_before_scheduled_time() -> None:
    """when.at does not trigger when current time is before the scheduled time."""
    schedule = JobScheduleConfig(
        type="agent",
        job="test",
        when=JobWhenConfig(at="09:00"),
    )
    # Current time: 08:30 local (before scheduled 09:00)
    now = datetime(2025, 1, 15, 8, 30, 0).astimezone()
    # Last run: yesterday at 09:30 local
    last_run = (datetime(2025, 1, 14, 9, 30, 0).astimezone()).astimezone(timezone.utc)

    assert _is_due(schedule, last_run, now.astimezone(timezone.utc)) is False
