"""Characterization tests for animations/sprites/composite.py."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.animations.sprites.composite import (
    AnimatedSprite,
    CompositeSprite,
    SpriteGroup,
    SpriteLayer,
)


class TestSpriteLayer:
    def test_default_color_is_white(self) -> None:
        layer = SpriteLayer()
        assert layer.color == "#ffffff"

    def test_positive_and_negative_default_none(self) -> None:
        layer = SpriteLayer()
        assert layer.positive is None
        assert layer.negative is None

    def test_custom_color(self) -> None:
        layer = SpriteLayer(color="#ff0000")
        assert layer.color == "#ff0000"

    def test_list_color(self) -> None:
        colors = ["#ff0000", "#00ff00"]
        layer = SpriteLayer(color=colors)
        assert layer.color == colors


class TestCompositeSprite:
    def _make_sprite(self) -> CompositeSprite:
        return CompositeSprite(
            layers=[SpriteLayer(color="#ffffff", positive=["ab", "cd"])],
            z_weights=[(50, 100)],
            y_weights=[(0, 5, 100)],
            speed_weights=[(0.5, 100)],
        )

    def test_layers_stored(self) -> None:
        sprite = self._make_sprite()
        assert len(sprite.layers) == 1

    def test_tick_returns_self(self) -> None:
        sprite = self._make_sprite()
        assert sprite.tick(0) is sprite
        assert sprite.tick(99) is sprite

    def test_resolve_colors_no_list_returns_self(self) -> None:
        sprite = self._make_sprite()
        resolved = sprite.resolve_colors()
        assert resolved is sprite

    def test_resolve_colors_with_list_picks_one(self) -> None:
        sprite = CompositeSprite(
            layers=[SpriteLayer(color=["#ff0000", "#00ff00"], positive=["ab"])],
            z_weights=[(50, 100)],
        )
        resolved = sprite.resolve_colors()
        assert isinstance(resolved.layers[0].color, str)
        assert resolved.layers[0].color in ("#ff0000", "#00ff00")

    def test_speed_fixed_and_non_default_weights_raises(self) -> None:
        with pytest.raises(ValueError):
            CompositeSprite(
                layers=[SpriteLayer()],
                speed_weights=[(0.5, 100)],
                speed_fixed=(0.1, 1.0),
            )

    def test_frozen_dataclass(self) -> None:
        sprite = self._make_sprite()
        with pytest.raises((AttributeError, TypeError)):
            sprite.layers = []


class TestAnimatedSprite:
    def _make_sprite(self) -> AnimatedSprite:
        return AnimatedSprite(
            frames=[["ab"], ["cd"]],
            z_weights=[(50, 100)],
            y_weights=[(0, 5, 100)],
            speed_weights=[(0.5, 100)],
        )

    def test_tick_cycles_frames(self) -> None:
        sprite = self._make_sprite()
        assert sprite.tick(0) == ["ab"]
        assert sprite.tick(1) == ["cd"]
        assert sprite.tick(2) == ["ab"]  # wraps

    def test_speed_fixed_and_non_default_weights_raises(self) -> None:
        with pytest.raises(ValueError):
            AnimatedSprite(
                frames=[["ab"]],
                speed_weights=[(0.5, 100)],
                speed_fixed=(0.1, 1.0),
            )

    def test_frozen_dataclass(self) -> None:
        sprite = self._make_sprite()
        with pytest.raises((AttributeError, TypeError)):
            sprite.frames = []


class TestSpriteGroup:
    def test_weights_must_sum_to_one(self) -> None:
        sprite = CompositeSprite(layers=[SpriteLayer()])
        with pytest.raises(ValueError):
            SpriteGroup(entries=[(sprite, 0.5, (0, 1))])  # sum = 0.5

    def test_count_range_invalid_raises(self) -> None:
        sprite = CompositeSprite(layers=[SpriteLayer()])
        with pytest.raises(ValueError):
            SpriteGroup(entries=[(sprite, 1.0, (5, 1))])  # lo > hi

    def test_pick_returns_entry(self) -> None:
        sprite = CompositeSprite(layers=[SpriteLayer()])
        group = SpriteGroup(entries=[(sprite, 1.0, (1, 1))])
        result = group.pick()
        assert result is sprite

    def test_pick_weighted_selection(self) -> None:
        s1 = CompositeSprite(layers=[SpriteLayer(color="#ff0000")])
        s2 = CompositeSprite(layers=[SpriteLayer(color="#00ff00")])
        group = SpriteGroup(entries=[(s1, 0.5, (1, 1)), (s2, 0.5, (1, 1))])
        # Both sprites are valid picks
        result = group.pick()
        assert result in (s1, s2)

    def test_negative_count_raises(self) -> None:
        sprite = CompositeSprite(layers=[SpriteLayer()])
        with pytest.raises(ValueError):
            SpriteGroup(entries=[(sprite, 1.0, (-1, 1))])
