"""Characterization tests for animations/sprites/celestial.py."""

from __future__ import annotations

from teleclaude.cli.tui.animations.sprites.celestial import MOON_SPRITE, SUN_SPRITE
from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite


class TestMoonSprite:
    def test_is_composite_sprite(self) -> None:
        assert isinstance(MOON_SPRITE, CompositeSprite)

    def test_has_exactly_one_layer(self) -> None:
        assert len(MOON_SPRITE.layers) == 1

    def test_layer_color_is_white(self) -> None:
        layer = MOON_SPRITE.layers[0]
        assert layer.color == "#FFFFFF"

    def test_layer_has_positive_rows(self) -> None:
        layer = MOON_SPRITE.layers[0]
        assert layer.positive is not None
        assert len(layer.positive) > 0

    def test_layer_has_negative_rows(self) -> None:
        layer = MOON_SPRITE.layers[0]
        assert layer.negative is not None
        assert len(layer.negative) > 0

    def test_tick_returns_self(self) -> None:
        assert MOON_SPRITE.tick(0) is MOON_SPRITE
        assert MOON_SPRITE.tick(10) is MOON_SPRITE

    def test_positive_rows_count_matches_negative(self) -> None:
        layer = MOON_SPRITE.layers[0]
        assert len(layer.positive) == len(layer.negative)

    def test_resolve_colors_returns_same(self) -> None:
        # No list colors, so resolve_colors returns self
        resolved = MOON_SPRITE.resolve_colors()
        assert resolved is MOON_SPRITE


class TestSunSprite:
    def test_is_composite_sprite(self) -> None:
        assert isinstance(SUN_SPRITE, CompositeSprite)

    def test_has_exactly_one_layer(self) -> None:
        assert len(SUN_SPRITE.layers) == 1

    def test_layer_color_is_gold(self) -> None:
        layer = SUN_SPRITE.layers[0]
        assert layer.color == "#FFD700"

    def test_same_shape_as_moon(self) -> None:
        moon_layer = MOON_SPRITE.layers[0]
        sun_layer = SUN_SPRITE.layers[0]
        # Same rows, different color
        assert moon_layer.positive == sun_layer.positive
        assert moon_layer.negative == sun_layer.negative

    def test_tick_returns_self(self) -> None:
        assert SUN_SPRITE.tick(0) is SUN_SPRITE

    def test_color_differs_from_moon(self) -> None:
        assert SUN_SPRITE.layers[0].color != MOON_SPRITE.layers[0].color
