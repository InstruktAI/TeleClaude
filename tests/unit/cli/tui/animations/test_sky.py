"""Characterization tests for animations/sky.py."""

from __future__ import annotations

from unittest.mock import patch

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animations.base import Z0, Z10, Z20, Z30, RenderBuffer
from teleclaude.cli.tui.animations.sky import GlobalSky
from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, SpriteLayer


def _palette() -> SpectrumPalette:
    return SpectrumPalette()


def _make_sky(dark_mode: bool = True, show_extra_motion: bool = False) -> GlobalSky:
    with patch("teleclaude.cli.tui.theme.is_dark_mode", return_value=dark_mode):
        sky = GlobalSky(
            palette=_palette(),
            is_big=True,
            duration_seconds=60.0,
            seed=42,
            show_extra_motion=show_extra_motion,
        )
        sky.dark_mode = dark_mode
    return sky


class TestGlobalSkyInit:
    def test_default_target_is_header(self) -> None:
        sky = _make_sky()

        assert sky.target == "header"

    def test_seeded_night_scene_populates_star_catalog(self) -> None:
        sky = _make_sky(dark_mode=True)

        assert len(sky.stars) == 150


class TestGlobalSkyUpdate:
    def test_update_returns_render_buffer(self) -> None:
        sky = _make_sky()

        assert isinstance(sky.update(0), RenderBuffer)

    def test_dark_mode_renders_dark_gradient_stars_and_celestial(self) -> None:
        sky = _make_sky(dark_mode=True)
        buffer = sky.update(0)

        assert buffer.layers[Z0][(0, 0)] == "#000000"
        assert buffer.layers[Z0][(0, 9)] == "#350065"
        assert len(buffer.layers[Z10]) > 0
        assert len(buffer.layers[Z20]) > 0

    def test_light_mode_renders_light_gradient_without_star_layer(self) -> None:
        sky = _make_sky(dark_mode=False)
        buffer = sky.update(0)

        assert buffer.layers[Z0][(0, 0)] == "#87ceeb"
        assert buffer.layers[Z0][(0, 9)] == "#daf3ff"
        assert Z10 not in buffer.layers or len(buffer.layers[Z10]) == 0
        assert len(buffer.layers[Z20]) > 0

    def test_theme_toggle_changes_visible_gradient_colors(self) -> None:
        sky = _make_sky(dark_mode=True)
        buffer = sky.update(0)
        dark_samples = (buffer.layers[Z0][(0, 0)], buffer.layers[Z0][(0, 9)])

        sky.dark_mode = False
        buffer = sky.update(1)
        light_samples = (buffer.layers[Z0][(0, 0)], buffer.layers[Z0][(0, 9)])

        assert dark_samples != light_samples
        assert light_samples == ("#87ceeb", "#daf3ff")


class TestGlobalSkyExtraMotion:
    def test_set_extra_motion_toggles_public_flag(self) -> None:
        sky = _make_sky(show_extra_motion=False)

        sky.set_extra_motion(True)
        assert sky.show_extra_motion is True

        sky.set_extra_motion(False)
        assert sky.show_extra_motion is False


class TestGlobalSkyForceSpawn:
    def test_force_spawn_custom_sprite_renders_visible_pixel(self) -> None:
        sky = _make_sky()
        sprite = CompositeSprite(
            layers=[SpriteLayer(color="#ffffff", positive=["X"])],
            z_weights=[(Z30, 1)],
            y_weights=[(0, 0, 1)],
            speed_fixed=(0.0, 0.0),
        )

        with patch.object(sky.rng, "randint", side_effect=[0, 11]):
            sky.force_spawn(sprite)

        buffer = sky.update(0)

        assert buffer.layers[Z30][(0, 0)] == "#ffffffX"

    def test_force_spawn_entity_alias_uses_random_pool(self) -> None:
        sky = _make_sky()
        sprite = CompositeSprite(
            layers=[SpriteLayer(color="#00ff00", positive=["Y"])],
            z_weights=[(Z30, 1)],
            y_weights=[(0, 0, 1)],
            speed_fixed=(0.0, 0.0),
        )

        with (
            patch("teleclaude.cli.tui.animations.sprites.get_sky_entities", return_value=[sprite]),
            patch.object(sky.rng, "randint", side_effect=[0, 11]),
        ):
            sky.force_spawn_entity()

        buffer = sky.update(0)

        assert buffer.layers[Z30][(0, 0)] == "#00ff00Y"
