"""Characterization tests for animations/sprites/ufo.py."""

from __future__ import annotations

from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteGroup
from teleclaude.cli.tui.animations.sprites.ufo import UFO_SPRITE, UFO_SPRITE_1


class TestUfoSprite1:
    def test_is_composite_sprite(self) -> None:
        assert isinstance(UFO_SPRITE_1, CompositeSprite)

    def test_has_three_layers(self) -> None:
        # UFO has body, top dome, and lights layers
        assert len(UFO_SPRITE_1.layers) == 3

    def test_has_z_weights(self) -> None:
        assert len(UFO_SPRITE_1.z_weights) > 0

    def test_y_weights_cover_full_range(self) -> None:
        # UFO can appear anywhere in the sky (y 0-7)
        for lo, hi, _ in UFO_SPRITE_1.y_weights:
            assert lo >= 0
            assert hi <= 9

    def test_speed_weights_include_zero(self) -> None:
        speeds = [s for s, _ in UFO_SPRITE_1.speed_weights]
        assert 0 in speeds

    def test_speed_weights_include_both_signs(self) -> None:
        speeds = [s for s, _ in UFO_SPRITE_1.speed_weights]
        assert any(s > 0 for s in speeds)
        assert any(s < 0 for s in speeds)

    def test_tick_returns_self(self) -> None:
        assert UFO_SPRITE_1.tick(0) is UFO_SPRITE_1

    def test_first_layer_color_grey(self) -> None:
        assert UFO_SPRITE_1.layers[0].color == "#bbbbbb"

    def test_last_layer_color_white(self) -> None:
        assert UFO_SPRITE_1.layers[2].color == "#ffffff"


class TestUfoSpriteGroup:
    def test_is_sprite_group(self) -> None:
        assert isinstance(UFO_SPRITE, SpriteGroup)

    def test_entries_include_ufo_sprite_1(self) -> None:
        sprites = [s for s, _, _ in UFO_SPRITE.entries]
        assert UFO_SPRITE_1 in sprites

    def test_weights_sum_to_one(self) -> None:
        total = sum(w for _, w, _ in UFO_SPRITE.entries)
        assert abs(total - 1.0) < 1e-6

    def test_count_range_allows_zero(self) -> None:
        # UFO is rare — min count can be 0
        for _, _, (lo, hi) in UFO_SPRITE.entries:
            assert lo >= 0
            assert hi >= lo

    def test_pick_returns_ufo_sprite_1(self) -> None:
        # Only one entry with weight 1.0
        result = UFO_SPRITE.pick()
        assert result is UFO_SPRITE_1
