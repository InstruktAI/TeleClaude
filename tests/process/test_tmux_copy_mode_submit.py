"""Process-tier regression coverage for tmux copy-mode input submission."""

from __future__ import annotations

import asyncio
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

from teleclaude.config import config
from teleclaude.core.tmux_bridge import send_keys_existing_tmux

pytestmark = [pytest.mark.process, pytest.mark.asyncio]

_TMUX_TIMEOUT_S = 15
_MARKER_TIMEOUT_S = 2
_SPEC = "project/spec/feature/agent_runtime/tmux-pane-orchestration"


class _TmuxHarness:
    """Own an isolated real tmux server for a send-keys behavior test."""

    def __init__(self, tmux_binary: str, session_name: str) -> None:
        self.tmux_binary = tmux_binary
        self.session_name = session_name

    def run(self, *args: str, check: bool = True) -> str:
        # tmux exposes server and copy-mode control only through its CLI; the
        # real client is the boundary this process test must exercise.
        result = subprocess.run(
            [self.tmux_binary, *args],
            capture_output=True,
            check=check,
            text=True,
            timeout=_TMUX_TIMEOUT_S,
        )
        return result.stdout.strip()

    def pane_is_in_mode(self) -> bool:
        mode_count = self.run("display-message", "-p", "-t", self.session_name, "#{pane_in_mode}")
        return int(mode_count) > 0


@pytest.fixture
def tmux_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[_TmuxHarness, None, None]:
    real_tmux = shutil.which("tmux")
    if real_tmux is None:
        pytest.skip("tmux is unavailable")

    socket_root = Path(tempfile.mkdtemp(prefix="telec-tmux-", dir="/tmp"))
    monkeypatch.setattr(config.computer, "tmux_binary", real_tmux)
    monkeypatch.setenv("TMUX_TMPDIR", str(socket_root))
    monkeypatch.delenv("TMUX", raising=False)
    harness = _TmuxHarness(real_tmux, f"tc-copy-mode-{uuid4().hex}")
    harness.run("new-session", "-d", "-s", harness.session_name, "sh")
    try:
        yield harness
    finally:
        harness.run("kill-server", check=False)
        shutil.rmtree(socket_root)


async def _wait_for_marker(marker_path: Path) -> None:
    deadline = time.monotonic() + _MARKER_TIMEOUT_S
    while not marker_path.exists():
        if time.monotonic() >= deadline:
            pytest.fail("tmux did not submit the marker command before the deadline")
        await asyncio.sleep(0.05)


@pytest.mark.process
@pytest.mark.spec(_SPEC, "UC-TPO2")
async def test_send_keys_submits_into_a_copy_mode_pane(
    tmux_harness: _TmuxHarness,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "copy-mode-submitted"
    tmux_harness.run("copy-mode", "-t", tmux_harness.session_name)
    assert tmux_harness.pane_is_in_mode()

    submitted = await send_keys_existing_tmux(
        tmux_harness.session_name,
        f"touch {shlex.quote(str(marker_path))}",
    )

    assert submitted is True
    await _wait_for_marker(marker_path)
    assert marker_path.is_file()


@pytest.mark.process
@pytest.mark.spec(_SPEC, "UC-TPO2")
async def test_send_keys_submits_into_a_live_pane(
    tmux_harness: _TmuxHarness,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "live-pane-submitted"
    assert not tmux_harness.pane_is_in_mode()

    submitted = await send_keys_existing_tmux(
        tmux_harness.session_name,
        f"touch {shlex.quote(str(marker_path))}",
    )

    assert submitted is True
    await _wait_for_marker(marker_path)
    assert marker_path.is_file()
