from __future__ import annotations

import pytest

from teleclaude.cli.tui.color_utils import (
    blend,
    deepen_for_light_mode,
    hex_to_rgb,
    letter_color_floor,
    relative_luminance,
    rgb_to_hex,
)


@pytest.mark.unit
def test_hex_and_rgb_helpers_round_trip_and_clamp_channels() -> None:
    assert hex_to_rgb("#336699") == (51, 102, 153)
    assert rgb_to_hex(0x33, 0x66, 0x99) == "#336699"
    assert rgb_to_hex(-5, 260, 128) == "#00ff80"


@pytest.mark.unit
def test_blend_returns_average_for_valid_hex_and_base_for_invalid_target() -> None:
    assert blend("#000000", "#ffffff", 0.5) == "#7f7f7f"
    assert blend("#123456", "oops", 0.5) == "#123456"


@pytest.mark.unit
def test_luminance_and_light_mode_helpers_follow_current_thresholds() -> None:
    assert relative_luminance("#000000") == 0.0
    assert deepen_for_light_mode("#eeeeee") == "#cacaca"
    assert letter_color_floor("#102030", "#203040") == "#203040"
