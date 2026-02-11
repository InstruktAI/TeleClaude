"""Tests for daemon-independent job execution.

Covers: run_job() CLI flags, _run_agent_job() subprocess dispatch,
overlap prevention (pidfile), and --list agent job display.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from teleclaude.config.schema import JobScheduleConfig
from teleclaude.cron import runner
from teleclaude.helpers import agent_cli
from teleclaude.helpers.agent_types import AgentName

# ---------------------------------------------------------------------------
# run_job() builds correct CLI flags
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_job_no_tools_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_job() must NOT pass --tools '' (unlike run_once)."""
    captured_cmd: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(agent_cli, "_pick_agent", lambda _: AgentName.CLAUDE)
    monkeypatch.setattr(agent_cli, "resolve_agent_binary", lambda _: "/usr/bin/claude")

    agent_cli.run_job(agent="claude", thinking_mode="fast", prompt="hello")

    cmd_str = " ".join(captured_cmd)
    assert '--tools ""' not in cmd_str
    assert '--tools ""' not in cmd_str


@pytest.mark.unit
def test_run_job_sets_role_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_job() sets TELECLAUDE_JOB_ROLE in subprocess environment."""
    captured_env: dict = {}

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(agent_cli, "_pick_agent", lambda _: AgentName.CLAUDE)
    monkeypatch.setattr(agent_cli, "resolve_agent_binary", lambda _: "/usr/bin/claude")

    agent_cli.run_job(agent="claude", thinking_mode="fast", prompt="hello", role="admin")

    assert captured_env.get("TELECLAUDE_JOB_ROLE") == "admin"


@pytest.mark.unit
def test_run_job_returns_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_job() returns the subprocess exit code."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 42),
    )
    monkeypatch.setattr(agent_cli, "_pick_agent", lambda _: AgentName.CLAUDE)
    monkeypatch.setattr(agent_cli, "resolve_agent_binary", lambda _: "/usr/bin/claude")

    code = agent_cli.run_job(agent="claude", thinking_mode="fast", prompt="hello")
    assert code == 42


@pytest.mark.unit
def test_run_job_passes_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_job() passes timeout_s to subprocess.run."""
    captured_kwargs: dict = {}

    def fake_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(agent_cli, "_pick_agent", lambda _: AgentName.CLAUDE)
    monkeypatch.setattr(agent_cli, "resolve_agent_binary", lambda _: "/usr/bin/claude")

    agent_cli.run_job(agent="claude", thinking_mode="fast", prompt="hello", timeout_s=600)

    assert captured_kwargs["timeout"] == 600


# ---------------------------------------------------------------------------
# _run_agent_job() uses run_job(), not daemon API
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_agent_job_calls_run_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """_run_agent_job() dispatches to run_job() instead of daemon socket."""
    call_args: dict = {}

    def fake_run_job(**kwargs):
        call_args.update(kwargs)
        return 0

    monkeypatch.setattr("teleclaude.helpers.agent_cli.run_job", fake_run_job)

    config = JobScheduleConfig(type="agent", job="memory-review", timeout=900)
    result = runner._run_agent_job("memory_review", config)

    assert result is True
    assert call_args["agent"] == "claude"
    assert call_args["thinking_mode"] == "fast"
    assert call_args["role"] == "admin"
    assert call_args["timeout_s"] == 900
    assert "@docs/project/spec/jobs/memory-review.md" in call_args["prompt"]


@pytest.mark.unit
def test_run_agent_job_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """_run_agent_job() uses 30-minute default when config has no timeout."""
    call_args: dict = {}

    def fake_run_job(**kwargs):
        call_args.update(kwargs)
        return 0

    monkeypatch.setattr("teleclaude.helpers.agent_cli.run_job", fake_run_job)

    config = JobScheduleConfig(type="agent", job="memory-review")
    runner._run_agent_job("memory_review", config)

    assert call_args["timeout_s"] == 1800


@pytest.mark.unit
def test_run_agent_job_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """_run_agent_job() returns False on non-zero exit."""
    monkeypatch.setattr("teleclaude.helpers.agent_cli.run_job", lambda **kw: 1)

    config = JobScheduleConfig(type="agent", job="memory-review")
    result = runner._run_agent_job("memory_review", config)
    assert result is False


# ---------------------------------------------------------------------------
# Overlap prevention (pidfile)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pidlock_acquired_when_no_pidfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pidfile = tmp_path / "cron_runner.pid"
    monkeypatch.setattr(runner, "_PIDFILE", pidfile)

    assert runner._acquire_pidlock() is True
    assert pidfile.exists()
    assert pidfile.read_text().strip() == str(os.getpid())


@pytest.mark.unit
def test_pidlock_blocked_by_live_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pidfile = tmp_path / "cron_runner.pid"
    pidfile.write_text(str(os.getpid()))  # current process is alive
    monkeypatch.setattr(runner, "_PIDFILE", pidfile)

    assert runner._acquire_pidlock() is False


@pytest.mark.unit
def test_pidlock_ignores_stale_pidfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pidfile = tmp_path / "cron_runner.pid"
    pidfile.write_text("999999999")  # almost certainly dead
    monkeypatch.setattr(runner, "_PIDFILE", pidfile)

    # os.kill(999999999, 0) should raise ProcessLookupError
    assert runner._acquire_pidlock() is True
    assert pidfile.read_text().strip() == str(os.getpid())


@pytest.mark.unit
def test_release_pidlock_removes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pidfile = tmp_path / "cron_runner.pid"
    pidfile.write_text(str(os.getpid()))
    monkeypatch.setattr(runner, "_PIDFILE", pidfile)

    runner._release_pidlock()
    assert not pidfile.exists()


@pytest.mark.unit
def test_run_due_jobs_skips_when_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_due_jobs() returns empty when another runner holds the pidlock."""
    monkeypatch.setattr(runner, "_acquire_pidlock", lambda: False)

    results = runner.run_due_jobs()
    assert results == {}
