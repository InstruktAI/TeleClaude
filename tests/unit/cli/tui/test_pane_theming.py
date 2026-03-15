from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.cli.tui import pane_theming
from teleclaude.cli.tui._pane_specs import PaneState, SessionPaneSpec


class _PaneThemingHarness(pane_theming.PaneThemingMixin):
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._tui_pane_id = "%1"
        self._in_tmux = True
        self._sticky_specs: list[SessionPaneSpec] = []
        self._active_spec: SessionPaneSpec | None = None
        self.state = PaneState()
        self._session_catalog: dict[str, SimpleNamespace] = {}

    def _run_tmux(self, *args: str) -> None:
        self.calls.append(args)

    def _get_pane_exists(self, _pane_id: str) -> bool:
        return True

    def invalidate_bg_cache(self) -> None:
        self.calls.append(("invalidate",))

    def _set_pane_background(
        self, pane_id: str, tmux_session_name: str, agent: str, *, is_tree_selected: bool = False
    ) -> None:
        self.calls.append(("session-bg", pane_id, tmux_session_name, agent, str(is_tree_selected)))

    def _set_doc_pane_background(self, pane_id: str, *, agent: str = "") -> None:
        self.calls.append(("doc-bg", pane_id, agent))

    def _set_tui_pane_background(self) -> None:
        self.calls.append(("tui-bg",))

    def _is_tree_selected_session(self, session_id: str) -> bool:
        return session_id == "session-selected"


@pytest.mark.unit
def test_apply_no_color_policy_switches_between_set_and_unset() -> None:
    harness = _PaneThemingHarness()
    original = pane_theming.theme.get_pane_theming_mode_level
    try:
        pane_theming.theme.get_pane_theming_mode_level = lambda: 1
        harness._apply_no_color_policy("tc_demo")
        pane_theming.theme.get_pane_theming_mode_level = lambda: 2
        harness._apply_no_color_policy("tc_demo")
    finally:
        pane_theming.theme.get_pane_theming_mode_level = original

    assert harness.calls == [
        ("set-environment", "-t", "tc_demo", "NO_COLOR", "1"),
        ("set-environment", "-t", "tc_demo", "-u", "NO_COLOR"),
    ]


@pytest.mark.unit
def test_set_tui_pane_background_applies_or_clears_styles_from_theme_level() -> None:
    harness = _PaneThemingHarness()
    original_should = pane_theming.theme.should_apply_session_theming
    original_inactive = pane_theming.theme.get_tui_inactive_background
    original_terminal = pane_theming.theme.get_terminal_background
    try:
        pane_theming.theme.should_apply_session_theming = lambda level=None: True
        pane_theming.theme.get_tui_inactive_background = lambda: "#111111"
        pane_theming.theme.get_terminal_background = lambda: "#222222"
        pane_theming.PaneThemingMixin._set_tui_pane_background(harness)
        pane_theming.theme.should_apply_session_theming = lambda level=None: False
        pane_theming.PaneThemingMixin._set_tui_pane_background(harness)
    finally:
        pane_theming.theme.should_apply_session_theming = original_should
        pane_theming.theme.get_tui_inactive_background = original_inactive
        pane_theming.theme.get_terminal_background = original_terminal

    assert ("set", "-p", "-t", "%1", "window-style", "bg=#111111") in harness.calls
    assert ("set", "-p", "-t", "%1", "window-active-style", "bg=#222222") in harness.calls
    assert ("set", "-pu", "-t", "%1", "window-style") in harness.calls
    assert ("set", "-wu", "-t", "%1", "pane-active-border-style") in harness.calls
    assert harness.calls.count(("refresh-client",)) == 2


@pytest.mark.unit
def test_reapply_agent_colors_styles_tui_doc_and_session_panes() -> None:
    harness = _PaneThemingHarness()
    harness._sticky_specs = [
        SessionPaneSpec("session-selected", "tmux-selected", None, True, "codex"),
        SessionPaneSpec("doc:guide", None, None, True, ""),
    ]
    harness._active_spec = SessionPaneSpec("session-active", "tmux-active", None, False, "claude")
    harness.state.session_to_pane = {
        "session-selected": "%2",
        "doc:guide": "%3",
        "session-active": "%4",
        "session-other": "%5",
    }
    harness._session_catalog = {
        "session-other": SimpleNamespace(tmux_session_name="tmux-other", active_agent="gemini"),
    }

    harness.reapply_agent_colors()

    assert harness.calls[0] == ("invalidate",)
    assert ("tui-bg",) in harness.calls
    assert ("session-bg", "%2", "tmux-selected", "codex", "True") in harness.calls
    assert ("doc-bg", "%3", "") in harness.calls
    assert ("session-bg", "%4", "tmux-active", "claude", "False") in harness.calls
    assert ("session-bg", "%5", "tmux-other", "gemini", "False") in harness.calls
