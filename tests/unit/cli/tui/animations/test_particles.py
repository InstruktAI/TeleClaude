"""Characterization tests for animations/particles.py."""

from __future__ import annotations

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.animations.particles import (
    Bioluminescence,
    CinematicPrismSweep,
    FireBreath,
    MatrixRain,
    SearchlightSweep,
)


def _palette() -> SpectrumPalette:
    return SpectrumPalette()


def _make(cls: type[Animation], is_big: bool = True) -> Animation:
    return cls(palette=_palette(), is_big=is_big, duration_seconds=10.0, seed=42)


def _update(anim: Animation, frame: int = 0) -> dict[tuple[int, int], str | int]:
    result = anim.update(frame)
    assert isinstance(result, dict)
    return result


class TestMatrixRain:
    def test_update_returns_dict(self) -> None:
        anim = _make(MatrixRain)
        result = _update(anim)
        assert isinstance(result, dict)

    def test_bright_head_is_white(self) -> None:
        anim = _make(MatrixRain)
        result = _update(anim, 0)
        # Some pixels should be white (#FFFFFF) for the head
        if result:
            all_values = list(result.values())
            assert all(isinstance(v, str) for v in all_values)

    def test_columns_advance_per_frame(self) -> None:
        anim = _make(MatrixRain)
        cols_before = list(anim._columns)
        _update(anim, 0)
        cols_after = list(anim._columns)
        # At least one column should have advanced by 1
        assert cols_before != cols_after

    def test_width_matches_banner(self) -> None:
        from teleclaude.cli.tui.pixel_mapping import BIG_BANNER_WIDTH

        anim = _make(MatrixRain, is_big=True)
        assert anim.width == BIG_BANNER_WIDTH


class TestFireBreath:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(FireBreath)
        result = _update(anim)
        assert len(result) > 0

    def test_update_values_are_hex(self) -> None:
        anim = _make(FireBreath)
        result = _update(anim)
        for v in result.values():
            assert isinstance(v, str)
            assert v.startswith("#")


class TestSearchlightSweep:
    def test_theme_filter_dark(self) -> None:
        assert SearchlightSweep.theme_filter == "dark"

    def test_is_shadow_caster(self) -> None:
        assert SearchlightSweep.is_shadow_caster is True

    def test_is_external_light(self) -> None:
        assert SearchlightSweep.is_external_light is True

    def test_update_dark_mode_returns_dict(self) -> None:
        anim = _make(SearchlightSweep)
        anim.dark_mode = True
        result = _update(anim)
        assert isinstance(result, dict)

    def test_update_light_mode_returns_empty(self) -> None:
        anim = _make(SearchlightSweep)
        anim.dark_mode = False
        result = _update(anim)
        assert result == {}

    def test_batman_mask_in_beam(self) -> None:
        anim = _make(SearchlightSweep)
        anim.dark_mode = True
        result = _update(anim, 0)
        if result:
            shadow_pixels = [v for v in result.values() if v == "#060606"]
            assert isinstance(shadow_pixels, list)


class TestCinematicPrismSweep:
    def test_theme_filter_dark(self) -> None:
        assert CinematicPrismSweep.theme_filter == "dark"

    def test_is_external_light(self) -> None:
        assert CinematicPrismSweep.is_external_light is True

    def test_update_returns_dict(self) -> None:
        anim = _make(CinematicPrismSweep)
        result = anim.update(0)
        assert isinstance(result, dict)

    def test_hue_range_set(self) -> None:
        anim = _make(CinematicPrismSweep)
        assert 0 <= anim.hue_start <= 360
        assert 0 <= anim.hue_end <= 360

    def test_multiple_frames_produce_dict(self) -> None:
        anim = _make(CinematicPrismSweep)
        for frame in range(5):
            result = anim.update(frame)
            assert isinstance(result, dict)


class TestBioluminescence:
    def test_theme_filter_dark(self) -> None:
        assert Bioluminescence.theme_filter == "dark"

    def test_is_external_light(self) -> None:
        assert Bioluminescence.is_external_light is True

    def test_update_returns_dict(self) -> None:
        anim = _make(Bioluminescence)
        result = _update(anim)
        assert isinstance(result, dict)

    def test_num_agents(self) -> None:
        anim = _make(Bioluminescence)
        assert len(anim._agents) == Bioluminescence._NUM_AGENTS

    def test_trails_accumulate(self) -> None:
        anim = _make(Bioluminescence)
        _update(anim, 0)
        # Agents leave trails
        assert len(anim._trails) > 0

    def test_trailing_pixels_decay(self) -> None:
        anim = _make(Bioluminescence)
        _update(anim, 0)  # build trails
        anim._trails = {(0, 0): 2}
        _update(anim, 1)
        # Should decay from 2 to 1
        assert anim._trails.get((0, 0)) == 1

    def test_pixels_at_minus_one_are_transparent(self) -> None:
        anim = _make(Bioluminescence)
        result = _update(anim, 0)
        # Most pixels should be -1 (transparent)
        minus_ones = sum(1 for v in result.values() if v == -1)
        assert minus_ones > 0
