"""Tests for teleclaude.project_setup.onboard_flow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

import pytest

import teleclaude.project_setup.onboard_flow as onboard_flow
from teleclaude.cli.tool_client import ToolAPIError


class _SessionEntry(TypedDict):
    """Shape of one session record as returned by the daemon's /sessions endpoint."""

    project_path: str
    title: str
    closed_at: str | None


class _DispatchBody(TypedDict, total=False):
    """Subset of RunSessionRequest fields the dispatcher writes."""

    command: str
    project: str
    args: str
    agent: str
    computer: str
    subfolder: str
    thinking_mode: str
    detach: bool
    additional_context: str


@dataclass(frozen=True)
class _RecordedCall:
    """One call recorded by the tool_api_request fake."""

    method: str
    path: str
    params: dict[str, str] | None = None
    json_body: _DispatchBody | None = None


@dataclass
class _Recorder:
    """Mutable list of recorded fake calls."""

    calls: list[_RecordedCall] = field(default_factory=list)


def _make_recorder(
    *,
    list_payload: list[_SessionEntry] | None = None,
    list_error: ToolAPIError | None = None,
    dispatch_error: ToolAPIError | None = None,
) -> tuple[_Recorder, Callable[..., object]]:
    """Build a fake tool_api_request that records every call.

    Distinguishes the dedup lookup (GET /sessions) from the dispatch
    (POST /sessions/run). Optional errors let tests drive each path.
    """
    recorder = _Recorder()

    def fake(
        method: str,
        path: str,
        json_body: _DispatchBody | None = None,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = timeout, socket_path
        recorder.calls.append(_RecordedCall(method=method, path=path, params=params, json_body=json_body))
        if method == "GET" and path == "/sessions":
            if list_error is not None:
                raise list_error
            return list(list_payload or [])
        if method == "POST" and path == "/sessions/run":
            if dispatch_error is not None:
                raise dispatch_error
            return {"status": "success", "session_id": "fake-session-id"}
        return None

    return recorder, fake


# ---------------------------------------------------------------------------
# run_analyze
# ---------------------------------------------------------------------------


def test_run_analyze_dispatches_projects_analyze_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder, fake = _make_recorder()
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    result = onboard_flow.run_analyze(tmp_path)

    assert result is True
    dispatch_calls = [c for c in recorder.calls if c.method == "POST" and c.path == "/sessions/run"]
    assert len(dispatch_calls) == 1
    body = dispatch_calls[0].json_body
    assert body is not None
    assert body["command"] == "/projects-analyze"
    assert body["project"] == str(tmp_path)


def test_run_analyze_dedup_lookup_queries_all_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: dedup must use all=true so cross-caller sessions are visible.

    Without ``all=true`` the daemon returns only sessions spawned by the
    current caller, so a parallel onboarding launched from another shell
    would slip past the dedup probe.
    """
    recorder, fake = _make_recorder()
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    onboard_flow.run_analyze(tmp_path)

    list_calls = [c for c in recorder.calls if c.method == "GET" and c.path == "/sessions"]
    assert len(list_calls) == 1
    params = list_calls[0].params
    assert params is not None and params.get("all") == "true"


def test_run_analyze_skips_when_active_session_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: list[_SessionEntry] = [
        {
            "project_path": str(tmp_path),
            "title": "/projects-analyze running",
            "closed_at": None,
        }
    ]
    recorder, fake = _make_recorder(list_payload=payload)
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    result = onboard_flow.run_analyze(tmp_path)

    assert result is False
    dispatch_calls = [c for c in recorder.calls if c.method == "POST" and c.path == "/sessions/run"]
    assert dispatch_calls == []


def test_run_analyze_returns_false_on_dispatch_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _recorder, fake = _make_recorder(dispatch_error=ToolAPIError("dispatch boom", status_code=500))
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    assert onboard_flow.run_analyze(tmp_path) is False


def test_run_analyze_returns_false_on_dispatch_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _recorder, fake = _make_recorder(dispatch_error=ToolAPIError("timed out", is_timeout=True))
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    assert onboard_flow.run_analyze(tmp_path) is False


# ---------------------------------------------------------------------------
# run_assess
# ---------------------------------------------------------------------------


def test_run_assess_dispatches_projects_assess_config_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder, fake = _make_recorder()
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    result = onboard_flow.run_assess(tmp_path)

    assert result is True
    dispatch_calls = [c for c in recorder.calls if c.method == "POST" and c.path == "/sessions/run"]
    assert len(dispatch_calls) == 1
    body = dispatch_calls[0].json_body
    assert body is not None
    assert body["command"] == "/projects-assess-config"


def test_run_assess_skips_when_active_session_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: list[_SessionEntry] = [
        {
            "project_path": str(tmp_path),
            "title": "/projects-assess-config xxx",
            "closed_at": None,
        }
    ]
    recorder, fake = _make_recorder(list_payload=payload)
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    result = onboard_flow.run_assess(tmp_path)

    assert result is False
    dispatch_calls = [c for c in recorder.calls if c.method == "POST" and c.path == "/sessions/run"]
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
    _recorder, fake = _make_recorder(list_payload=payload)
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.ACTIVE


def test_active_session_for_command_ignores_closed_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: list[_SessionEntry] = [
        {
            "project_path": str(tmp_path),
            "title": "/projects-analyze finished",
            "closed_at": "2025-01-01T00:00:00Z",
        }
    ]
    _recorder, fake = _make_recorder(list_payload=payload)
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.INACTIVE


def test_active_session_for_command_ignores_different_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: list[_SessionEntry] = [
        {
            "project_path": "/some/other/project",
            "title": "/projects-analyze running",
            "closed_at": None,
        }
    ]
    _recorder, fake = _make_recorder(list_payload=payload)
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.INACTIVE


def test_active_session_for_command_returns_unknown_on_transport_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daemon unreachability must surface as UNKNOWN so callers fail closed."""
    _recorder, fake = _make_recorder(list_error=ToolAPIError("daemon is not running"))
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.UNKNOWN


def test_active_session_for_command_returns_unknown_on_unexpected_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-list payload must surface as UNKNOWN — never as INACTIVE."""

    def fake(method: str, path: str, **_kwargs: object) -> object:
        _ = method, path
        return {"unexpected": "shape"}

    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    assert onboard_flow._active_session_for_command(tmp_path, "/projects-analyze") is onboard_flow.DedupState.UNKNOWN


def test_dispatch_refuses_when_dedup_state_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Critical safety: an UNKNOWN dedup state must NOT dispatch.

    Treating unknown as inactive would spawn duplicate long-running sessions
    when the daemon is briefly unreachable. Fail closed.
    """
    recorder, fake = _make_recorder(list_error=ToolAPIError("daemon is not running"))
    monkeypatch.setattr(onboard_flow, "tool_api_request", fake)

    assert onboard_flow.run_analyze(tmp_path) is False

    dispatch_calls = [c for c in recorder.calls if c.method == "POST" and c.path == "/sessions/run"]
    assert dispatch_calls == [], "run_analyze must not dispatch on UNKNOWN dedup state"
