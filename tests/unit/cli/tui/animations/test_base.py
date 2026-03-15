"""Characterization tests for animations/base.py."""

from __future__ import annotations

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animations.base import (
    Z0,
    Z10,
    Z20,
    Z30,
    Z40,
    Z50,
    Z60,
    Z70,
    Z80,
    Z90,
    Animation,
    RenderBuffer,
    Spectrum,
    render_sprite,
)
from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteLayer

# ---------------------------------------------------------------------------
# Z-level constants
# ---------------------------------------------------------------------------


class TestZLevels:
    def test_z_levels_ordered(self) -> None:
        assert Z0 < Z10 < Z20 < Z30 < Z40 < Z50 < Z60 < Z70 < Z80 < Z90

    def test_z_levels_values(self) -> None:
        assert Z0 == 0
        assert Z50 == 50
        assert Z90 == 90


# ---------------------------------------------------------------------------
# Spectrum
# ---------------------------------------------------------------------------


class TestSpectrum:
    def test_single_stop_returns_color(self) -> None:
        s = Spectrum(["#ff0000"])
        result = s.get_color(0.0)
        assert result.startswith("#")
        assert len(result) == 7

    def test_two_stops_endpoint_zero(self) -> None:
        s = Spectrum(["#ff0000", "#0000ff"])
        result = s.get_color(0.0)
        assert result.startswith("#")

    def test_two_stops_endpoint_one(self) -> None:
        s = Spectrum(["#ff0000", "#0000ff"])
        result = s.get_color(1.0)
        assert result.startswith("#")

    def test_clamps_below_zero(self) -> None:
        s = Spectrum(["#ff0000", "#0000ff"])
        assert s.get_color(-0.5) == s.get_color(0.0)

    def test_clamps_above_one(self) -> None:
        s = Spectrum(["#ff0000", "#0000ff"])
        assert s.get_color(1.5) == s.get_color(1.0)

    def test_empty_stops_returns_black(self) -> None:
        s = Spectrum([])
        assert s.get_color(0.5) == "#000000"


# ---------------------------------------------------------------------------
# RenderBuffer
# ---------------------------------------------------------------------------


class TestRenderBuffer:
    def test_add_and_retrieve_pixel(self) -> None:
        buf = RenderBuffer()
        buf.add_pixel(Z50, 5, 3, "#ff0000")
        assert buf.layers[Z50][(5, 3)] == "#ff0000"

    def test_add_creates_layer(self) -> None:
        buf = RenderBuffer()
        assert Z50 not in buf.layers
        buf.add_pixel(Z50, 0, 0, "#ffffff")
        assert Z50 in buf.layers

    def test_clear_removes_all_pixels(self) -> None:
        buf = RenderBuffer()
        buf.add_pixel(Z50, 0, 0, "#ffffff")
        buf.add_pixel(Z10, 1, 1, "#ff0000")
        buf.clear()
        for layer in buf.layers.values():
            assert len(layer) == 0

    def test_clear_layer_only_clears_target_z(self) -> None:
        buf = RenderBuffer()
        buf.add_pixel(Z50, 0, 0, "#ffffff")
        buf.add_pixel(Z10, 1, 1, "#ff0000")
        buf.clear_layer(Z50)
        assert len(buf.layers[Z50]) == 0
        assert (1, 1) in buf.layers[Z10]

    def test_overwrite_pixel(self) -> None:
        buf = RenderBuffer()
        buf.add_pixel(Z50, 0, 0, "#ff0000")
        buf.add_pixel(Z50, 0, 0, "#00ff00")
        assert buf.layers[Z50][(0, 0)] == "#00ff00"


# ---------------------------------------------------------------------------
# render_sprite
# ---------------------------------------------------------------------------


class TestRenderSprite:
    def test_plain_sprite_writes_non_space(self) -> None:
        buf = RenderBuffer()
        sprite = ["ab", "cd"]
        render_sprite(buf, Z50, 0, 0, sprite, 10, 10)
        assert (0, 0) in buf.layers[Z50]
        assert (1, 0) in buf.layers[Z50]

    def test_spaces_not_written(self) -> None:
        buf = RenderBuffer()
        sprite = ["a "]
        render_sprite(buf, Z50, 0, 0, sprite, 10, 10)
        assert (0, 0) in buf.layers[Z50]
        assert (1, 0) not in buf.layers.get(Z50, {})

    def test_out_of_bounds_clipped(self) -> None:
        buf = RenderBuffer()
        sprite = ["abc"]
        render_sprite(buf, Z50, 8, 0, sprite, 10, 10)
        # x=8,9 in bounds; x=10 out
        assert (8, 0) in buf.layers[Z50]
        assert (9, 0) in buf.layers[Z50]
        assert (10, 0) not in buf.layers.get(Z50, {})

    def test_negative_y_rows_skipped(self) -> None:
        buf = RenderBuffer()
        sprite = ["ab", "cd"]
        render_sprite(buf, Z50, 0, -1, sprite, 10, 10)
        # row 0 of sprite is at y=-1 (skip), row 1 at y=0 (keep)
        assert (0, 0) in buf.layers[Z50]
        assert (0, -1) not in buf.layers.get(Z50, {})

    def test_composite_sprite_writes_color_encoded_pixel(self) -> None:
        buf = RenderBuffer()
        sprite = CompositeSprite(
            layers=[SpriteLayer(color="#ff0000", positive=["X"])],
        )

        render_sprite(buf, Z50, 0, 0, sprite, 10, 10)

        assert buf.layers[Z50][(0, 0)] == "#ff0000X"

    def test_composite_sprite_negative_overlay_encodes_foreground_and_background(self) -> None:
        buf = RenderBuffer()
        sprite = CompositeSprite(
            layers=[
                SpriteLayer(color="#ff0000", positive=["X"]),
                SpriteLayer(color="#00ff00", negative=["o"]),
            ],
        )

        render_sprite(buf, Z50, 0, 0, sprite, 10, 10)

        assert buf.layers[Z50][(0, 0)] == "#ff0000#00ff00o"


