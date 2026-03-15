from __future__ import annotations

import pytest

from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui import pane_layout
from teleclaude.cli.tui._pane_specs import PaneState, SessionPaneSpec


class _PaneLayoutHarness(pane_layout.PaneLayoutMixin):
    def __init__(self) -> None:
        self._in_tmux = True
        self._tui_pane_id = "%1"
        self._sticky_specs: list[SessionPaneSpec] = []
        self._active_spec: SessionPaneSpec | None = None
        self._selected_session_id: str | None = None
        self._tree_node_has_focus = False
        self._bg_signature = None
        self._layout_signature = None
        self._session_catalog: dict[str, SessionDTO] = {}
        self.state = PaneState()
        self.events: list[tuple[str, object]] = []
        self._unchanged = False

    def _reconcile(self) -> None:
        self.events.append(("reconcile", None))

    def _layout_is_unchanged(self) -> bool:
        return self._unchanged

    def _render_layout(self) -> None:
        self.events.append(("render", None))

    def invalidate_bg_cache(self) -> None:
        self.events.append(("invalidate", None))

    def focus_pane_for_session(self, session_id: str) -> None:
        self.events.append(("focus", session_id))

    def _update_active_pane(self, active_spec: SessionPaneSpec) -> None:
        self.events.append(("update-active", active_spec.session_id))

    def _clear_active_state_if_sticky(self) -> None:
        self.events.append(("clear-active", None))

    def _refresh_session_pane_backgrounds(self) -> None:
        self.events.append(("refresh-bg", None))

    def _set_tui_pane_background(self) -> None:
        self.events.append(("tui-bg", None))

    def _get_pane_exists(self, _pane_id: str) -> bool:
        return True

    def _set_pane_background(
        self, pane_id: str, tmux_session_name: str, agent: str, *, is_tree_selected: bool = False
    ) -> None:
        self.events.append(("session-bg", (pane_id, tmux_session_name, agent, is_tree_selected)))

    def _set_doc_pane_background(self, pane_id: str, *, agent: str = "") -> None:
        self.events.append(("doc-bg", (pane_id, agent)))

    def _build_attach_cmd(self, tmux_session_name: str, computer_info: object = None) -> str:
        return f"attach:{tmux_session_name}"

    @property
    def _active_pane_id(self) -> str | None:
        if self.state.active_session_id is None:
            return None
        return self.state.session_to_pane.get(self.state.active_session_id)


@pytest.mark.unit
def test_apply_layout_builds_active_spec_and_renders_when_signature_changes() -> None:
    harness = _PaneLayoutHarness()
    harness._session_catalog = {
        "session-1": SessionDTO(
            session_id="session-1",
            title="title",
            status="idle",
            tmux_session_name="tmux-1",
            active_agent="codex",
            computer="c1",
        )
    }

    harness.apply_layout(
        active_session_id="session-1",
        sticky_session_ids=[],
        get_computer_info=lambda name: None,
        focus=True,
    )

    assert harness._active_spec is not None
    assert harness._active_spec.session_id == "session-1"
    assert ("render", None) in harness.events
    assert ("invalidate", None) in harness.events
    assert ("focus", "session-1") in harness.events


@pytest.mark.unit
def test_build_session_specs_caps_output_at_five_entries() -> None:
    harness = _PaneLayoutHarness()
    harness._sticky_specs = [
        SessionPaneSpec(f"sticky-{index}", f"tmux-{index}", None, True, "codex") for index in range(1, 6)
    ]
    harness._active_spec = SessionPaneSpec("active", "tmux-active", None, False, "claude")

    specs = harness._build_session_specs()

    assert len(specs) == 5
    assert [spec.session_id for spec in specs] == ["sticky-1", "sticky-2", "sticky-3", "sticky-4", "sticky-5"]


@pytest.mark.unit
def test_build_pane_command_prefixes_doc_commands_for_peaceful_levels() -> None:
    harness = _PaneLayoutHarness()
    command_spec = SessionPaneSpec("doc:1", None, None, False, "", command="less file.md")
    session_spec = SessionPaneSpec("session-1", "tmux-1", None, False, "codex")
    original = pane_layout.theme.get_pane_theming_mode_level
    try:
        pane_layout.theme.get_pane_theming_mode_level = lambda: 1
        assert harness._build_pane_command(command_spec) == "NO_COLOR=1 less file.md"
        pane_layout.theme.get_pane_theming_mode_level = lambda: 3
        assert harness._build_pane_command(command_spec) == "less file.md"
    finally:
        pane_layout.theme.get_pane_theming_mode_level = original

    assert harness._build_pane_command(session_spec) == "attach:tmux-1"
