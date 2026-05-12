"""Tests for teleclaude.project_setup.onboard_flow."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

import pytest

import teleclaude.project_setup.onboard_flow as onboard_flow


class _SessionEntry(TypedDict):
    """Shape of one session record as returned by `telec sessions list`."""

    project_path: str
    title: str
    closed_at: str | None


class _CompletedProcess:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_subprocess_recorder(
    *,
    list_sessions_payload: list[_SessionEntry] | None = None,
    returncode: int = 0,
) -> tuple[list[list[str]], Callable[..., _CompletedProcess]]:
    """Build a fake subprocess.run that records every call.

    The fake distinguishes the dedup query (`telec sessions list`) from the
    dispatch (`telec sessions run`) so we can drive both paths from one stub.
    """
    calls: list[list[str]] = []
    payload: list[_SessionEntry] = list_sessions_payload or []

    def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> _CompletedProcess:
        _ = args, kwargs
        calls.append(list(cmd))
        if "list" in cmd and "sessions" in cmd:
            return _CompletedProcess(returncode=0, stdout=json.dumps(payload))
        return _CompletedProcess(returncode=returncode, stdout="", stderr="")

    return calls, fake_run


# ---------------------------------------------------------------------------
# run_analyze
# ---------------------------------------------------------------------------


def test_run_analyze_dispatches_projects_analyze_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls, fake_run = _make_subprocess_recorder()
    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    result = onboard_flow.run_analyze(tmp_path)

    assert result is True
    dispatch_calls = [c for c in calls if "run" in c and "sessions" in c]
    assert len(dispatch_calls) == 1
    assert "/projects-analyze" in dispatch_calls[0]
    assert str(tmp_path) in dispatch_calls[0]


def test_run_analyze_skips_when_active_session_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active = [
        {
            "project_path": str(tmp_path),
            "title": "/projects-analyze ...",
            "closed_at": None,
        }
    ]
    calls, fake_run = _make_subprocess_recorder(list_sessions_payload=active)
    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    result = onboard_flow.run_analyze(tmp_path)

    assert result is False
    dispatch_calls = [c for c in calls if "run" in c and "sessions" in c]
    assert dispatch_calls == []


def test_run_analyze_returns_false_on_dispatch_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _calls, fake_run = _make_subprocess_recorder(returncode=1)
    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    assert onboard_flow.run_analyze(tmp_path) is False


def test_run_analyze_returns_false_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> _CompletedProcess:
        _ = args, kwargs
        if "list" in cmd and "sessions" in cmd:
            return _CompletedProcess(returncode=0, stdout="[]")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    assert onboard_flow.run_analyze(tmp_path) is False


# ---------------------------------------------------------------------------
# run_assess
# ---------------------------------------------------------------------------


def test_run_assess_dispatches_projects_assess_config_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls, fake_run = _make_subprocess_recorder()
    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    result = onboard_flow.run_assess(tmp_path)

    assert result is True
    dispatch_calls = [c for c in calls if "run" in c and "sessions" in c]
    assert len(dispatch_calls) == 1
    assert "/projects-assess-config" in dispatch_calls[0]


def test_run_assess_skips_when_active_session_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active = [
        {
            "project_path": str(tmp_path),
            "title": "/projects-assess-config xxx",
            "closed_at": None,
        }
    ]
    calls, fake_run = _make_subprocess_recorder(list_sessions_payload=active)
    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    result = onboard_flow.run_assess(tmp_path)

    assert result is False
    dispatch_calls = [c for c in calls if "run" in c and "sessions" in c]
    assert dispatch_calls == []


# ---------------------------------------------------------------------------
# run_onboard
# ---------------------------------------------------------------------------


def test_run_onboard_runs_init_then_assess_then_analyze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Onboarding must call init plumbing first, then dispatch assess, then analyze."""
    call_order: list[str] = []

    def fake_init(project_root: Path) -> None:
        _ = project_root
        call_order.append("init")

    def fake_assess(project_root: Path) -> bool:
        _ = project_root
        call_order.append("assess")
        return True

    def fake_analyze(project_root: Path) -> bool:
        _ = project_root
        call_order.append("analyze")
        return True

    monkeypatch.setattr(onboard_flow, "init_project", fake_init)
    monkeypatch.setattr(onboard_flow, "run_assess", fake_assess)
    monkeypatch.setattr(onboard_flow, "run_analyze", fake_analyze)

    onboard_flow.run_onboard(tmp_path)

    assert call_order == ["init", "assess", "analyze"]