# ---------------------------------------------------------------------------
# Animation base class helpers
# ---------------------------------------------------------------------------


class _ConcreteAnimation(Animation):
    """Minimal concrete subclass for testing Animation helpers."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        return {}


class TestAnimationHelpers:
    def _make_anim(self, duration_seconds: float = 10.0, speed_ms: int = 100) -> _ConcreteAnimation:
        palette = SpectrumPalette()
        return _ConcreteAnimation(
            palette=palette,
            is_big=True,
            duration_seconds=duration_seconds,
            speed_ms=speed_ms,
            seed=42,
        )

    def test_duration_frames_calculated(self) -> None:
        anim = self._make_anim(duration_seconds=10.0, speed_ms=100)
        # 10s * 1000ms/s / 100ms = 100 frames
        assert anim.duration_frames == 100

    def test_is_complete_false_before_end(self) -> None:
        anim = self._make_anim()
        assert not anim.is_complete(0)
        assert not anim.is_complete(50)

    def test_is_complete_true_at_end(self) -> None:
        anim = self._make_anim()
        assert anim.is_complete(100)
        assert anim.is_complete(200)

    def test_default_target_banner_when_big(self) -> None:
        anim = self._make_anim()
        assert anim.target == "banner"

    def test_default_target_logo_when_small(self) -> None:
        palette = SpectrumPalette()
        anim = _ConcreteAnimation(palette=palette, is_big=False, duration_seconds=5.0, seed=0)
        assert anim.target == "logo"

    def test_linear_surge_zero_outside_width(self) -> None:
        anim = self._make_anim()
        assert anim.linear_surge(10.0, 5.0, 3.0) == 0.0

    def test_linear_surge_max_at_center(self) -> None:
        anim = self._make_anim()
        assert anim.linear_surge(5.0, 5.0, 3.0) == 1.0

    def test_radial_field_zero_outside_radius(self) -> None:
        anim = self._make_anim()
        assert anim.radial_field(20, 20, 5.0, 5.0, 5.0) == 0.0

    def test_radial_field_max_at_center(self) -> None:
        anim = self._make_anim()
        assert anim.radial_field(5, 5, 5.0, 5.0, 10.0) == 1.0

    def test_get_modulation_returns_float_in_range(self) -> None:
        anim = self._make_anim()
        for frame in range(100):
            m = anim.get_modulation(frame)
            assert 0.4 <= m <= 1.1, f"modulation {m} out of range at frame {frame}"

    def test_enforce_vibrancy_returns_hex(self) -> None:
        anim = self._make_anim()
        result = anim.enforce_vibrancy("#888888")
        assert result.startswith("#")
        assert len(result) == 7

    def test_get_electric_neon_returns_hex(self) -> None:
        anim = self._make_anim()
        result = anim.get_electric_neon("#ff0000")
        assert result.startswith("#")
        assert len(result) == 7

    def test_get_contrast_safe_color_dark_mode_boosts_dark(self) -> None:
        anim = self._make_anim()
        anim.dark_mode = True
        # Very dark color should be boosted
        result = anim.get_contrast_safe_color("#050505")
        from teleclaude.cli.tui.color_utils import hex_to_rgb

        r, g, b = hex_to_rgb(result)
        avg = (r + g + b) / 3
        assert avg >= 100

    def test_get_contrast_safe_color_light_mode_passthrough(self) -> None:
        anim = self._make_anim()
        anim.dark_mode = False
        result = anim.get_contrast_safe_color("#050505")
        assert result == "#050505"

    def test_seed_deterministic_rng(self) -> None:
        palette = SpectrumPalette()
        a1 = _ConcreteAnimation(palette=palette, is_big=True, duration_seconds=5.0, seed=123)
        a2 = _ConcreteAnimation(palette=palette, is_big=True, duration_seconds=5.0, seed=123)
        assert a1.rng.random() == a2.rng.random()
