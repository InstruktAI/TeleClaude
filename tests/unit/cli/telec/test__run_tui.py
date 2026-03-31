from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

run_tui = importlib.import_module("teleclaude.cli.telec._run_tui")


@dataclass
class AppInit:
    api: object | None = None
    start_view: int = 0
    config_guided: bool = False


def test_run_tui_cleans_up_session_when_app_exits_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = SimpleNamespace(trace=MagicMock(), exception=MagicMock())
    helper_calls: list[str] = []
    created = AppInit()

    class FakeTelecAPIClient:
        pass

    class FakeTelecApp:
        def __init__(self, api: object, *, start_view: int, config_guided: bool) -> None:
            created.api = api
            created.start_view = start_view
            created.config_guided = config_guided

        def run(self) -> int:
            return 0

    monkeypatch.setattr(run_tui.os, "execvp", MagicMock())
    monkeypatch.delenv("TELEC_RELOAD", raising=False)

    with patch.dict(
        sys.modules,
        {
            "instrukt_ai_logging": SimpleNamespace(get_logger=lambda _name: logger),
            "teleclaude.cli.api_client": SimpleNamespace(TelecAPIClient=FakeTelecAPIClient),
            "teleclaude.cli.telec.handlers.misc": SimpleNamespace(
                _ensure_tmux_mouse_on=lambda: helper_calls.append("mouse"),
                _ensure_tmux_status_hidden_for_tui=lambda: helper_calls.append("status"),
                _maybe_kill_tui_session=lambda: helper_calls.append("kill"),
            ),
            "teleclaude.cli.tui.app": SimpleNamespace(RELOAD_EXIT=99, TelecApp=FakeTelecApp),
        },
    ):
        run_tui._run_tui(start_view=3, config_guided=True)

    assert created.start_view == 3
    assert created.config_guided is True
    assert helper_calls == ["status", "mouse", "kill"]
    run_tui.os.execvp.assert_not_called()
    assert "TELEC_RELOAD" not in os.environ


def test_run_tui_reexecs_python_module_on_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = SimpleNamespace(trace=MagicMock(), exception=MagicMock())
    execvp = MagicMock()

    class FakeTelecApp:
        def __init__(self, _api: object, *, start_view: int, config_guided: bool) -> None:
            assert start_view == 2
            assert config_guided is False

        def run(self) -> int:
            return 99

    monkeypatch.setattr(run_tui.os, "execvp", execvp)
    monkeypatch.setattr(run_tui, "_resolve_reload_exec_argv", lambda: ("/tmp/telec", ["/tmp/telec"]))
    monkeypatch.delenv("TELEC_RELOAD", raising=False)

    with patch.dict(
        sys.modules,
        {
            "instrukt_ai_logging": SimpleNamespace(get_logger=lambda _name: logger),
            "teleclaude.cli.api_client": SimpleNamespace(TelecAPIClient=object),
            "teleclaude.cli.telec.handlers.misc": SimpleNamespace(
                _ensure_tmux_mouse_on=lambda: None,
                _ensure_tmux_status_hidden_for_tui=lambda: None,
                _maybe_kill_tui_session=lambda: (_ for _ in ()).throw(AssertionError("cleanup should be skipped")),
            ),
            "teleclaude.cli.tui.app": SimpleNamespace(RELOAD_EXIT=99, TelecApp=FakeTelecApp),
        },
    ):
        run_tui._run_tui(start_view=2)

    execvp.assert_called_once_with("/tmp/telec", ["/tmp/telec"])
    assert os.environ["TELEC_RELOAD"] == "1"


def test_resolve_reload_exec_argv_prefers_current_console_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_tui.sys, "argv", ["/tmp/telec"])
    monkeypatch.setattr(run_tui.os.path, "isabs", lambda value: value == "/tmp/telec")
    monkeypatch.setattr(run_tui.os.path, "basename", lambda value: "telec" if value == "/tmp/telec" else "")
    monkeypatch.setattr(run_tui.os, "access", lambda value, mode: value == "/tmp/telec")
    monkeypatch.setattr(run_tui.shutil, "which", lambda name: "/other/telec" if name == "telec" else None)

    executable, argv = run_tui._resolve_reload_exec_argv()

    assert executable == "/tmp/telec"
    assert argv == ["/tmp/telec"]


def test_resolve_reload_exec_argv_falls_back_to_module_when_console_script_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_tui.sys, "argv", ["telec"])
    monkeypatch.setattr(run_tui.os.path, "isabs", lambda _value: False)
    monkeypatch.setattr(run_tui.shutil, "which", lambda _name: None)
    monkeypatch.setattr(run_tui.sys, "executable", "/tmp/python")

    executable, argv = run_tui._resolve_reload_exec_argv()

    assert executable == "/tmp/python"
    assert argv == ["/tmp/python", "-m", "teleclaude.cli.telec"]


def test_run_tui_config_mode_uses_config_view() -> None:
    forwarded: list[tuple[int, bool]] = []

    with patch.object(
        run_tui, "_run_tui", side_effect=lambda start_view, config_guided: forwarded.append((start_view, config_guided))
    ):
        run_tui._run_tui_config_mode(guided=True)

    assert forwarded == [(4, True)]
