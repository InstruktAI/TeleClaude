"""Characterization tests for pure functions in teleclaude.cli.tui.widgets.banner."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.widgets.banner import (
    BANNER_HEIGHT,
    BANNER_LINES,
    LOGO_HEIGHT,
    LOGO_LINES,
    LOGO_WIDTH,
    _apply_sky_ambient,
    _apply_sky_entity,
    _consume_sky_entity_value,
    _dim_color,
    _is_pipe,
    _to_color,
)

# --- _to_color ---


@pytest.mark.unit
def test_to_color_returns_string_longer_than_one_char() -> None:
    assert _to_color("#FF0000") == "#FF0000"


@pytest.mark.unit
def test_to_color_returns_none_for_single_char_string() -> None:
    assert _to_color("a") is None


@pytest.mark.unit
def test_to_color_returns_none_for_none_input() -> None:
    assert _to_color(None) is None


@pytest.mark.unit
def test_to_color_returns_none_for_integer_input() -> None:
    assert _to_color(42) is None


# --- _is_pipe ---


@pytest.mark.unit
def test_is_pipe_returns_true_for_double_line_box_drawing_char() -> None:
    assert _is_pipe("\u2550") is True  # ═


@pytest.mark.unit
def test_is_pipe_returns_true_for_upper_bound_char() -> None:
    assert _is_pipe("\u256c") is True  # ╬


@pytest.mark.unit
def test_is_pipe_returns_false_for_regular_ascii() -> None:
    assert _is_pipe("a") is False


@pytest.mark.unit
def test_is_pipe_returns_false_for_space() -> None:
    assert _is_pipe(" ") is False


# --- _dim_color ---


@pytest.mark.unit
def test_dim_color_scales_rgb_components() -> None:
    result = _dim_color("#ffffff", 0.5)
    # Each component: 255 * 0.5 = 127 = 0x7f
    assert result == "#7f7f7f"


@pytest.mark.unit
def test_dim_color_returns_original_when_not_hex() -> None:
    result = _dim_color("blue", 0.5)
    assert result == "blue"


@pytest.mark.unit
def test_dim_color_returns_original_for_wrong_length() -> None:
    result = _dim_color("#FFF", 0.5)
    assert result == "#FFF"


@pytest.mark.unit
def test_dim_color_factor_one_returns_same_color() -> None:
    result = _dim_color("#80c0e0", 1.0)
    assert result == "#80c0e0"


# --- banner constants ---


@pytest.mark.unit
def test_banner_lines_count_matches_banner_height() -> None:
    # BANNER_HEIGHT = len(BANNER_LINES) + 1
    assert BANNER_HEIGHT == len(BANNER_LINES) + 1


@pytest.mark.unit
def test_logo_height_equals_logo_lines_plus_one() -> None:
    assert LOGO_HEIGHT == len(LOGO_LINES) + 1


@pytest.mark.unit
def test_logo_width_pinned() -> None:
    assert LOGO_WIDTH == 40


# --- _apply_sky_entity ---


@pytest.mark.unit
def test_apply_sky_entity_sets_fg_char_and_color_for_non_partial() -> None:
    state: dict[str, str | bool | None] = {
        "fg_char": " ",
        "fg_color": None,
        "bg_entity_color": None,
        "need_behind": False,
    }
    done = _apply_sky_entity(state, "X", "#FF0000", "#FF0000", partial=False)
    assert state["fg_char"] == "X"
    assert state["fg_color"] == "#FF0000"
    assert done is False  # same fg and bg, no extra bg_entity_color


@pytest.mark.unit
def test_apply_sky_entity_partial_triggers_need_behind() -> None:
    state: dict[str, str | bool | None] = {
        "fg_char": " ",
        "fg_color": None,
        "bg_entity_color": None,
        "need_behind": False,
    }
    done = _apply_sky_entity(state, "\u2588", "#AABBCC", "#AABBCC", partial=True)
    assert state["need_behind"] is True
    assert done is False


# --- _apply_sky_ambient ---


@pytest.mark.unit
def test_apply_sky_ambient_sets_fg_color_when_none() -> None:
    state: dict[str, str | bool | None] = {
        "fg_char": " ",
        "fg_color": None,
        "bg_entity_color": None,
        "need_behind": False,
    }
    done = _apply_sky_ambient(state, "#112233")
    assert state["fg_color"] == "#112233"
    assert done is False


@pytest.mark.unit
def test_apply_sky_ambient_sets_bg_entity_color_when_fg_color_already_set() -> None:
    state: dict[str, str | bool | None] = {
        "fg_char": "A",
        "fg_color": "#AABBCC",
        "bg_entity_color": None,
        "need_behind": False,
    }
    done = _apply_sky_ambient(state, "#112233")
    assert state["bg_entity_color"] == "#112233"
    assert done is True


# --- _consume_sky_entity_value ---


@pytest.mark.unit
def test_consume_sky_entity_value_parses_7char_ambient() -> None:
    """7-char value starting with # is ambient: sets fg_color only."""
    state: dict[str, str | bool | None] = {
        "fg_char": " ",
        "fg_color": None,
        "bg_entity_color": None,
        "need_behind": False,
    }
    _consume_sky_entity_value(state, "#AABBCC", z=1, dark_mode=True)
    assert state["fg_color"] == "#AABBCC"


@pytest.mark.unit
def test_consume_sky_entity_value_parses_8char_colored_entity() -> None:
    """8-char value: #RRGGBBc — colored entity char."""
    state: dict[str, str | bool | None] = {
        "fg_char": " ",
        "fg_color": None,
        "bg_entity_color": None,
        "need_behind": False,
    }
    val = "#FF0000X"  # 8 chars: color + char
    _consume_sky_entity_value(state, val, z=1, dark_mode=True)
    assert state["fg_char"] == "X"
    assert state["fg_color"] == "#FF0000"
