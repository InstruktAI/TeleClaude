"""Functional bindings for the `telec sessions start`/`run` --path flag rename.

Drives the real CLI handlers, asserting at the API-request boundary that
`--path` populates the historical per-endpoint wire field (`project_path` for
`start`, `project` for `run`) and that a stale `--project` now fails loudly —
non-zero exit, no API call — instead of silently falling through to cwd.

The CLI layer never inspects the `--path` value for git-ness or a
`teleclaude.yml`; GIT-only resolution lives server-side in
`teleclaude.project_root.resolve_project_root`, which this file's mocked
`tool_api_call` boundary never invokes. That resolution is unaffected by the
rename (the CLI passed the raw string through before and still does) and is
out of scope here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.tool_commands import sessions as sessions_tool

pytestmark = pytest.mark.functional

ApiCall = tuple[str, str, dict[str, str] | None, object | None]

_COMPUTER = "remote-box"


@pytest.fixture
def api_calls(monkeypatch: pytest.MonkeyPatch) -> list[ApiCall]:
    calls: list[ApiCall] = []

    def tool_api_call(
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: object | None = None,
    ) -> dict[str, str]:
        calls.append((method, path, params, json_body))
        return {"status": "ok"}

    monkeypatch.setattr(sessions_tool, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions_tool, "print_json", lambda data: None)
    return calls


def test_sessions_start_path_flag_populates_project_path(api_calls: list[ApiCall], tmp_path: Path) -> None:
    target = tmp_path / "some-repo"
    target.mkdir()

    sessions_tool.handle_sessions_start(["--path", str(target)])

    assert len(api_calls) == 1
    method, path, _params, body = api_calls[0]
    assert (method, path) == ("POST", "/sessions")
    assert isinstance(body, dict)
    assert Path(body["project_path"]) == target


def test_sessions_start_path_equals_form_populates_project_path(api_calls: list[ApiCall], tmp_path: Path) -> None:
    target = tmp_path / "some-repo"
    target.mkdir()

    sessions_tool.handle_sessions_start([f"--path={target}"])

    assert len(api_calls) == 1
    _method, _path, _params, body = api_calls[0]
    assert isinstance(body, dict)
    assert Path(body["project_path"]) == target


def test_sessions_run_path_flag_populates_project(api_calls: list[ApiCall], tmp_path: Path) -> None:
    target = tmp_path / "some-repo"
    target.mkdir()

    sessions_tool.handle_sessions_run(["--command", "/next-build", "--path", str(target)])

    assert len(api_calls) == 1
    method, path, _params, body = api_calls[0]
    assert (method, path) == ("POST", "/sessions/run")
    assert isinstance(body, dict)
    assert Path(body["project"]) == target


def test_sessions_run_path_equals_form_populates_project(api_calls: list[ApiCall], tmp_path: Path) -> None:
    target = tmp_path / "some-repo"
    target.mkdir()

    sessions_tool.handle_sessions_run(["--command", "/next-build", f"--path={target}"])

    assert len(api_calls) == 1
    _method, _path, _params, body = api_calls[0]
    assert isinstance(body, dict)
    assert Path(body["project"]) == target


def test_sessions_start_stale_project_flag_exits_nonzero_without_api_call(
    api_calls: list[ApiCall], capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        sessions_tool.handle_sessions_start(["--project", "/tmp/somewhere"])

    assert excinfo.value.code != 0
    assert api_calls == []
    assert capsys.readouterr().err == snapshot


def test_sessions_run_stale_project_flag_exits_nonzero_without_api_call(
    api_calls: list[ApiCall], capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        sessions_tool.handle_sessions_run(["--command", "/next-build", "--project", "/tmp/somewhere"])

    assert excinfo.value.code != 0
    assert api_calls == []
    assert capsys.readouterr().err == snapshot


def test_sessions_start_computer_and_default_cwd_unchanged(
    api_calls: list[ApiCall], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sessions_tool, "resolve_invocation_cwd", lambda: tmp_path)

    sessions_tool.handle_sessions_start(["--computer", _COMPUTER])

    _method, _path, _params, body = api_calls[0]
    assert isinstance(body, dict)
    assert body["computer"] == _COMPUTER
    assert Path(body["project_path"]) == tmp_path


def test_sessions_run_computer_and_default_cwd_unchanged(
    api_calls: list[ApiCall], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sessions_tool, "resolve_invocation_cwd", lambda: tmp_path)

    sessions_tool.handle_sessions_run(["--command", "/next-build", "--computer", _COMPUTER])

    _method, _path, _params, body = api_calls[0]
    assert isinstance(body, dict)
    assert body["computer"] == _COMPUTER
    assert Path(body["project"]) == tmp_path
