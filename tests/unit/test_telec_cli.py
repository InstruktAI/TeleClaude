"""Tests for telec CLI session-management behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, TypedDict

import pytest

from teleclaude.cli import telec
from teleclaude.cli.api_client import APIError
from teleclaude.cli.models import CreateSessionResult


class _CreateSessionCall(TypedDict, total=False):
    skip_listener_registration: bool


def test_attach_tmux_session_switches_inside_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, Any] = {}

    def fake_run(args: list[str], check: bool = False) -> None:  # noqa: ARG001 - signature match
        called["args"] = args

    monkeypatch.setenv("TMUX", "1")
    monkeypatch.setattr(telec.subprocess, "run", fake_run)

    telec._attach_tmux_session("tc_999")

    assert called["args"][:2] == [telec.config.computer.tmux_binary, "switch-client"]


def test_attach_tmux_session_attaches_outside_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, tuple[str, ...]] = {}

    def fake_execlp(*args: str) -> None:
        called["args"] = args

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr(telec.os, "execlp", fake_execlp)

    telec._attach_tmux_session("tc_888")

    assert called["args"][1:] == (telec.config.computer.tmux_binary, "attach-session", "-t", "tc_888")


def test_main_bridges_terminal_login_into_tui_tmux_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: Dict[str, tuple[str, ...]] = {}

    class _HasSessionMissing:
        returncode = 1

    def _fake_run(*_args, **_kwargs):
        return _HasSessionMissing()

    def _fake_execlp(*args: str) -> None:
        captured["args"] = args
        raise SystemExit(0)

    monkeypatch.setattr(telec, "config", SimpleNamespace(computer=SimpleNamespace(tmux_binary="tmux")))
    monkeypatch.setattr(telec, "setup_logging", lambda: None)
    monkeypatch.setattr(telec, "read_current_session_email", lambda: "admin@example.com")
    monkeypatch.setattr(telec.subprocess, "run", _fake_run)
    monkeypatch.setattr(telec.os, "execlp", _fake_execlp)
    monkeypatch.setattr(telec.sys, "argv", ["telec"])
    monkeypatch.delenv("TMUX", raising=False)

    with pytest.raises(SystemExit):
        telec.main()

    args = captured["args"]
    assert "-e" in args
    assert "TELEC_AUTH_EMAIL=admin@example.com" in args


def test_main_requires_login_for_multi_user_tui(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(telec, "setup_logging", lambda: None)
    monkeypatch.setattr(telec, "_requires_tui_login", lambda: True)
    monkeypatch.setattr(telec, "read_current_session_email", lambda: None)
    monkeypatch.setattr(telec.sys, "argv", ["telec"])
    monkeypatch.delenv("TMUX", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        telec.main()

    assert excinfo.value.code == 1
    output = capsys.readouterr().out
    assert "telec auth login is required" in output


def test_revive_session_attaches_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, str] = {}

    async def fake_revive(_session_id: str) -> CreateSessionResult:
        return CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_revived", agent="codex")

    async def fake_kick(_session_id: str) -> bool:
        called["kick"] = "1"
        return True

    def fake_attach(name: str) -> None:
        called["name"] = name

    monkeypatch.setattr(telec, "_revive_session_via_api", fake_revive)
    monkeypatch.setattr(telec, "_send_revive_enter_via_api", fake_kick)
    monkeypatch.setattr(telec, "_attach_tmux_session", fake_attach)

    telec._revive_session("sess-1", attach=True)

    assert called["kick"] == "1"
    assert called["name"] == "tc_revived"


def test_revive_session_does_not_attach_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, str] = {}

    async def fake_revive(_session_id: str) -> CreateSessionResult:
        return CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_revived", agent="codex")

    async def fake_kick(_session_id: str) -> bool:
        called["kick"] = "1"
        return True

    def fake_attach(name: str) -> None:
        called["name"] = name

    monkeypatch.setattr(telec, "_revive_session_via_api", fake_revive)
    monkeypatch.setattr(telec, "_send_revive_enter_via_api", fake_kick)
    monkeypatch.setattr(telec, "_attach_tmux_session", fake_attach)

    telec._revive_session("sess-1", attach=False)

    assert called["kick"] == "1"
    assert "name" not in called


def test_revive_session_warns_when_kick_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_revive(_session_id: str) -> CreateSessionResult:
        return CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_revived", agent="codex")

    async def fake_kick(_session_id: str) -> bool:
        raise APIError("kick failed")

    monkeypatch.setattr(telec, "_revive_session_via_api", fake_revive)
    monkeypatch.setattr(telec, "_send_revive_enter_via_api", fake_kick)

    telec._revive_session("sess-1", attach=False)

    out = capsys.readouterr().out
    assert "Revived session sess-1" in out
    assert "Warning: revive kick failed: kick failed" in out


def test_sessions_revive_routes_to_revive_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, Any] = {}

    def fake_handle_revive(args: list[str]) -> None:
        called["args"] = args

    monkeypatch.setattr(telec, "_handle_revive", fake_handle_revive)

    telec._handle_cli_command(["sessions", "revive", "sess-123", "--attach"])

    assert called["args"] == ["sess-123", "--attach"]


def test_top_level_revive_is_not_supported(capsys: pytest.CaptureFixture[str]) -> None:
    telec._handle_cli_command(["revive", "sess-456"])
    output = capsys.readouterr().out
    assert "Unknown command: /revive" in output


def test_namespace_commands_require_explicit_subcommand(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Parent commands must not execute behavior when invoked without a subcommand."""

    standalone_namespaces = [name for name, cmd in telec.CLI_SURFACE.items() if cmd.subcommands and cmd.standalone]
    assert standalone_namespaces == []

    def _forbid(_args: list[str]) -> None:
        raise AssertionError("Implicit parent execution is forbidden")

    monkeypatch.setattr(telec, "handle_sessions", _forbid)
    monkeypatch.setattr(telec, "handle_computers", _forbid)
    monkeypatch.setattr(telec, "handle_projects", _forbid)
    monkeypatch.setattr(telec, "handle_agents", _forbid)
    monkeypatch.setattr(telec, "handle_channels", _forbid)

    def _forbid_wizard(guided: bool = False) -> None:  # noqa: ARG001 - signature match
        _forbid([])

    monkeypatch.setattr(telec, "_run_tui_config_mode", _forbid_wizard)

    namespace_commands = [name for name, cmd in telec.CLI_SURFACE.items() if cmd.subcommands and not cmd.standalone]
    for command in namespace_commands:
        telec._handle_cli_command([command])
        output = capsys.readouterr().out
        assert "Usage:" in output
        assert f"telec {command}" in output


