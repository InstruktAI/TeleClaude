"""Regression coverage for launchd-owned macOS tmux server startup."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from teleclaude.project_setup import macos_setup


@pytest.mark.functional
@pytest.mark.spec("project/procedure/init-extensions", "UC-INIT-EXT-2A")
def test_tmux_server_service_is_foreground_cwd_stable_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teleclaude_home = tmp_path / ".teleclaude"
    wrapper = tmp_path / "Applications" / "TmuxLauncher.app" / "Contents" / "MacOS" / "tmux-launcher"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("launcher", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(macos_setup, "is_macos", lambda: True)
    monkeypatch.setattr(macos_setup.subprocess, "run", fake_run)

    args = {"home": tmp_path, "teleclaude_home": teleclaude_home, "launchctl": "launchctl"}
    macos_setup.install_tmux_server_service(**args)

    plist_path = tmp_path / "Library" / "LaunchAgents" / "ai.instrukt.tmux-server.plist"
    payload = plistlib.loads(plist_path.read_bytes())
    assert payload["ProgramArguments"] == [str(wrapper), "--teleclaude-server"]
    assert payload["WorkingDirectory"] == str(teleclaude_home)
    assert payload["KeepAlive"] is True
    assert payload["RunAtLoad"] is True
    assert calls == [
        ["launchctl", "print", f"gui/{os.getuid()}/ai.instrukt.tmux-server"],
        ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)],
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
    ]

    calls.clear()
    macos_setup.install_tmux_server_service(**args)
    assert calls == [["launchctl", "print", f"gui/{os.getuid()}/ai.instrukt.tmux-server"]]


@pytest.mark.functional
@pytest.mark.spec("project/spec/feature/agent_runtime/tmux-pane-orchestration", "UC-TPO2")
@pytest.mark.skipif(sys.platform != "darwin", reason="TmuxLauncher is a macOS app binary")
@pytest.mark.parametrize(
    ("launcher_args", "expected_args"),
    [
        (("list-sessions",), ["-N", "list-sessions"]),
        (("--teleclaude-server",), ["-D"]),
    ],
)
def test_tmux_launcher_separates_client_and_server_modes(
    tmp_path: Path,
    launcher_args: tuple[str, ...],
    expected_args: list[str],
) -> None:
    fake_tmux = tmp_path / "tmux"
    fake_tmux.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_tmux.chmod(0o755)
    launcher = Path(__file__).resolve().parents[2] / "bin" / "TmuxLauncher.app" / "Contents" / "MacOS" / "tmux-launcher"

    result = subprocess.run(
        [str(launcher), *launcher_args],
        env={**os.environ, "TMUX_LAUNCHER_TARGET": str(fake_tmux)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == expected_args
