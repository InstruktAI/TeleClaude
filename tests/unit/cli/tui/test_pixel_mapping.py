from __future__ import annotations

import pytest

from teleclaude.cli.tui.pixel_mapping import PixelMap, RenderTarget, TargetRegistry


@pytest.mark.unit
def test_render_target_caches_a_full_grid_of_pixels() -> None:
    target = RenderTarget(name="custom", width=3, height=2, letters=[(0, 0), (1, 1)])

    pixels = target.get_all_pixels()

    assert len(pixels) == 6
    assert pixels[0] == (0, 0)
    assert pixels[-1] == (2, 1)
    assert target.get_all_pixels() is pixels


@pytest.mark.unit
def test_pixel_map_routes_boolean_targets_to_current_pixel_sets() -> None:
    pixel_map = PixelMap()

    assert len(pixel_map.get_all_pixels(False)) == 120
    assert len(pixel_map.get_all_pixels(True)) == 504
    assert pixel_map.get_row_pixels(0, False) == []
    assert pixel_map.get_column_pixels(0, True) == []
    assert pixel_map.get_letter_pixels(0, False) == []
    assert pixel_map.get_letter_pixels(0, True) == []
    assert pixel_map.get_is_character(False, 999, 999) is False
    assert pixel_map.get_is_letter(False, 999, 999) is False


@pytest.mark.unit
def test_target_registry_returns_registered_targets_by_name() -> None:
    registry = TargetRegistry()

    registry.register("custom", 4, 1, [])

    target = registry.get("custom")

    assert target is not None
    assert target.name == "custom"
    assert target.width == 4
