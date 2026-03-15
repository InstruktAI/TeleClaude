from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

misc = importlib.import_module("teleclaude.cli.telec.handlers.misc")


def test_git_short_commit_hash_returns_unknown_on_git_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(misc.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""))

    assert misc._git_short_commit_hash() == "unknown"


def test_handle_sync_forwards_warn_and_validate_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, bool, bool]] = []

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            importlib.import_module("sys").modules,
            "teleclaude.sync",
            SimpleNamespace(
                sync=lambda project_root, *, validate_only, warn_only: (
                    calls.append((project_root, validate_only, warn_only)) or True
                )
            ),
        )
        monkeypatch.chdir("/tmp")
        misc._handle_sync(["--warn-only", "--validate-only"])

    assert calls and calls[0][1:] == (True, True)


def test_handle_revive_parses_attach_and_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool, str | None]] = []

    monkeypatch.setattr(
        misc, "_revive_session", lambda session_id, attach, *, agent=None: calls.append((session_id, attach, agent))
    )

    misc._handle_revive(["sess-1", "--attach", "--agent", "codex"])

    assert calls == [("sess-1", True, "codex")]


def test_revive_session_prints_success_and_attaches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    attached = MagicMock()

    async def fake_revive(_session_id: str, *, agent: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(status="success", session_id="sess-1", error=None, tmux_session_name="tmux-1")

    async def fake_send(_session_id: str) -> bool:
        return True

    monkeypatch.setattr(misc, "_revive_session_via_api", fake_revive)
    monkeypatch.setattr(misc, "_send_revive_enter_via_api", fake_send)
    monkeypatch.setattr(misc, "_attach_tmux_session", attached)

    misc._revive_session("sess-1", True)

    attached.assert_called_once_with("tmux-1")
    assert "Revived session sess-1" in capsys.readouterr().out


def test_maybe_kill_tui_session_kills_matching_tmux_session(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setenv(misc.TUI_ENV_KEY, misc.ENV_ENABLE)
    monkeypatch.setenv(misc.TMUX_ENV_KEY, "1")
    monkeypatch.setattr(misc.config.computer, "tmux_binary", "tmux")

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(args)
        if args[:3] == ["tmux", "display-message", "-p"]:
            return SimpleNamespace(stdout="tc_tui\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(misc.subprocess, "run", fake_run)

    misc._maybe_kill_tui_session()

    assert calls[-1] == ["tmux", "kill-session", "-t", misc.TUI_SESSION_NAME]
