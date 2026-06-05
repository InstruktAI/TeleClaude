from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Generator
from dataclasses import dataclass

import pytest

from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui._pane_specs import PaneState
from teleclaude.cli.tui.pane_manager import TmuxPaneManager, _PaneLayoutState

pytestmark = pytest.mark.functional


@dataclass(frozen=True)
class _PaneGeometry:
    left: int
    top: int
    width: int
    height: int


class _LiveTmuxLayoutHarness(TmuxPaneManager):
    def __init__(self, tmux_binary: str, session_name: str) -> None:
        self.tmux_binary = tmux_binary
        self.session_name = session_name
        self._in_tmux = True
        self._layout_state = _PaneLayoutState()
        self._session_catalog: dict[str, SessionDTO] = {}
        self.state = PaneState()
        self._tui_pane_id = self._first_pane_id()

    def _run_tmux(self, *args: str) -> str:
        command = [self.tmux_binary, *args]
        if args and args[0] == "list-panes":
            command = [self.tmux_binary, "list-panes", "-t", self.session_name, *args[1:]]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def _reconcile(self) -> None:
        return None

    def _get_pane_exists(self, pane_id: str) -> bool:
        return pane_id in self._run_tmux("list-panes", "-F", "#{pane_id}").splitlines()

    def _get_current_pane_id(self) -> str | None:
        return self._tui_pane_id

    def _build_attach_cmd(self, tmux_session_name: str, computer_info: object = None) -> str:
        return "sleep 60"

    def _is_tree_selected_session(self, _session_id: str) -> bool:
        return False

    def _get_session_agent(self, session_id: str) -> str | None:
        session = self._session_catalog.get(session_id)
        return session.active_agent if session else None

    def _set_pane_background(self, *_args: object, **_kwargs: object) -> None:
        return None

    def _set_doc_pane_background(self, *_args: object, **_kwargs: object) -> None:
        return None

    def _set_tui_pane_background(self) -> None:
        return None

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


def _session(session_id: str) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="idle",
        tmux_session_name=f"tmux-{session_id}",
        active_agent="codex",
        computer="local",
    )


def _apply(harness: _LiveTmuxLayoutHarness, *, active: str | None, sticky: list[str]) -> None:
    harness.apply_layout(
        active_session_id=active,
        sticky_session_ids=sticky,
        get_computer_info=lambda _name: None,
        focus=False,
    )


@pytest.fixture
def live_tmux_harness() -> Generator[_LiveTmuxLayoutHarness, None, None]:
    tmux_binary = shutil.which("tmux")
    if tmux_binary is None:
        pytest.skip("tmux is unavailable")
    session_name = f"tc-layout-{os.getpid()}"
    subprocess.run(
        [tmux_binary, "new-session", "-d", "-s", session_name, "-x", "120", "-y", "40", "sleep 60"],
        check=True,
    )
    try:
        harness = _LiveTmuxLayoutHarness(tmux_binary, session_name)
        harness._session_catalog = {sid: _session(sid) for sid in ("s1", "s2", "s3", "s4", "s5", "preview")}
        yield harness
    finally:
        subprocess.run([tmux_binary, "kill-session", "-t", session_name], check=False)


def _assert_three_by_two_bound(geometry: dict[str, _PaneGeometry]) -> None:
    assert len(geometry) <= 6
    assert len({pane.left for pane in geometry.values()}) <= 3
    assert len({pane.top for pane in geometry.values()}) <= 2


def _panes_in_left_column(
    harness: _LiveTmuxLayoutHarness,
    geometry: dict[str, _PaneGeometry],
) -> set[str]:
    tui = geometry[harness._tui_pane_id]
    return {pane_id for pane_id, pane in geometry.items() if pane.left == tui.left}


def test_live_tmux_grid_preserves_panes_and_bounds_borrow_revert(
    live_tmux_harness: _LiveTmuxLayoutHarness,
) -> None:
    harness = live_tmux_harness

    _apply(harness, active=None, sticky=["s1", "s2", "s3"])
    tui_plus_three = dict(harness.state.session_to_pane)

    _apply(harness, active=None, sticky=["s1", "s2", "s3", "s4"])
    tui_plus_four = dict(harness.state.session_to_pane)
    geometry_four = harness.geometry()
    _assert_three_by_two_bound(geometry_four)
    assert _panes_in_left_column(harness, geometry_four) == {harness._tui_pane_id}
    assert {sid: tui_plus_four[sid] for sid in ("s1", "s2", "s3")} == tui_plus_three

    _apply(harness, active=None, sticky=["s1", "s2", "s3", "s4", "s5"])
    tui_plus_five = dict(harness.state.session_to_pane)
    geometry_five = harness.geometry()
    _assert_three_by_two_bound(geometry_five)
    assert _panes_in_left_column(harness, geometry_five) == {harness._tui_pane_id, tui_plus_five["s5"]}
    assert {sid: tui_plus_five[sid] for sid in ("s1", "s2", "s3", "s4")} == tui_plus_four

    borrowed_pane = tui_plus_five["s5"]
    _apply(harness, active="preview", sticky=["s1", "s2", "s3", "s4", "s5"])
    assert harness.state.session_to_pane["preview"] == borrowed_pane
    _assert_three_by_two_bound(harness.geometry())

    _apply(harness, active=None, sticky=["s1", "s2", "s3", "s4", "s5"])
    assert harness.state.session_to_pane["s5"] == borrowed_pane
    assert "preview" not in harness.state.session_to_pane
    _assert_three_by_two_bound(harness.geometry())
