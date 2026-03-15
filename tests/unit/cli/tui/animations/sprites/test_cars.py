"""Characterization tests for animations/sprites/cars.py."""

from __future__ import annotations

from teleclaude.cli.tui.animations.sprites.cars import (
    CAR_SPRITE,
    CAR_SPRITE_LEFT,
    CAR_SPRITE_RIGHT,
)
from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteGroup


class TestCarSpriteLeft:
    def test_is_composite_sprite(self) -> None:
        assert isinstance(CAR_SPRITE_LEFT, CompositeSprite)

    def test_has_layers(self) -> None:
        assert len(CAR_SPRITE_LEFT.layers) > 0

    def test_all_speed_weights_negative(self) -> None:
        # Left-facing car moves left (negative speeds)
        for speed, _ in CAR_SPRITE_LEFT.speed_weights:
            assert speed < 0

    def test_z_weights_present(self) -> None:
        assert len(CAR_SPRITE_LEFT.z_weights) > 0

    def test_y_weights_anchor_to_row_7(self) -> None:
        # Cars should anchor at row 7 (tab bar)
        for lo, hi, _ in CAR_SPRITE_LEFT.y_weights:
            assert lo == 7
            assert hi == 7

    def test_tick_returns_self(self) -> None:
        assert CAR_SPRITE_LEFT.tick(0) is CAR_SPRITE_LEFT


class TestCarSpriteRight:
    def test_is_composite_sprite(self) -> None:
        assert isinstance(CAR_SPRITE_RIGHT, CompositeSprite)

    def test_all_speed_weights_positive(self) -> None:
        # Right-facing car moves right (positive speeds)
        for speed, _ in CAR_SPRITE_RIGHT.speed_weights:
            assert speed > 0

    def test_z_weights_present(self) -> None:
        assert len(CAR_SPRITE_RIGHT.z_weights) > 0

    def test_y_weights_anchor_to_row_7(self) -> None:
        for lo, hi, _ in CAR_SPRITE_RIGHT.y_weights:
            assert lo == 7
            assert hi == 7


class TestCarSprite:
    def test_is_sprite_group(self) -> None:
        assert isinstance(CAR_SPRITE, SpriteGroup)

    def test_direction_none(self) -> None:
        # Car direction is None (randomized per spawn)
        assert CAR_SPRITE.direction is None

    def test_entries_include_both_directions(self) -> None:
        sprites = [s for s, _, _ in CAR_SPRITE.entries]
        assert CAR_SPRITE_LEFT in sprites
        assert CAR_SPRITE_RIGHT in sprites

    def test_weights_sum_to_one(self) -> None:
        total = sum(w for _, w, _ in CAR_SPRITE.entries)
        assert abs(total - 1.0) < 1e-6

    def test_pick_returns_valid_sprite(self) -> None:
        result = CAR_SPRITE.pick()
        assert result in (CAR_SPRITE_LEFT, CAR_SPRITE_RIGHT)
