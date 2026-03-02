"""Unit tests for TUI theming state gating and hex palette."""

from teleclaude.cli.tui.theme import (
    AGENT_PALETTE,
    NEUTRAL_PALETTE,
    PEACEFUL_PALETTE,
    STRUCTURAL_PALETTE,
    get_agent_hex,
    get_agent_normal_color,
    get_neutral_color,
    get_peaceful_color,
    get_structural_color,
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


def test_agent_palette_has_all_agents_and_tiers() -> None:
    """AGENT_PALETTE has entries for all agents in both modes."""
    for mode in ("dark", "light"):
        for agent in ("claude", "gemini", "codex"):
            for tier in ("subtle", "muted", "normal", "highlight"):
                val = AGENT_PALETTE[mode][agent][tier]
                assert val.startswith("#"), f"Expected hex, got {val}"
                assert len(val) == 7, f"Expected #RRGGBB, got {val}"


def test_get_agent_hex_returns_palette_value(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.theme._is_dark_mode", True)
    assert get_agent_hex("claude", "normal") == AGENT_PALETTE["dark"]["claude"]["normal"]


def test_get_agent_normal_color_returns_hex(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.theme._is_dark_mode", True)
    result = get_agent_normal_color("claude")
    assert result.startswith("#")


def test_neutral_palette_complete() -> None:
    for mode in ("dark", "light"):
        for tier in ("subtle", "muted", "normal", "highlight"):
            assert tier in NEUTRAL_PALETTE[mode]


def test_peaceful_palette_complete() -> None:
    for mode in ("dark", "light"):
        for tier in ("subtle", "muted", "normal", "highlight"):
            assert tier in PEACEFUL_PALETTE[mode]


def test_structural_palette_complete() -> None:
    for mode in ("dark", "light"):
        for key in ("connector", "separator", "input_border", "banner", "status_fg"):
            assert key in STRUCTURAL_PALETTE[mode]


def test_get_neutral_color_dark(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.theme._is_dark_mode", True)
    assert get_neutral_color("highlight") == "#e0e0e0"


def test_get_neutral_color_light(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.theme._is_dark_mode", False)
    assert get_neutral_color("highlight") == "#202020"


def test_get_peaceful_color_dark(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.theme._is_dark_mode", True)
    assert get_peaceful_color("normal") == "#bcbcbc"


def test_get_structural_color(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.theme._is_dark_mode", True)
    assert get_structural_color("connector") == "#808080"
