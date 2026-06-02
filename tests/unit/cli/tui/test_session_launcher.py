from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.api_models import CreateSessionResponseDTO
from teleclaude.cli.tui import session_launcher


@pytest.mark.unit
def test_attach_tmux_session_returns_false_without_session_name_or_tmux_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    stdscr = Mock()

    assert session_launcher.attach_tmux_session(None, stdscr) is False
    assert session_launcher.attach_tmux_session("tc_demo", stdscr) is False
    stdscr.refresh.assert_not_called()


@pytest.mark.unit
def test_attach_tmux_session_runs_split_window_and_restores_curses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "1")
    monkeypatch.setattr(session_launcher.config, "computer", SimpleNamespace(tmux_binary="tmux-bin"))
    def_prog_mode = Mock()
    endwin = Mock()
    reset_prog_mode = Mock()
    run = Mock()
    monkeypatch.setattr(session_launcher.curses, "def_prog_mode", def_prog_mode)
    monkeypatch.setattr(session_launcher.curses, "endwin", endwin)
    monkeypatch.setattr(session_launcher.curses, "reset_prog_mode", reset_prog_mode)
    monkeypatch.setattr(session_launcher.subprocess, "run", run)
    stdscr = Mock()

    attached = session_launcher.attach_tmux_session("tc_demo", stdscr)

    assert attached is True
    def_prog_mode.assert_called_once_with()
    endwin.assert_called_once_with()
    reset_prog_mode.assert_called_once_with()
    run.assert_called_once_with(
        ["tmux-bin", "split-window", "-h", "-p", "60", "tmux-bin attach -t tc_demo"],
        check=False,
    )
    stdscr.refresh.assert_called_once_with()


@pytest.mark.unit
def test_attach_tmux_from_result_requires_a_tmux_session_name(monkeypatch: pytest.MonkeyPatch) -> None:
    attach = Mock(return_value=True)
    monkeypatch.setattr(session_launcher, "attach_tmux_session", attach)
    stdscr = Mock()
    with_tmux = CreateSessionResponseDTO(status="success", session_id="s1", tmux_session_name="tc_demo")
    without_tmux = CreateSessionResponseDTO(status="success", session_id="s1", tmux_session_name="")

    assert session_launcher.attach_tmux_from_result(with_tmux, stdscr) is True
    assert session_launcher.attach_tmux_from_result(without_tmux, stdscr) is False
    attach.assert_called_once_with("tc_demo", stdscr, computer=None, cache=None)


@pytest.mark.unit
def test_attach_tmux_session_wraps_remote_peer_in_ssh(
    monkeypatch: pytest.MonkeyPatch, snapshot: SnapshotAssertion
) -> None:
    """The rendered split-window command is the cross-computer attach contract — snapshot it."""
    monkeypatch.setenv("TMUX", "1")
    monkeypatch.setattr(session_launcher.config, "computer", SimpleNamespace(name="MozMini", tmux_binary="local-tmux"))
    run = Mock()
    monkeypatch.setattr(session_launcher.curses, "def_prog_mode", Mock())
    monkeypatch.setattr(session_launcher.curses, "endwin", Mock())
    monkeypatch.setattr(session_launcher.curses, "reset_prog_mode", Mock())
    monkeypatch.setattr(session_launcher.subprocess, "run", run)
    stdscr = Mock()

    cache = Mock()
    cache.get_computers.return_value = [
        SimpleNamespace(
            name="MozBook",
            is_local=False,
            user="morriz",
            host="mozbook.local",
            tmux_binary="/opt/tmux",
        )
    ]

    attached = session_launcher.attach_tmux_session("tc_demo", stdscr, computer="MozBook", cache=cache)

    assert attached is True
    assert run.call_args.args[0] == snapshot


@pytest.mark.unit
def test_attach_tmux_session_remote_with_missing_identity_returns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remote attach must NOT silently fall back to local when peer identity hasn't propagated.

    Silent fallback would point the local tmux client at a session name that lives on a
    different machine — misleading-feedback regression. The attach must return False so
    the caller can render a status message and retry once the heartbeat catches up.
    """
    monkeypatch.setenv("TMUX", "1")
    monkeypatch.setattr(session_launcher.config, "computer", SimpleNamespace(name="MozMini", tmux_binary="local-tmux"))
    run = Mock()
    monkeypatch.setattr(session_launcher.curses, "def_prog_mode", Mock())
    monkeypatch.setattr(session_launcher.curses, "endwin", Mock())
    monkeypatch.setattr(session_launcher.curses, "reset_prog_mode", Mock())
    monkeypatch.setattr(session_launcher.subprocess, "run", run)
    stdscr = Mock()

    cache = Mock()
    cache.get_computers.return_value = [
        SimpleNamespace(name="MozBook", is_local=False, user=None, host=None, tmux_binary=None)
    ]

    attached = session_launcher.attach_tmux_session("tc_demo", stdscr, computer="MozBook", cache=cache)

    assert attached is False
    run.assert_not_called()
