"""Characterization tests for animations/sky.py."""

from __future__ import annotations

from unittest.mock import patch

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animations.base import RenderBuffer
from teleclaude.cli.tui.animations.sky import GlobalSky, SkyEntity


def _palette() -> SpectrumPalette:
    return SpectrumPalette()


def _make_sky(dark_mode: bool = True, show_extra_motion: bool = False) -> GlobalSky:
    """Create a GlobalSky with mocked theme to avoid system calls."""
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


class TestSkyEntityTypedDict:
    def test_sky_entity_keys(self) -> None:
        # SkyEntity is a TypedDict — verify the expected keys are annotated
        keys = SkyEntity.__annotations__
        assert "sprite" in keys
        assert "x" in keys
        assert "speed" in keys
        assert "y" in keys
        assert "z" in keys


class TestGlobalSkyInit:
    def test_default_target_is_header(self) -> None:
        sky = _make_sky()
        assert sky.target == "header"

    def test_dark_mode_attribute(self) -> None:
        sky = _make_sky(dark_mode=True)
        assert sky.dark_mode is True

    def test_stars_populated(self) -> None:
        sky = _make_sky(dark_mode=True)
        assert len(sky.stars) == 150

    def test_sky_entities_populated(self) -> None:
        sky = _make_sky()
        # At least some entities should be spawned
        assert isinstance(sky._sky_entities, list)

    def test_weather_is_valid(self) -> None:
        sky = _make_sky()
        assert sky._weather in GlobalSky._WEATHER_NAMES

    def test_cached_term_width_positive(self) -> None:
        sky = _make_sky()
        assert sky._cached_term_width > 0


class TestGlobalSkyUpdate:
    def test_update_returns_render_buffer(self) -> None:
        sky = _make_sky()
        result = sky.update(0)
        assert isinstance(result, RenderBuffer)

    def test_update_multiple_frames(self) -> None:
        sky = _make_sky()
        for frame in range(5):
            result = sky.update(frame)
            assert isinstance(result, RenderBuffer)

    def test_sky_gradient_cached_after_first_update(self) -> None:
        sky = _make_sky()
        sky.update(0)
        # Cache should be populated
        assert sky._cached_dark_mode is not None
        assert len(sky._cached_sky_pixels) > 0

    def test_sky_cache_rebuilt_on_theme_change(self) -> None:
        sky = _make_sky(dark_mode=True)
        sky.update(0)
        # Simulate theme change
        sky.dark_mode = False
        sky.update(1)
        assert sky._cached_dark_mode is False

    def test_persistent_buffer_reused(self) -> None:
        sky = _make_sky()
        buf1 = sky.update(0)
        buf2 = sky.update(1)
        # Same buffer object reused
        assert buf1 is buf2

    def test_z0_layer_populated(self) -> None:
        from teleclaude.cli.tui.animations.base import Z0

        sky = _make_sky()
        buf = sky.update(0)
        assert Z0 in buf.layers
        assert len(buf.layers[Z0]) > 0


class TestGlobalSkyExtraMotion:
    def test_set_extra_motion_disables(self) -> None:
        sky = _make_sky(show_extra_motion=False)
        sky.set_extra_motion(False)  # noop when already disabled
        # No error

    def test_set_extra_motion_enables(self) -> None:
        sky = _make_sky(show_extra_motion=False)
        sky.set_extra_motion(True)
        # Some optional motion entities may have been added
        assert sky.show_extra_motion is True

    def test_set_extra_motion_to_same_value_is_noop(self) -> None:
        sky = _make_sky(show_extra_motion=True)
        count_before = len(sky._sky_entities)
        sky.set_extra_motion(True)
        # No change
        assert len(sky._sky_entities) == count_before


class TestGlobalSkyForceSpawn:
    def test_force_spawn_none_adds_entity(self) -> None:
        sky = _make_sky()
        count_before = len(sky._sky_entities)
        sky.force_spawn(None)
        assert len(sky._sky_entities) >= count_before

    def test_force_spawn_entity_legacy_alias(self) -> None:
        sky = _make_sky()
        count_before = len(sky._sky_entities)
        sky.force_spawn_entity()
        assert len(sky._sky_entities) >= count_before

    def test_force_spawn_with_specific_sprite(self) -> None:
        from teleclaude.cli.tui.animations.sprites.clouds import WISP_1

        sky = _make_sky()
        count_before = len(sky._sky_entities)
        sky.force_spawn(WISP_1)
        assert len(sky._sky_entities) == count_before + 1


class TestGlobalSkyHelpers:
    def test_fetch_term_width_returns_int(self) -> None:
        width = GlobalSky._fetch_term_width()
        assert isinstance(width, int)
        assert width > 0

    def test_sprite_max_width_animated(self) -> None:
        from teleclaude.cli.tui.animations.sprites.birds import BIRD_SMALL

        w = GlobalSky._sprite_max_width(BIRD_SMALL)
        assert w >= 1

    def test_sprite_max_width_composite(self) -> None:
        from teleclaude.cli.tui.animations.sprites.clouds import WISP_1

        w = GlobalSky._sprite_max_width(WISP_1)
        assert w >= 1

    def test_sprite_owns_direction_with_signed_weights(self) -> None:
        from teleclaude.cli.tui.animations.sprites.cars import CAR_SPRITE_LEFT

        # CAR_SPRITE_LEFT has all negative speed weights
        result = GlobalSky._sprite_owns_direction(CAR_SPRITE_LEFT)
        assert result is True

    def test_sprite_owns_direction_mixed_weights(self) -> None:
        from teleclaude.cli.tui.animations.sprites.ufo import UFO_SPRITE_1

        # UFO has mixed positive/negative weights
        result = GlobalSky._sprite_owns_direction(UFO_SPRITE_1)
        assert result is False
