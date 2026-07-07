"""TUI pane theming resilience against a client-less tmux server.

Drives the real ``PaneThemingMixin._set_tui_pane_background`` against a live
tmux server on an isolated socket (``-L``) that has no client ever attached —
decoupled from the ambient default-socket state so the scenario reproduces
deterministically regardless of whether the host machine happens to have an
attached tmux client elsewhere. Only the tmux process boundary is a seam; the
theming mixin itself is real and unmocked.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Generator

import pytest

from teleclaude.cli.tui._pane_specs import PaneState
from teleclaude.cli.tui.pane_manager import TmuxPaneManager, _PaneLayoutState

pytestmark = pytest.mark.process

# Upper bound on any single tmux invocation; a hung command fails fast well
# within the process tier's relaxed budget rather than blocking the stage.
_TMUX_TIMEOUT_S = 15


class _ClientlessThemingHarness(TmuxPaneManager):
    """Live-tmux harness on an isolated, permanently client-less server."""

    def __init__(self, tmux_binary: str, socket_name: str) -> None:
        self.tmux_binary = tmux_binary
        self.socket_name = socket_name
        self._in_tmux = True
        self._layout_state = _PaneLayoutState()
        self.state = PaneState()
        self._tui_pane_id = self._first_pane_id()

    def _run_tmux(self, *args: str) -> str:
        result = subprocess.run(
            [self.tmux_binary, "-L", self.socket_name, *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=_TMUX_TIMEOUT_S,
        )
        return result.stdout.strip()

    def _get_pane_exists(self, pane_id: str) -> bool:
        return pane_id in self._run_tmux("list-panes", "-a", "-F", "#{pane_id}").splitlines()

    def _first_pane_id(self) -> str:
        return self._run_tmux("list-panes", "-a", "-F", "#{pane_id}").splitlines()[0]


@pytest.fixture
def clientless_harness() -> Generator[_ClientlessThemingHarness, None, None]:
    tmux_binary = shutil.which("tmux")
    if tmux_binary is None:
        pytest.skip("tmux is unavailable")
    socket_name = f"tc-clientless-{os.getpid()}"
    session_name = f"tc-clientless-session-{os.getpid()}"
    subprocess.run(
        [tmux_binary, "-L", socket_name, "new-session", "-d", "-s", session_name, "sleep 60"],
        check=True,
        timeout=_TMUX_TIMEOUT_S,
    )
    try:
        yield _ClientlessThemingHarness(tmux_binary, socket_name)
    finally:
        subprocess.run(
            [tmux_binary, "-L", socket_name, "kill-server"],
            check=False,
            timeout=_TMUX_TIMEOUT_S,
        )


@pytest.mark.spec("project/spec/feature/tui/pane-theming", "UC-PTHEME-1")
def test_tui_pane_theming_completes_when_no_client_is_attached(
    clientless_harness: _ClientlessThemingHarness,
) -> None:
    harness = clientless_harness

    # Precondition: the isolated server has no attached client (F1's failure
    # condition), independent of any client attached elsewhere on the host.
    assert not harness._run_tmux("list-clients")

    harness._set_tui_pane_background()  # must complete without raising

    window_style = harness._run_tmux("show-options", "-p", "-t", harness._tui_pane_id, "-v", "window-style")
    border_style = harness._run_tmux("show-options", "-w", "-t", harness._tui_pane_id, "-v", "pane-border-style")
    assert window_style
    assert border_style
