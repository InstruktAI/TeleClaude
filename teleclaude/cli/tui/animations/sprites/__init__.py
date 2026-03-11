"""AnimatedSprite definitions for TUI sky animations."""

from teleclaude.cli.tui.animations.sprites.birds import BIRD_FLOCK
from teleclaude.cli.tui.animations.sprites.cars import CAR_SPRITE
from teleclaude.cli.tui.animations.sprites.celestial import MOON_SPRITE, SUN_SPRITE
from teleclaude.cli.tui.animations.sprites.clouds import CLOUDS_CLEAR, CLOUDS_CLOUDY, CLOUDS_FAIR, CLOUDS_OVERCAST
from teleclaude.cli.tui.animations.sprites.composite import AnimatedSprite, CompositeSprite, SpriteGroup, SpriteLayer
from teleclaude.cli.tui.animations.sprites.ufo import UFO_SPRITE

__all__ = [
    "BIRD_FLOCK",
    "CAR_SPRITE",
    "MOON_SPRITE",
    "SUN_SPRITE",
    "UFO_SPRITE",
    "AnimatedSprite",
    "CompositeSprite",
    "SpriteGroup",
    "SpriteLayer",
    "get_sky_entities",
    "get_sprite_groups",
    "get_weather_clouds",
]


def get_sky_entities() -> list[CompositeSprite | AnimatedSprite]:
    """Collect all standalone sprites that declare z_weights (sky entities).

    Iterates over everything exported from this package. Drop a new sprite
    file in the folder, import it here, and it automatically becomes a
    spawnable sky entity -- no changes to the sky animation code.
    """
    import sys

    module = sys.modules[__name__]
    return [
        obj
        for name in __all__
        if isinstance(obj := getattr(module, name, None), (CompositeSprite, AnimatedSprite)) and obj.z_weights
    ]


def get_sprite_groups() -> list[SpriteGroup]:
    """Collect all SpriteGroup instances exported from this package."""
    import sys

    module = sys.modules[__name__]
    return [obj for name in __all__ if isinstance(obj := getattr(module, name, None), SpriteGroup)]


# Weather name → cloud SpriteGroup mapping
_WEATHER_CLOUDS: dict[str, SpriteGroup] = {
    "clear": CLOUDS_CLEAR,
    "fair": CLOUDS_FAIR,
    "cloudy": CLOUDS_CLOUDY,
    "overcast": CLOUDS_OVERCAST,
}


def get_weather_clouds(weather: str) -> SpriteGroup:
    """Return the cloud SpriteGroup for a weather state."""
    return _WEATHER_CLOUDS.get(weather, CLOUDS_CLEAR)
