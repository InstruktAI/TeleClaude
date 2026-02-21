"""Unit tests for subscription-driven cron runner logic."""

from pathlib import Path
from types import SimpleNamespace

from teleclaude.config.schema import JobScheduleConfig
from teleclaude.cron import runner


def _setup_people_with_subscription(tmp_path: Path, job_name: str, *, enabled: bool = True) -> Path:
    """Create a test people dir with a subscription to the given job."""
    root = tmp_path / ".teleclaude"
    (root / "people" / "alice").mkdir(parents=True)

    (root / "teleclaude.yml").write_text(
        """
people:
  - name: alice
    email: alice@example.com
    role: admin
""",
        encoding="utf-8",
    )

    enabled_str = "true" if enabled else "false"
    (root / "people" / "alice" / "teleclaude.yml").write_text(
        f"""
creds:
  telegram:
    user_name: alice
    user_id: 111
    chat_id: "111"
subscriptions:
  - type: job
    job: {job_name}
    enabled: {enabled_str}
    when:
      every: "1h"
""",
        encoding="utf-8",
    )

    return root


def test_subscription_job_skipped_without_subscribers(monkeypatch, tmp_path: Path) -> None:
    """A subscription job with no subscribers should be skipped."""

    class _State:
        def get_job(self, _name: str) -> SimpleNamespace:
            return SimpleNamespace(last_run=None)

        def mark_success(self, _name: str) -> None:
            return None

        def mark_failed(self, _name: str, _error: str) -> None:
            return None

    class _FakeStateHolder:
        @staticmethod
        def load() -> _State:
            return _State()

    root = tmp_path / ".teleclaude"
    root.mkdir(parents=True)
    (root / "teleclaude.yml").write_text("people: []\n", encoding="utf-8")

    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: True)
    monkeypatch.setattr(
        runner,
        "_load_job_schedules",
        lambda config_path=None: {
            "idea-miner": JobScheduleConfig(schedule="hourly", category="subscription"),
        },
    )
    monkeypatch.setattr(runner, "discover_jobs", lambda: [])
    monkeypatch.setattr(runner, "CronState", _FakeStateHolder)
    monkeypatch.setattr(runner, "_scan_and_notify", lambda state, schedules, root=None: None)

    results = runner.run_due_jobs(root=root)
    assert results == {}


def test_subscription_job_skipped_when_all_disabled(monkeypatch, tmp_path: Path) -> None:
    """A subscription job should be skipped when all subscribers have enabled=false."""

    class _State:
        def get_job(self, _name: str) -> SimpleNamespace:
            return SimpleNamespace(last_run=None)

        def mark_success(self, _name: str) -> None:
            return None

        def mark_failed(self, _name: str, _error: str) -> None:
            return None

    class _FakeStateHolder:
        @staticmethod
        def load() -> _State:
            return _State()

    root = _setup_people_with_subscription(tmp_path, "idea-miner", enabled=False)

    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: True)
    monkeypatch.setattr(
        runner,
        "_load_job_schedules",
        lambda config_path=None: {
            "idea-miner": JobScheduleConfig(schedule="hourly", category="subscription"),
        },
    )
    monkeypatch.setattr(runner, "discover_jobs", lambda: [])
    monkeypatch.setattr(runner, "CronState", _FakeStateHolder)
    monkeypatch.setattr(runner, "_scan_and_notify", lambda state, schedules, root=None: None)

    results = runner.run_due_jobs(root=root)
    assert results == {}


def test_system_job_always_due_when_schedule_says_so(monkeypatch, tmp_path: Path) -> None:
    """A system-category job uses its own schedule, not subscriptions."""

    class _State:
        def get_job(self, _name: str) -> SimpleNamespace:
            return SimpleNamespace(last_run=None)

        def mark_success(self, _name: str) -> None:
            return None

        def mark_failed(self, _name: str, _error: str) -> None:
            return None

    class _FakeStateHolder:
        @staticmethod
        def load() -> _State:
            return _State()

    class _PythonJob:
        name = "maintenance"

        def run(self) -> SimpleNamespace:
            return SimpleNamespace(success=True, message="ok", items_processed=0, errors=None)

    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: True)
    monkeypatch.setattr(
        runner,
        "_load_job_schedules",
        lambda config_path=None: {
            "maintenance": JobScheduleConfig(schedule="hourly", category="system"),
        },
    )
    monkeypatch.setattr(runner, "discover_jobs", lambda: [_PythonJob()])
    monkeypatch.setattr(runner, "CronState", _FakeStateHolder)
    monkeypatch.setattr(runner, "_scan_and_notify", lambda state, schedules, root=None: None)

    results = runner.run_due_jobs(root=tmp_path)
    assert results == {"maintenance": True}


def test_should_run_subscription_job_returns_true_for_enabled_subscriber(tmp_path: Path) -> None:
    """_should_run_subscription_job should return True when a subscriber is enabled and due."""
    from teleclaude.cron.state import CronState

    root = _setup_people_with_subscription(tmp_path, "idea-miner", enabled=True)
    state = CronState.load(tmp_path / "state.json")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    assert runner._should_run_subscription_job("idea-miner", state, now, root=root) is True


def test_should_run_subscription_job_returns_false_for_disabled(tmp_path: Path) -> None:
    """_should_run_subscription_job should return False when subscriber is disabled."""
    from teleclaude.cron.state import CronState

    root = _setup_people_with_subscription(tmp_path, "idea-miner", enabled=False)
    state = CronState.load(tmp_path / "state.json")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    assert runner._should_run_subscription_job("idea-miner", state, now, root=root) is False
