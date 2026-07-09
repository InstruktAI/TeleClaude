from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from jobs.base import JobResult
from teleclaude.config.schema import JobScheduleConfig
from teleclaude.constants import ROLE_JOB_RUNNER
from teleclaude.cron import runner
from teleclaude.cron.state import CronState, JobRunStatus, PendingEmission
from teleclaude.events.schemas.jobs import JobRunEventType
from teleclaude.services.log_bug_hunter_service import LOG_BUG_HUNTER_JOB

pytestmark = pytest.mark.functional


def test_agent_job_dispatch_uses_slash_command_initial_input(monkeypatch: pytest.MonkeyPatch, snapshot) -> None:
    captured_messages: list[str] = []
    captured_metadata: list[object] = []

    class FakeResponse:
        session_id = "sess-job"

    class FakeClient:
        async def connect(self) -> None:
            return None

        async def create_session(self, **kwargs: object) -> FakeResponse:
            message = kwargs["message"]
            assert isinstance(message, str)
            captured_messages.append(message)
            captured_metadata.append(kwargs["metadata"])
            return FakeResponse()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(runner, "TelecAPIClient", FakeClient)

    session_id = runner._run_agent_job("daily_digest", JobScheduleConfig(type="agent", job="daily-digest"))

    assert session_id
    assert captured_messages == snapshot
    # The generic scheduled-agent job path is a job-runner filing — the sole
    # no-human lineage root the creation contract permits (UC-WTC26).
    [metadata] = captured_metadata
    assert isinstance(metadata, dict)
    assert metadata["system_role"] == ROLE_JOB_RUNNER


def test_agent_dispatch_opens_run_without_marking_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: True)
    monkeypatch.setattr(runner.CronState, "load", classmethod(lambda cls: state))
    monkeypatch.setattr(runner, "discover_jobs", lambda: [])
    monkeypatch.setattr(
        runner,
        "_load_job_schedules",
        lambda: {"daily_digest": JobScheduleConfig(type="agent", job="daily-digest")},
    )
    monkeypatch.setattr(runner, "_dispatch_agent_job", lambda name, config: "sess-job")
    monkeypatch.setattr(runner, "_drain_pending_emissions", lambda state: None)

    results = runner.run_due_jobs(force=True)

    assert results["daily_digest"] is True
    job = state.get_job("daily_digest")
    assert job.last_status is JobRunStatus.RUNNING
    assert job.run_session_id
    assert state.iter_pending_emissions() == []


def test_open_run_is_not_dispatched_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    state.open_run("daily_digest", started_at=datetime.now(UTC), session_id="sess-open")
    dispatched: list[str] = []
    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: True)
    monkeypatch.setattr(runner.CronState, "load", classmethod(lambda cls: state))
    monkeypatch.setattr(runner, "discover_jobs", lambda: [])
    monkeypatch.setattr(
        runner,
        "_load_job_schedules",
        lambda: {"daily_digest": JobScheduleConfig(type="agent", job="daily-digest")},
    )
    monkeypatch.setattr(runner, "_dispatch_agent_job", lambda name, config: dispatched.append(name) or "sess-new")
    monkeypatch.setattr(runner, "_drain_pending_emissions", lambda state: None)

    results = runner.run_due_jobs(force=True)

    assert results == {}
    assert dispatched == []
    assert state.get_job("daily_digest").run_session_id


def test_log_bug_hunter_closes_synchronous_outcome_without_later_stall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    schedules = {LOG_BUG_HUNTER_JOB: JobScheduleConfig(type="agent", job=LOG_BUG_HUNTER_JOB, timeout=1)}
    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: True)
    monkeypatch.setattr(runner.CronState, "load", classmethod(lambda cls: state))
    monkeypatch.setattr(runner, "discover_jobs", lambda: [])
    monkeypatch.setattr(runner, "_load_job_schedules", lambda: schedules)
    monkeypatch.setattr(runner, "_run_log_bug_hunter_orchestrated", lambda: True)
    monkeypatch.setattr(runner, "_drain_pending_emissions", lambda state: None)

    results = runner.run_due_jobs(force=True)
    runner._mark_stalled_runs(state, schedules, now=datetime.now(UTC) + timedelta(minutes=31))

    assert results[LOG_BUG_HUNTER_JOB] is True
    assert state.get_job(LOG_BUG_HUNTER_JOB).last_status is JobRunStatus.SUCCESS
    assert state.iter_open_runs() == []
    assert all(emission.event_type != JobRunEventType.STALLED for emission in state.iter_pending_emissions())


