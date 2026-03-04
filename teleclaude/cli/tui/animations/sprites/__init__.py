"""AnimatedSprite definitions for TUI sky animations."""

from teleclaude.cli.tui.animations.sprites.birds import BIRD_FLOCK
from teleclaude.cli.tui.animations.sprites.celestial import MOON_SPRITE, SUN_SPRITE
from teleclaude.cli.tui.animations.sprites.clouds import CLOUD_SPRITES_FAR, CLOUD_SPRITES_MID, CLOUD_SPRITES_NEAR
from teleclaude.cli.tui.animations.sprites.composite import AnimatedSprite, CompositeSprite, SpriteGroup, SpriteLayer
from teleclaude.cli.tui.animations.sprites.ufo import UFO_SPRITE

__all__ = [
    "BIRD_FLOCK",
    "CLOUD_SPRITES_FAR",
    "CLOUD_SPRITES_MID",
    "CLOUD_SPRITES_NEAR",
    "CompositeSprite",
    "get_sky_entities",
    "get_sprite_groups",
    "MOON_SPRITE",
    "AnimatedSprite",
    "SpriteGroup",
    "SpriteLayer",
    "SUN_SPRITE",
    "UFO_SPRITE",
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
