from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

config_handler = importlib.import_module("teleclaude.cli.telec.handlers.config")


def test_handle_config_without_args_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config_handler, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    config_handler._handle_config([])

    assert capsys.readouterr().out == "usage:config\n"


def test_handle_config_wizard_requires_tty(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(config_handler.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        config_handler._handle_config(["wizard"])

    assert exc_info.value.code == 1
    assert "Interactive config requires a terminal." in capsys.readouterr().out


def test_handle_config_wizard_runs_guided_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    monkeypatch.setattr(config_handler.sys.stdin, "isatty", lambda: True)

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.cli.telec._run_tui",
            SimpleNamespace(_run_tui_config_mode=lambda guided: called.append(guided)),
        )
        config_handler._handle_config(["wizard"])

    assert called == [True]


def test_handle_config_get_delegates_to_config_command() -> None:
    received: list[list[str]] = []

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.cli.config_cmd",
            SimpleNamespace(handle_config_command=lambda args: received.append(args)),
        )
        config_handler._handle_config(["get", "deployment.channel"])

    assert received == [["get", "deployment.channel"]]