def test_reported_agent_result_closes_run_and_queues_outcome(tmp_path: Path) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    started_at = datetime.now(UTC) - timedelta(seconds=1)
    state.open_run("daily_digest", started_at=started_at, session_id="sess-job")
    runs_dir = tmp_path / "jobs" / "daily_digest" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "reported.json").write_text(JobResult(success=True, message="done", items_processed=2).to_json())

    runner._close_reported_agent_runs(
        state,
        {"daily_digest": JobScheduleConfig(type="agent", job="daily-digest")},
        jobs_dir=tmp_path / "jobs",
    )

    assert state.get_job("daily_digest").last_status is JobRunStatus.SUCCESS
    emission = state.iter_pending_emissions()[0]
    assert emission.event_type == JobRunEventType.SUCCEEDED
    assert emission.items == 2


def test_stalled_agent_run_queues_actionable_outcome(tmp_path: Path) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    state.open_run(
        "daily_digest",
        started_at=datetime.now(UTC) - timedelta(seconds=120),
        session_id="sess-job",
    )

    runner._mark_stalled_runs(
        state,
        {"daily_digest": JobScheduleConfig(type="agent", job="daily-digest", timeout=1)},
        now=datetime.now(UTC),
    )

    assert state.get_job("daily_digest").last_status is JobRunStatus.STALLED
    emission = state.iter_pending_emissions()[0]
    assert emission.event_type == JobRunEventType.STALLED
    assert emission.actionable is True


def test_pending_emission_drain_retries_until_publish_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    state.add_pending_emission(
        PendingEmission(
            idempotency_key="daily_digest:2026-07-07T12:00:00+00:00",
            event_type=JobRunEventType.FAILED,
            job_name="daily_digest",
            status=JobRunStatus.FAILED,
            message="failed",
            items=0,
            actionable=True,
        )
    )

    class FakeProducer:
        def __init__(self) -> None:
            self.calls = 0

        async def emit(self, envelope: Any) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("publish failed")
            return "1-0"

    producer = FakeProducer()
    monkeypatch.setattr(runner, "ensure_event_producer", lambda: producer)

    with pytest.raises(RuntimeError):
        runner._drain_pending_emissions(state)
    assert state.has_unnotified_actionable("daily_digest") is True

    runner._drain_pending_emissions(state)

    assert state.iter_pending_emissions() == []


def test_script_timeout_aborts_remaining_due_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = CronState(path=tmp_path / "cron_state.json")
    first = runner.ScriptJob(name="first", script="jobs/first.py", module_name="jobs.first")
    second = runner.ScriptJob(name="second", script="jobs/second.py", module_name="jobs.second")
    started: list[str] = []

    def run_script(job: runner.ScriptJob, timeout_s: int | None = None) -> tuple[JobResult, bool]:
        started.append(job.name)
        return JobResult(success=False, message="timed out"), True

    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: True)
    monkeypatch.setattr(runner.CronState, "load", classmethod(lambda cls: state))
    monkeypatch.setattr(runner, "discover_jobs", lambda: [first, second])
    monkeypatch.setattr(
        runner,
        "_load_job_schedules",
        lambda: {
            "first": JobScheduleConfig(script="jobs/first.py", timeout=1),
            "second": JobScheduleConfig(script="jobs/second.py", timeout=1),
        },
    )
    monkeypatch.setattr(runner, "_run_script_job", run_script)
    monkeypatch.setattr(runner, "_drain_pending_emissions", lambda state: None)

    results = runner.run_due_jobs(force=True)

    assert results == {"first": False}
    assert started == ["first"]
