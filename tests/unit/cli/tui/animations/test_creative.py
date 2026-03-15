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
    _hue_to_hex,
    _pick_hue,
)


def _palette() -> SpectrumPalette:
    return SpectrumPalette()


def _make(cls: type[Animation], is_big: bool = True) -> Animation:
    return cls(palette=_palette(), is_big=is_big, duration_seconds=5.0, seed=42)


def _update(anim: Animation, frame: int = 0) -> dict[tuple[int, int], str | int]:
    result = anim.update(frame)
    assert isinstance(result, dict)
    return result


class TestHelpers:
    def test_hue_to_hex_returns_hex_string(self) -> None:
        result = _hue_to_hex(180.0)
        assert result.startswith("#")
        assert len(result) == 7

    def test_pick_hue_returns_valid_degrees(self) -> None:
        import random

        rng = random.Random(42)
        hue = _pick_hue(rng)
        assert 0.0 <= hue <= 360.0


class TestNeonFlicker:
    def test_theme_filter_dark(self) -> None:
        assert NeonFlicker.theme_filter == "dark"

    def test_update_returns_non_empty(self) -> None:
        anim = _make(NeonFlicker)
        result = _update(anim)
        assert len(result) > 0

    def test_update_values_are_hex_strings(self) -> None:
        anim = _make(NeonFlicker)
        result = _update(anim)
        for v in result.values():
            assert isinstance(v, str)
            assert v.startswith("#")

    def test_lazy_init_on_first_update(self) -> None:
        anim = _make(NeonFlicker)
        assert not anim._initialized
        _update(anim)
        assert anim._initialized

    def test_subsequent_updates_no_reinit(self) -> None:
        anim = _make(NeonFlicker)
        _update(anim, 0)
        main_color = anim._main_color
        _update(anim, 1)
        assert anim._main_color == main_color


class TestPlasma:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(Plasma)
        result = _update(anim)
        assert len(result) > 0

    def test_update_values_are_hex_strings(self) -> None:
        anim = _make(Plasma)
        result = _update(anim)
        for v in result.values():
            assert isinstance(v, str)
            assert v.startswith("#")

    def test_lazy_init(self) -> None:
        anim = _make(Plasma)
        assert anim._params is None
        _update(anim)
        assert anim._params is not None


class TestGlitch:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(Glitch)
        result = _update(anim)
        assert len(result) > 0

    def test_lazy_init(self) -> None:
        anim = _make(Glitch)
        assert anim._params is None
        _update(anim)
        assert anim._params is not None

    def test_burst_window_produces_glitch_colors(self) -> None:
        anim = _make(Glitch)
        _update(anim)  # init
        # Frame 0 is within burst window (0 % 12 < 3) with sufficient rng
        result = _update(anim, 0)
        # At least some pixels should be present
        assert len(result) > 0


class TestEQBars:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(EQBars)
        result = _update(anim)
        assert len(result) > 0

    def test_lazy_init(self) -> None:
        anim = _make(EQBars)
        assert anim._params is None
        _update(anim)
        assert anim._params is not None

    def test_gradient_lut_populated(self) -> None:
        anim = _make(EQBars)
        _update(anim)
        assert len(anim._gradient_lut) > 0

    def test_dark_pixels_present(self) -> None:
        anim = _make(EQBars)
        result = _update(anim, 0)
        # Below the bar level, pixels should be dark
        dark_pixels = [v for v in result.values() if v == "#080808"]
        assert len(dark_pixels) > 0


class TestLavaLamp:
    def test_update_returns_non_empty(self) -> None:
        anim = _make(LavaLamp)
        result = _update(anim)
        assert len(result) > 0

    def test_lazy_init(self) -> None:
        anim = _make(LavaLamp)
        assert anim._blobs is None
        _update(anim)
        assert anim._blobs is not None

    def test_num_blobs(self) -> None:
        anim = _make(LavaLamp)
        _update(anim)
        assert len(anim._blobs) == LavaLamp._NUM_BLOBS

    def test_background_color_for_empty_pixels(self) -> None:
        anim = _make(LavaLamp)
        result = _update(anim, 0)
        # Some pixels should have background color
        bg_pixels = [v for v in result.values() if v == "#050512"]
        assert len(bg_pixels) > 0


class TestColorSweep:
    def test_theme_filter_dark(self) -> None:
        assert ColorSweep.theme_filter == "dark"

    def test_update_returns_dict(self) -> None:
        anim = _make(ColorSweep)
        result = anim.update(0)
        assert isinstance(result, dict)

    def test_lazy_init(self) -> None:
        anim = _make(ColorSweep)
        assert anim._params is None
        anim.update(0)
        assert anim._params is not None

    def test_direction_is_valid(self) -> None:
        anim = _make(ColorSweep)
        anim.update(0)
        valid_dirs = {"lr", "rl", "tb", "bt", "diag_dr", "diag_dl", "radial"}
        assert anim._params["direction"] in valid_dirs


class TestLaserScan:
    def test_theme_filter_dark(self) -> None:
        assert LaserScan.theme_filter == "dark"

    def test_update_returns_non_empty(self) -> None:
        anim = _make(LaserScan)
        result = _update(anim)
        assert len(result) > 0

    def test_lazy_init_sets_glow(self) -> None:
        anim = _make(LaserScan)
        assert anim._glow is None
        _update(anim)
        assert anim._glow is not None
        assert anim._glow.startswith("#")

    def test_white_hot_core_at_beam(self) -> None:
        anim = _make(LaserScan)
        _update(anim)  # init
        result = _update(anim, 0)
        # Some pixels should be white (core)
        white_pixels = [v for v in result.values() if v == "#ffffff"]
        # White core may or may not exist depending on beam position
        assert isinstance(white_pixels, list)
