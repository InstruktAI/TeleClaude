"""Characterization tests for animations/creative.py."""

from __future__ import annotations

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.animations.creative import (
    ColorSweep,
    EQBars,
    Glitch,
    LaserScan,
    LavaLamp,
    NeonFlicker,
    Plasma,
)
from teleclaude.cli.tui.pixel_mapping import BIG_BANNER_LETTERS, PixelMap


def _palette() -> SpectrumPalette:
    return SpectrumPalette()


def _make(cls: type[Animation], is_big: bool = True) -> Animation:
    return cls(palette=_palette(), is_big=is_big, duration_seconds=5.0, seed=42)


def _update(anim: Animation, frame: int = 0) -> dict[tuple[int, int], str | int]:
    result = anim.update(frame)
    assert isinstance(result, dict)
    return result


def _big_letter_pixel_count() -> int:
    return sum(len(PixelMap.get_letter_pixels(True, idx)) for idx in range(len(BIG_BANNER_LETTERS)))


class TestNeonFlicker:
    def test_theme_filter_dark(self) -> None:
        assert NeonFlicker.theme_filter == "dark"

    def test_same_seed_reproduces_first_frame(self) -> None:
        first = _update(_make(NeonFlicker), 0)
        second = _update(_make(NeonFlicker), 0)

        assert first == second

    def test_consecutive_frames_shift_letter_intensities(self) -> None:
        anim = _make(NeonFlicker)

        assert _update(anim, 0) != _update(anim, 1)

    def test_update_covers_all_big_letter_pixels(self) -> None:
        result = _update(_make(NeonFlicker), 0)

        assert len(result) == _big_letter_pixel_count()
        assert len(set(result.values())) > 1


class TestPlasma:
    def test_same_seed_reproduces_first_frame(self) -> None:
        first = _update(_make(Plasma), 0)
        second = _update(_make(Plasma), 0)

        assert first == second

    def test_frames_change_color_field_over_time(self) -> None:
        anim = _make(Plasma)

        assert _update(anim, 0) != _update(anim, 10)

    def test_update_covers_all_big_letter_pixels(self) -> None:
        result = _update(_make(Plasma), 0)

        assert len(result) == _big_letter_pixel_count()
        assert all(isinstance(value, str) and value.startswith("#") for value in result.values())


class TestGlitch:
    def test_burst_frame_contains_corruption_colors(self) -> None:
        result = _update(_make(Glitch), 0)

        assert "#ffffff" in result.values()
        assert len(set(result.values())) > 1

    def test_non_burst_frame_settles_to_single_base_color(self) -> None:
        result = _update(_make(Glitch), 5)

        assert len(set(result.values())) == 1


class TestEQBars:
    def test_update_covers_all_big_letter_pixels(self) -> None:
        result = _update(_make(EQBars), 0)

        assert len(result) == _big_letter_pixel_count()

    def test_update_contains_dark_and_lit_bars(self) -> None:
        result = _update(_make(EQBars), 0)
        values = set(result.values())

        assert "#080808" in values
        assert len(values) > 1

    def test_frames_change_column_levels(self) -> None:
        anim = _make(EQBars)

        assert _update(anim, 0) != _update(anim, 10)


class TestLavaLamp:
    def test_update_covers_all_big_letter_pixels(self) -> None:
        result = _update(_make(LavaLamp), 0)

        assert len(result) == _big_letter_pixel_count()

    def test_update_contains_background_and_blob_colors(self) -> None:
        result = _update(_make(LavaLamp), 0)
        values = set(result.values())

        assert "#050512" in values
        assert len(values) > 1

    def test_frames_shift_visible_blob_mix(self) -> None:
        anim = _make(LavaLamp)

        assert _update(anim, 0) != _update(anim, 10)


class TestColorSweep:
    def test_theme_filter_dark(self) -> None:
        assert ColorSweep.theme_filter == "dark"

    def test_same_seed_reproduces_first_frame(self) -> None:
        first = _update(_make(ColorSweep), 0)
        second = _update(_make(ColorSweep), 0)

        assert first == second

    def test_first_frame_lights_only_subset_of_letters(self) -> None:
        result = _update(_make(ColorSweep), 0)

        assert 0 < len(result) < _big_letter_pixel_count()

    def test_lit_region_moves_over_time(self) -> None:
        anim = _make(ColorSweep)

        assert _update(anim, 0) != _update(anim, 10)


class TestLaserScan:
    def test_theme_filter_dark(self) -> None:
        assert LaserScan.theme_filter == "dark"

    def test_update_covers_all_big_letter_pixels(self) -> None:
        result = _update(_make(LaserScan), 0)

        assert len(result) == _big_letter_pixel_count()

    def test_scanning_frame_contains_white_hot_core(self) -> None:
        result = _update(_make(LaserScan), 2)

        assert "#ffffff" in result.values()

    def test_beam_position_changes_visible_colors(self) -> None:
        anim = _make(LaserScan)

        assert _update(anim, 0) != _update(anim, 2)
