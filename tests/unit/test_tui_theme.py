"""Unit tests for TUI theming state gating."""

import curses

from teleclaude.cli.tui.theme import (
    AGENT_PREVIEW_SELECTED_BG_PAIRS,
    AGENT_PREVIEW_SELECTED_BG_PAIRS_HIGHLIGHT,
    AGENT_PREVIEW_SELECTED_BG_PAIRS_OFF,
    AGENT_PREVIEW_SELECTED_BG_PAIRS_SEMI,
    AGENT_PREVIEW_SELECTED_FOCUS_PAIRS,
    AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_HIGHLIGHT,
    AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_OFF,
    AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_SEMI,
    get_agent_preview_selected_bg_attr,
    get_agent_preview_selected_focus_attr,
    should_apply_paint_pane_theming,
    should_apply_session_theming,
)


def test_should_apply_session_theming_respects_pane_levels() -> None:
    """Session pane theming is only active in the intended levels."""
    assert should_apply_session_theming(0) is False
    assert should_apply_session_theming(1) is True
    assert should_apply_session_theming(2) is False
    assert should_apply_session_theming(3) is True
    assert should_apply_session_theming(4) is True


def test_should_apply_paint_theming_only_when_full_agent_level() -> None:
    """Paint pane theming remains limited to the third highlight state."""
    assert should_apply_paint_pane_theming(0) is False
    assert should_apply_paint_pane_theming(1) is False
    assert should_apply_paint_pane_theming(2) is False
    assert should_apply_paint_pane_theming(3) is True
    assert should_apply_paint_pane_theming(4) is False


def test_preview_selected_bg_uses_off_for_state_0_and_2(monkeypatch) -> None:
    """State 2 reverts to peaceful row styling despite advancing the footer indicator."""
    monkeypatch.setattr("teleclaude.cli.tui.theme.get_pane_theming_mode_level", lambda _mode: mode_level)
    monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

    for mode_level in (0, 2):
        assert (
            get_agent_preview_selected_bg_attr("claude")
            == AGENT_PREVIEW_SELECTED_BG_PAIRS_OFF["claude"] | curses.A_BOLD
        )
        assert (
            get_agent_preview_selected_focus_attr("claude")
            == AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_OFF["claude"] | curses.A_BOLD
        )

    for mode_level in (1,):
        assert (
            get_agent_preview_selected_bg_attr("claude")
            == AGENT_PREVIEW_SELECTED_BG_PAIRS_HIGHLIGHT["claude"] | curses.A_BOLD
        )
        assert (
            get_agent_preview_selected_focus_attr("claude")
            == AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_HIGHLIGHT["claude"] | curses.A_BOLD
        )

    for mode_level in (3,):
        assert (
            get_agent_preview_selected_bg_attr("claude")
            == AGENT_PREVIEW_SELECTED_BG_PAIRS_SEMI["claude"] | curses.A_BOLD
        )
        assert (
            get_agent_preview_selected_focus_attr("claude")
            == AGENT_PREVIEW_SELECTED_FOCUS_PAIRS_SEMI["claude"] | curses.A_BOLD
        )

    for mode_level in (4,):
        assert get_agent_preview_selected_bg_attr("claude") == AGENT_PREVIEW_SELECTED_BG_PAIRS["claude"] | curses.A_BOLD
        assert (
            get_agent_preview_selected_focus_attr("claude")
            == AGENT_PREVIEW_SELECTED_FOCUS_PAIRS["claude"] | curses.A_BOLD
        )
