"""Characterization tests for animations/sprites/birds.py."""

from __future__ import annotations

from teleclaude.cli.tui.animations.sprites.birds import (
    BIRD_FLOCK,
    BIRD_LARGE,
    BIRD_LARGE_FRONT,
    BIRD_SMALL,
)
from teleclaude.cli.tui.animations.sprites.composite import AnimatedSprite, SpriteGroup


class TestBirdSmall:
    def test_is_animated_sprite(self) -> None:
        assert isinstance(BIRD_SMALL, AnimatedSprite)

    def test_two_frames(self) -> None:
        assert len(BIRD_SMALL.frames) == 2

    def test_frames_are_plain_lists(self) -> None:
        for frame in BIRD_SMALL.frames:
            assert isinstance(frame, list)

    def test_theme_is_light(self) -> None:
        assert BIRD_SMALL.theme == "light"

    def test_z_weights_present(self) -> None:
        assert len(BIRD_SMALL.z_weights) > 0

    def test_y_weights_present(self) -> None:
        assert len(BIRD_SMALL.y_weights) > 0

    def test_tick_cycles_frames(self) -> None:
        f0 = BIRD_SMALL.tick(0)
        f1 = BIRD_SMALL.tick(1)
        f2 = BIRD_SMALL.tick(2)
        assert f0 == f2  # wraps
        assert f0 != f1


class TestBirdLarge:
    def test_is_animated_sprite(self) -> None:
        assert isinstance(BIRD_LARGE, AnimatedSprite)

    def test_two_frames(self) -> None:
        assert len(BIRD_LARGE.frames) == 2

    def test_theme_is_light(self) -> None:
        assert BIRD_LARGE.theme == "light"

    def test_frames_are_composite_sprites(self) -> None:
        from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite

        for frame in BIRD_LARGE.frames:
            assert isinstance(frame, CompositeSprite)

    def test_tick_returns_renderable(self) -> None:
        frame = BIRD_LARGE.tick(0)
        assert frame is not None


class TestBirdLargeFront:
    def test_is_animated_sprite(self) -> None:
        assert isinstance(BIRD_LARGE_FRONT, AnimatedSprite)

    def test_higher_z_than_bird_large(self) -> None:
        front_z_levels = {z for z, _ in BIRD_LARGE_FRONT.z_weights}
        large_z_levels = {z for z, _ in BIRD_LARGE.z_weights}
        # Front should have higher z levels (closer to viewer)
        assert max(front_z_levels) > max(large_z_levels)

    def test_y_weights_different_from_large(self) -> None:
        assert BIRD_LARGE_FRONT.y_weights != BIRD_LARGE.y_weights


class TestBirdFlock:
    def test_is_sprite_group(self) -> None:
        assert isinstance(BIRD_FLOCK, SpriteGroup)

    def test_entries_non_empty(self) -> None:
        assert len(BIRD_FLOCK.entries) > 0

    def test_weights_sum_to_one(self) -> None:
        total = sum(w for _, w, _ in BIRD_FLOCK.entries)
        assert abs(total - 1.0) < 1e-6

    def test_bird_small_in_flock(self) -> None:
        sprites = [s for s, _, _ in BIRD_FLOCK.entries]
        assert BIRD_SMALL in sprites

    def test_bird_large_in_flock(self) -> None:
        sprites = [s for s, _, _ in BIRD_FLOCK.entries]
        assert BIRD_LARGE in sprites
