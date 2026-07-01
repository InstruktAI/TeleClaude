"""Remote-pane theming and swap resilience, driven through apply_layout.

These tests enter the real layout entry point ``TmuxPaneManager.apply_layout``
against a live tmux server with the theming mixin left real (unstubbed). The
only seam is the tmux process boundary (``_run_tmux``), which is captured and,
for the resilience test, fault-injected. Behavior is observed at the emitted
tmux command boundary and via real pane geometry.

They drive real OS subprocesses (tmux) against wall-clock deadlines, so they run
in the serial ``process`` tier (``make test-meta`` / ``tests/process/``), never
the fast ``-n auto`` suite where tmux-server contention starves the per-test
timeout. Every subprocess call is bounded so a hung tmux fails fast.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Generator
from dataclasses import dataclass

import pytest

from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui._pane_specs import ComputerInfo, PaneState
from teleclaude.cli.tui.pane_manager import TmuxPaneManager, _PaneLayoutState

pytestmark = pytest.mark.process

_REMOTE_COMPUTER = "remotehost"

# Upper bound on any single tmux invocation; a hung command fails fast well
# within the process tier's relaxed budget rather than blocking the stage.
_TMUX_TIMEOUT_S = 15

# tmux protocol tokens the harness inspects on captured invocations.
_WINDOW_STYLE = "window-style"
_TARGET_FLAG = "-t"
_SET_VERBS = frozenset({"set", "set-environment"})
_NON_SESSION_SCOPES = ("-p", "-pu", "-w", "-s", "-sa")


@dataclass(frozen=True)
class _PaneGeometry:
    left: int
    top: int
    width: int
    height: int


class _RemoteThemingHarness(TmuxPaneManager):
    """Live-tmux harness that keeps the theming mixin real and captures tmux."""

    def __init__(self, tmux_binary: str, session_name: str) -> None:
        self.tmux_binary = tmux_binary
        self.session_name = session_name
        self._in_tmux = True
        self._layout_state = _PaneLayoutState()
        self._session_catalog: dict[str, SessionDTO] = {}
        self.state = PaneState()
        self._computer_info_resolver = _resolve_computer_info
        self.calls: list[tuple[str, ...]] = []
        self.fault_on_window_style = False
        self.tmux_names: dict[str, str] = {}
        self._tui_pane_id = self._first_pane_id()

    def _run_tmux(self, *args: str) -> str:
        self.calls.append(args)
        if self.fault_on_window_style and _WINDOW_STYLE in args and args[0] == "set":
            raise subprocess.CalledProcessError(1, [self.tmux_binary, *args])
        command = [self.tmux_binary, *args]
        if args and args[0] == "list-panes":
            command = [self.tmux_binary, "list-panes", "-t", self.session_name, *args[1:]]
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=_TMUX_TIMEOUT_S)
        return result.stdout.strip()

    def _reconcile(self) -> None:
        return None

    def _get_pane_exists(self, pane_id: str) -> bool:
        return pane_id in self._run_tmux("list-panes", "-F", "#{pane_id}").splitlines()

    def _get_current_pane_id(self) -> str | None:
        return self._tui_pane_id

    def _build_attach_cmd(self, _tmux_session_name: str, _computer_info: object = None) -> str:
        del _tmux_session_name, _computer_info
        return "sleep 60"

    def _is_tree_selected_session(self, _session_id: str) -> bool:
        del _session_id
        return False

    def _get_session_agent(self, session_id: str) -> str | None:
        session = self._session_catalog.get(session_id)
        return session.active_agent if session else None

    def focus_pane_for_session(self, session_id: str) -> bool:
        return session_id in self.state.session_to_pane

    def _first_pane_id(self) -> str:
        return self._run_tmux("list-panes", "-F", "#{pane_id}").splitlines()[0]

    def geometry(self) -> dict[str, _PaneGeometry]:
        output = self._run_tmux(
            "list-panes",
            "-F",
            "#{pane_id}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}",
        )
        panes: dict[str, _PaneGeometry] = {}
        for line in output.splitlines():
            pane_id, left, top, width, height = line.split("\t")
            panes[pane_id] = _PaneGeometry(int(left), int(top), int(width), int(height))
        return panes


def _resolve_computer_info(name: str) -> ComputerInfo | None:
    if name == _REMOTE_COMPUTER:
        return ComputerInfo(name=name, is_local=False, user="morriz", host="192.168.1.30")
    return ComputerInfo(name="local", is_local=True)


def _session(session_id: str, computer: str, tmux_session_name: str) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="idle",
        tmux_session_name=tmux_session_name,
        active_agent="codex",
        computer=computer,
    )


def _apply(harness: _RemoteThemingHarness, *, active: str) -> None:
    harness.apply_layout(
        active_session_id=active,
        sticky_session_ids=[],
        get_computer_info=_resolve_computer_info,
        focus=False,
    )


def _session_scoped_targets(calls: list[tuple[str, ...]]) -> set[str]:
    """Session names hit by a session-scoped ``set``/``set-environment -t``."""
    targets: set[str] = set()
    for args in calls:
        if not args or args[0] not in _SET_VERBS:
            continue
        if any(scope in args for scope in _NON_SESSION_SCOPES):
            continue  # pane/window/server scope, not session scope
        if _TARGET_FLAG in args:
            idx = args.index(_TARGET_FLAG)
            if idx + 1 < len(args):
                targets.add(args[idx + 1])
    return targets


@pytest.fixture
def remote_harness() -> Generator[_RemoteThemingHarness, None, None]:
    tmux_binary = shutil.which("tmux")
    if tmux_binary is None:
        pytest.skip("tmux is unavailable")
    suffix = str(os.getpid())
    session_name = f"tc-theming-{suffix}"
    subprocess.run(
        [tmux_binary, "new-session", "-d", "-s", session_name, "-x", "120", "-y", "40", "sleep 60"],
        check=True,
        timeout=_TMUX_TIMEOUT_S,
    )
    tmux_names = {
        "lpreview": f"tmux-lpreview-{suffix}",
        "lpreview2": f"tmux-lpreview2-{suffix}",
        "rpreview": f"tmux-rpreview-{suffix}",
    }
    # Local session names must exist on the local server for session-scoped
    # option-sets to succeed; the remote name is deliberately absent (it lives
    # only on the remote host), which is exactly what the remote guard sidesteps.
    local_sessions = (tmux_names["lpreview"], tmux_names["lpreview2"])
    for name in local_sessions:
        subprocess.run(
            [tmux_binary, "new-session", "-d", "-s", name, "sleep 60"],
            check=True,
            timeout=_TMUX_TIMEOUT_S,
        )
    try:
        harness = _RemoteThemingHarness(tmux_binary, session_name)
        harness.tmux_names = tmux_names
        harness._session_catalog = {
            "lpreview": _session("lpreview", "local", tmux_names["lpreview"]),
            "lpreview2": _session("lpreview2", "local", tmux_names["lpreview2"]),
            "rpreview": _session("rpreview", _REMOTE_COMPUTER, tmux_names["rpreview"]),
        }
        yield harness
    finally:
        for name in (session_name, *local_sessions):
            subprocess.run([tmux_binary, "kill-session", "-t", name], check=False, timeout=_TMUX_TIMEOUT_S)


def test_remote_preview_then_local_preview_swaps_without_local_session_scoped_tmux(
    remote_harness: _RemoteThemingHarness,
) -> None:
    harness = remote_harness

    _apply(harness, active="rpreview")
    _apply(harness, active="lpreview")

    targets = _session_scoped_targets(harness.calls)
    # The remote session name is not a valid target on the local tmux server, so
    # no session-scoped command may address it.
    assert harness.tmux_names["rpreview"] not in targets
    # Parity: the local preview still gets its session-scoped `status off`.
    assert harness.tmux_names["lpreview"] in targets
    # The swap happened in place: TUI + one preview pane, no nested split.
    assert len(harness.geometry()) == 2
    assert harness.state.session_to_pane.get("lpreview") is not None
    assert harness.state.session_to_pane.get("rpreview") is None


def test_swap_stays_coherent_when_post_respawn_theming_fails(
    remote_harness: _RemoteThemingHarness,
) -> None:
    harness = remote_harness

    _apply(harness, active="rpreview")

    # Fault a still-executed post-respawn pane-scoped command (a path the remote
    # guard does not remove): theming the swapped-in local pane must fail.
    harness.fault_on_window_style = True
    with pytest.raises(subprocess.CalledProcessError):
        _apply(harness, active="lpreview")
    harness.fault_on_window_style = False

    # Structural state stayed coherent despite the theming failure: the cell
    # spec and the pane map agree (no split-brain).
    cell_specs = harness._layout_state.cell_specs or []
    assert [spec.session_id for spec in cell_specs] == ["lpreview"]
    assert harness.state.session_to_pane.get("lpreview") is not None
    assert harness.state.session_to_pane.get("rpreview") is None

    # The next preview swaps in place rather than producing a nested split.
    _apply(harness, active="lpreview2")
    assert len(harness.geometry()) == 2
    assert harness.state.session_to_pane.get("lpreview2") is not None
