from __future__ import annotations

import pytest

from teleclaude.cli.tui import theme


@pytest.mark.unit
def test_normalize_pane_theming_mode_preserves_current_aliases_and_rejects_invalid_values() -> None:
    assert theme.normalize_pane_theming_mode("full") == "agent_plus"
    assert theme.normalize_pane_theming_mode("agent") == "agent"
    with pytest.raises(ValueError):
        theme.normalize_pane_theming_mode("none")


@pytest.mark.unit
def test_pane_theming_level_helpers_reflect_current_mode_table() -> None:
    assert theme.get_pane_theming_mode_from_level(0) == "off"
    assert theme.get_pane_theming_mode_from_level(4) == "agent_plus"
    assert theme.should_apply_session_theming(0) is False
    assert theme.should_apply_session_theming(1) is True
    assert theme.should_apply_session_theming(2) is False
    assert theme.should_apply_session_theming(3) is True
    assert theme.should_apply_session_theming(4) is True
    assert theme.should_apply_paint_pane_theming(3) is True
    assert theme.should_apply_paint_pane_theming(4) is False
    with pytest.raises(ValueError):
        theme.get_pane_theming_mode_from_level(5)


@pytest.mark.unit
def test_theme_color_resolution_depends_on_dark_mode_cache() -> None:
    assert theme.resolve_selection_bg_hex(None) == "#606060"

    original = theme._is_dark_mode
    try:
        theme._is_dark_mode = True
        assert theme.get_agent_hex("codex") == "#afd7ff"
        theme._is_dark_mode = False
        assert theme.get_agent_hex("codex") == "#005f87"
    finally:
        theme._is_dark_mode = original