def test_run_onboard_dispatches_assess_and_analyze_after_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both AI dispatches must occur — onboard does not skip either."""
    assess_calls: list[Path] = []
    analyze_calls: list[Path] = []

    def fake_assess(project_root: Path) -> bool:
        assess_calls.append(project_root)
        return True

    def fake_analyze(project_root: Path) -> bool:
        analyze_calls.append(project_root)
        return True

    monkeypatch.setattr(onboard_flow, "init_project", lambda _p: None)
    monkeypatch.setattr(onboard_flow, "run_assess", fake_assess)
    monkeypatch.setattr(onboard_flow, "run_analyze", fake_analyze)

    onboard_flow.run_onboard(tmp_path)

    assert assess_calls == [tmp_path]
    assert analyze_calls == [tmp_path]


# ---------------------------------------------------------------------------
# _active_session_for_command
# ---------------------------------------------------------------------------


def test_active_session_for_command_matches_open_session_with_matching_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload: list[_SessionEntry] = [
        {
            "project_path": str(tmp_path),
            "title": "/projects-analyze running",
            "closed_at": None,
        }
    ]
    _calls, fake_run = _make_subprocess_recorder(list_sessions_payload=payload)
    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.ACTIVE


def test_active_session_for_command_ignores_closed_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: list[_SessionEntry] = [
        {
            "project_path": str(tmp_path),
            "title": "/projects-analyze finished",
            "closed_at": "2025-01-01T00:00:00Z",
        }
    ]
    _calls, fake_run = _make_subprocess_recorder(list_sessions_payload=payload)
    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.INACTIVE


def test_active_session_for_command_ignores_different_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: list[_SessionEntry] = [
        {
            "project_path": "/some/other/project",
            "title": "/projects-analyze running",
            "closed_at": None,
        }
    ]
    _calls, fake_run = _make_subprocess_recorder(list_sessions_payload=payload)
    monkeypatch.setattr(onboard_flow.subprocess, "run", fake_run)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.INACTIVE


def test_active_session_for_command_returns_unknown_on_lookup_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lookup failure must surface as UNKNOWN so callers fail closed."""

    def raising_run(cmd: list[str], *_args: object, **_kwargs: object) -> _CompletedProcess:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(onboard_flow.subprocess, "run", raising_run)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.UNKNOWN


def test_active_session_for_command_returns_unknown_on_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def garbled_run(cmd: list[str], *_args: object, **_kwargs: object) -> _CompletedProcess:
        _ = cmd
        return _CompletedProcess(returncode=0, stdout="not json")

    monkeypatch.setattr(onboard_flow.subprocess, "run", garbled_run)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.UNKNOWN


def test_dispatch_refuses_when_dedup_state_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Critical safety: an UNKNOWN dedup state must NOT dispatch.

    Treating unknown as inactive would spawn duplicate long-running sessions
    when the daemon is briefly unreachable. Fail closed.
    """
    dispatch_calls: list[list[str]] = []

    def watcher_run(cmd: list[str], *_args: object, **_kwargs: object) -> _CompletedProcess:
        if "list" in cmd and "sessions" in cmd:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        dispatch_calls.append(list(cmd))
        return _CompletedProcess(returncode=0)

    monkeypatch.setattr(onboard_flow.subprocess, "run", watcher_run)

    assert onboard_flow.run_analyze(tmp_path) is False
    assert dispatch_calls == [], "run_analyze must not dispatch on UNKNOWN dedup state"