def test_help_expands_config_second_level_actions() -> None:
    output = telec._usage()
    assert "telec config people list" in output
    assert "telec config people add" in output
    assert "telec config people edit" in output
    assert "telec config people remove" in output
    assert "telec config env list" in output
    assert "telec config env set" in output


def test_help_includes_notes_and_examples_for_all_subcommands() -> None:
    for cmd_name, cmd in telec.CLI_SURFACE.items():
        if not cmd.subcommands:
            continue
        for sub_name in cmd.subcommands:
            output = telec._usage(cmd_name, sub_name)
            assert "\nNotes:\n" in output
            assert "\nExamples:\n" in output


def test_help_includes_notes_and_examples_for_top_level_leaf_commands() -> None:
    for cmd_name, cmd in telec.CLI_SURFACE.items():
        if cmd.subcommands:
            continue
        output = telec._usage(cmd_name)
        assert "\nNotes:\n" in output
        assert "\nExamples:\n" in output


def test_version_command_prints_version_channel_and_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Result:
        returncode = 0
        stdout = "ea8cc35\n"

    def fake_run(args: list[str], capture_output: bool, text: bool, check: bool) -> _Result:
        assert args == ["git", "rev-parse", "--short", "HEAD"]
        assert capture_output is True
        assert text is True
        assert check is False
        return _Result()

    monkeypatch.setattr(telec, "__version__", "1.0.0")
    monkeypatch.setattr(telec.subprocess, "run", fake_run)

    telec._handle_cli_command(["version"])

    output = capsys.readouterr().out.strip()
    assert output == "TeleClaude v1.0.0 (channel: alpha, commit: ea8cc35)"


def test_version_command_uses_unknown_commit_when_git_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(args: list[str], capture_output: bool, text: bool, check: bool) -> None:
        _ = (args, capture_output, text, check)
        raise OSError("git not found")

    monkeypatch.setattr(telec, "__version__", "1.0.0")
    monkeypatch.setattr(telec.subprocess, "run", fake_run)

    telec._handle_cli_command(["version"])

    output = capsys.readouterr().out.strip()
    assert output == "TeleClaude v1.0.0 (channel: alpha, commit: unknown)"


def test_bugs_report_dispatch_skips_listener_registration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """bugs report should offload without registering caller listener notifications."""
    create_calls: list[_CreateSessionCall] = []

    class _FakeApiClient:
        async def connect(self) -> None:
            return None

        async def create_session(self, **kwargs: object) -> CreateSessionResult:
            call: _CreateSessionCall = {}
            skip_listener_registration = kwargs.get("skip_listener_registration")
            if isinstance(skip_listener_registration, bool):
                call["skip_listener_registration"] = skip_listener_registration
            create_calls.append(call)
            return CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_1", agent=None)

        async def close(self) -> None:
            return None

    def _fake_git_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(telec, "TelecAPIClient", _FakeApiClient)
    monkeypatch.setattr(telec.subprocess, "run", _fake_git_run)
    monkeypatch.chdir(tmp_path)

    slug = "fix-bugs-report-skip-listener"
    telec._handle_bugs_report(
        [
            "listener spam on bugs report",
            "--slug",
            slug,
        ]
    )

    assert create_calls, "Expected telec bugs report to dispatch an orchestrator session"
    assert create_calls[0].get("skip_listener_registration") is True


def test_bugs_list_uses_worktree_state_for_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """bugs list and roadmap list should agree on worktree-owned build status."""
    project_root = tmp_path
    slug = "fix-bug"

    todos_dir = project_root / "todos"
    todo_dir = todos_dir / slug
    todo_dir.mkdir(parents=True)
    (todos_dir / "roadmap.yaml").write_text(f"- slug: {slug}\n", encoding="utf-8")
    (todo_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
    (todo_dir / "state.yaml").write_text("build: pending\nreview: pending\n", encoding="utf-8")

    worktree_todo = project_root / "trees" / slug / "todos" / slug
    worktree_todo.mkdir(parents=True, exist_ok=True)
    (worktree_todo / "state.yaml").write_text("build: started\nreview: pending\n", encoding="utf-8")

    monkeypatch.chdir(project_root)

    telec._handle_roadmap(["list"])
    roadmap_output = capsys.readouterr().out
    assert "Build:started" in roadmap_output

    telec._handle_bugs(["list"])
    bugs_output = capsys.readouterr().out
    bug_lines = [line for line in bugs_output.splitlines() if slug in line]
    assert bug_lines
    assert any("building" in line for line in bug_lines)
