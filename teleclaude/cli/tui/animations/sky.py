"""GlobalSky animation — background sky canvas with day/night cycles."""

from __future__ import annotations

import math
import shutil
import time
from typing import TypedDict

from teleclaude.cli.tui.animations.base import Z0, Z10, Z20, Animation, RenderBuffer, render_sprite
from teleclaude.cli.tui.animations.sprites import MOON_SPRITE, SUN_SPRITE
from teleclaude.cli.tui.animations.sprites.composite import AnimatedSprite, CompositeSprite, SpriteGroup


class SkyEntity(TypedDict):
    """A single sky entity managed by GlobalSky."""

    sprite: CompositeSprite | AnimatedSprite
    sprite_w: int
    x: float  # cumulative fractional position
    speed: float
    target_speed: float
    y: int
    z: int
    next_speed_change: int
    fixed_speed: bool
    optional_motion: bool


class GlobalSky(Animation):
    """TC20: Global background canvas with Day/Night physical states.
    Paints the entire header area (Z-0) including margins.
    Dynamic weather system with parallax clouds at weighted Z-levels.
    Quarter celestial (sun/moon) anchored at top-right corner.
    UFO as rare sky entity with weighted depth.
    """

    _WEATHER_NAMES = ["clear", "fair", "cloudy", "overcast"]
    _WEATHER_WEIGHTS = [30, 35, 25, 10]

    # Sky gradient: top row = base, bottom row = target, linear interpolation between
    _SKY_BASE_DARK = "#000000"
    _SKY_TARGET_DARK = "#350065"  # lighter purple at bottom
    _SKY_BASE_LIGHT = "#87CEEB"
    _SKY_TARGET_LIGHT = "#DAF3FF"  # lighter blue at bottom

    def __init__(self, *args, show_extra_motion: bool = True, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs.setdefault("target", "header")
        super().__init__(*args, **kwargs)
        self.show_extra_motion = show_extra_motion
        self.width = 400
        self.height = 10
        self._all_pixels = [(x, y) for y in range(self.height) for x in range(self.width)]

        # Pre-computed sky gradient caches (avoid 4000 interpolations per frame)
        self._cached_dark_mode: bool | None = None
        self._cached_sky_pixels: list[tuple[int, int, int, str]] = []  # (z, x, y, color)

        # Cached terminal width — refreshed every ~100 frames instead of every frame
        self._cached_term_width: int = self._fetch_term_width()
        self._term_width_frame: int = 0

        # Stars — weighted toward tiny dots; big sparkles are rare
        _star_types = ["\u00b7", ".", "+", "\u2726", "*"]  # ·  .  +  ✦  *
        _star_weights = [50, 20, 15, 10, 5]
        self.stars = []
        for _ in range(150):
            self.stars.append(
                {
                    "pos": (self.rng.randint(0, self.width - 1), self.rng.randint(0, self.height - 1)),
                    "char": self.rng.choices(_star_types, weights=_star_weights, k=1)[0],
                    "phase": self.rng.random() * math.pi * 2,
                    "speed": 0.010 + self.rng.random() * 0.018,
                }
            )

        # Weather system — weather determines which cloud group is active
        self._weather = self.rng.choices(self._WEATHER_NAMES, weights=self._WEATHER_WEIGHTS, k=1)[0]
        self._next_weather_change = time.time() + self.rng.uniform(30 * 60, 120 * 60)

        # Sky entities — all sprites (clouds, birds, UFO, etc.) via the sprite system
        self._sky_entities: list[SkyEntity] = self._spawn_initial_entities()

    @staticmethod
    def _fetch_term_width() -> int:
        try:
            return shutil.get_terminal_size().columns
        except Exception:
            return 200

    def _pick_z_level(self, weights: list[tuple[int, int]]) -> int:
        """Pick a Z-level from a weighted distribution."""
        levels, wts = zip(*weights)
        return self.rng.choices(levels, weights=wts, k=1)[0]

    def _theme_matches(self, sprite: object, group_theme: str | None = None) -> bool:
        """Check if a sprite matches the current mode.

        group_theme overrides per-sprite theme when set.
        Uses is_dark_mode() directly because self.dark_mode defaults to True
        in Animation.__init__ and isn't updated until play() runs — after
        _spawn_initial_entities has already executed.
        """
        from teleclaude.cli.tui.theme import is_dark_mode

        theme = group_theme if group_theme is not None else getattr(sprite, "theme", None)
        if theme is None:
            return True
        return theme == ("dark" if is_dark_mode() else "light")

    def _spawn_group_entities(
        self,
        group: SpriteGroup,
        entities: list[SkyEntity],
        *,
        optional_motion: bool = False,
    ) -> None:
        """Spawn entities for a single SpriteGroup, respecting group direction and theme."""
        group_dir = group.direction if group.direction is not None else self.rng.choice([-1, 1])
        group_theme = group.theme
        for sprite, _weight, (lo, hi) in group.entries:
            if not self._theme_matches(sprite, group_theme=group_theme):
                continue
            n = self.rng.randint(lo, hi)
            for _ in range(n):
                entities.append(self._spawn_sky_entity(sprite, direction=group_dir, optional_motion=optional_motion))

    def _spawn_initial_entities(self) -> list[SkyEntity]:
        """Spawn sky entities: standalone sprites + non-cloud groups + weather clouds."""
        from teleclaude.cli.tui.animations.sprites import (
            get_optional_motion_groups,
            get_sky_entities,
            get_weather_clouds,
        )

        entities: list[SkyEntity] = []
        # Standalone sprites (15% chance each)
        for sprite in get_sky_entities():
            if self._theme_matches(sprite) and self.rng.random() < 0.15:
                entities.append(self._spawn_sky_entity(sprite))
        if self.show_extra_motion:
            for group in get_optional_motion_groups():
                self._spawn_group_entities(group, entities, optional_motion=True)

        cloud_group = get_weather_clouds(self._weather)
        self._spawn_group_entities(cloud_group, entities)
        return entities

    def _pick_y(self, y_weights: list[tuple[int, int, int]]) -> int:
        """Pick a Y position from weighted (y_lo, y_hi, weight) triples."""
        _, _, *_ = y_weights[0]  # validate structure
        ranges_and_weights = [(lo, hi, w) for lo, hi, w in y_weights]
        wts = [w for _, _, w in ranges_and_weights]
        chosen = self.rng.choices(ranges_and_weights, weights=wts, k=1)[0]
        return self.rng.randint(chosen[0], chosen[1])

    def _pick_weighted_float(self, weights: list[tuple[float, int]]) -> float:
        """Pick a float value from a weighted distribution."""
        values, wts = zip(*weights)
        return self.rng.choices(values, weights=wts, k=1)[0]

    @staticmethod
    def _sprite_max_width(sprite: CompositeSprite | AnimatedSprite) -> int:
        """Compute stable bounding-box width across all frames/layers."""
        w = 0
        renderables: list[list[str] | CompositeSprite] = (
            sprite.frames if isinstance(sprite, AnimatedSprite) else [sprite]
        )
        for r in renderables:
            if isinstance(r, CompositeSprite):
                for layer in r.layers:
                    for rows in (layer.positive, layer.negative):
                        if rows:
                            w = max(w, *(len(row) for row in rows))
            else:
                w = max(w, *(len(row) for row in r))
        return w

    @staticmethod
    def _sprite_owns_direction(sprite: CompositeSprite | AnimatedSprite) -> bool:
        """True if all speed_weights share the same strict sign (no zeros)."""
        vals = [v for v, _ in sprite.speed_weights]
        return all(v > 0 for v in vals) or all(v < 0 for v in vals)

    def _spawn_sky_entity(
        self,
        sprite: CompositeSprite | AnimatedSprite,
        direction: int | None = None,
        *,
        optional_motion: bool = False,
    ) -> SkyEntity:
        """Spawn a sky entity from any CompositeSprite or AnimatedSprite.

        Direction override chain:
          1. Sprite has signed speed_weights → sprite owns direction, ignore param.
          2. direction param provided (from group) → apply as sign.
          3. Neither → random ±1.
        """
        if isinstance(sprite, CompositeSprite):
            sprite = sprite.resolve_colors()
        z_level = self._pick_z_level(sprite.z_weights)
        y = self._pick_y(sprite.y_weights) if sprite.y_weights else 2
        owns_dir = self._sprite_owns_direction(sprite)

        if not owns_dir and direction is None:
            direction = self.rng.choice([-1, 1])

        if sprite.speed_fixed is not None:
            lo, hi = sprite.speed_fixed
            speed = self.rng.uniform(lo, hi)
            if not owns_dir:
                speed = abs(speed) * direction  # type: ignore[operator]
            return {
                "sprite": sprite,
                "sprite_w": self._sprite_max_width(sprite),
                "x": self.rng.randint(0, self.width),
                "speed": speed,
                "target_speed": speed,
                "y": y,
                "z": z_level,
                "next_speed_change": 0,
                "fixed_speed": True,
                "optional_motion": optional_motion,
            }

        initial_speed = self._pick_weighted_float(sprite.speed_weights)
        if not owns_dir:
            initial_speed = abs(initial_speed) * direction  # type: ignore[operator]
        return {
            "sprite": sprite,
            "sprite_w": self._sprite_max_width(sprite),
            "x": self.rng.randint(0, self.width),
            "speed": initial_speed,
            "target_speed": initial_speed,
            "y": y,
            "z": z_level,
            "next_speed_change": self.rng.randint(80, 300),
            "fixed_speed": False,
            "optional_motion": optional_motion,
        }

    def set_extra_motion(self, enabled: bool) -> None:
        """Enable or disable optional moving sprites without rebuilding ambient sky."""
        from teleclaude.cli.tui.animations.sprites import get_optional_motion_groups

        if self.show_extra_motion == enabled:
            return

        self.show_extra_motion = enabled
        if not enabled:
            self._sky_entities = [entity for entity in self._sky_entities if not entity["optional_motion"]]
            return

        for group in get_optional_motion_groups():
            self._spawn_group_entities(group, self._sky_entities, optional_motion=True)

    def force_spawn(self, sprite: object | None = None) -> None:
        """Force a sky entity to appear immediately.

        Args:
            sprite: A specific sprite instance, SpriteGroup, or None for random.
        """
        if isinstance(sprite, SpriteGroup):
            from teleclaude.cli.tui.animations.sprites import get_optional_motion_groups

            # Pick a random entry from the group, respect group direction
            entries = sprite.entries
            if entries:
                chosen_sprite = self.rng.choices(
                    [s for s, _, _ in entries],
                    weights=[w for _, w, _ in entries],
                    k=1,
                )[0]
                group_dir = sprite.direction if sprite.direction is not None else self.rng.choice([-1, 1])
                is_optional_motion = any(group is sprite for group in get_optional_motion_groups())
                self._sky_entities.append(
                    self._spawn_sky_entity(
                        chosen_sprite,
                        direction=group_dir,
                        optional_motion=is_optional_motion,
                    )
                )
            return
        if sprite is not None:
            self._sky_entities.append(self._spawn_sky_entity(sprite))
        else:
            from teleclaude.cli.tui.animations.sprites import get_sky_entities

            entities = get_sky_entities()
            if entities:
                self._sky_entities.append(self._spawn_sky_entity(self.rng.choice(entities)))

    def force_spawn_entity(self) -> None:
        """Force a random sky entity to appear immediately (legacy alias)."""
        self.force_spawn()

    def _build_sky_cache(self) -> list[tuple[int, int, int, str]]:
        """Pre-compute static sky gradient pixels for the current theme."""
        from teleclaude.cli.tui.theme import blend_colors

        base = self._SKY_BASE_DARK if self.dark_mode else self._SKY_BASE_LIGHT
        target = self._SKY_TARGET_DARK if self.dark_mode else self._SKY_TARGET_LIGHT
        max_y = max(1, self.height - 1)
        row_colors = [blend_colors(base, target, y / max_y) for y in range(self.height)]
        pixels: list[tuple[int, int, int, str]] = []
        for x, y in self._all_pixels:
            pixels.append((Z0, x, y, row_colors[y]))
        return pixels

    def _render_quarter_celestial(self, buffer: RenderBuffer, term_width: int) -> None:
        """Render celestial body (sun/moon) at top-right corner using SUN_SPRITE or MOON_SPRITE."""

        sprite = SUN_SPRITE if not self.dark_mode else MOON_SPRITE
        layer = sprite.layers[0]
        sprite_w = max(len(r) for r in layer.positive)
        # Anchor center at top-right
        cx = term_width - 1
        cy = 1
        # Narrow pane: push partially off-screen
        if term_width <= 130:
            cx += 8
            cy -= 4

        top_left_x = cx - sprite_w + 1
        render_sprite(buffer, Z20, top_left_x, cy, sprite, self.width, self.height)

    def update(self, frame: int) -> RenderBuffer:
        # Reuse persistent buffer — avoid allocating 4000+ dict entries per frame
        if not hasattr(self, "_buffer"):
            self._buffer = RenderBuffer()
        buffer = self._buffer

        # Refresh terminal width every ~100 frames (~15s at 250ms tick)
        if frame - self._term_width_frame >= 100:
            self._cached_term_width = self._fetch_term_width()
            self._term_width_frame = frame
        term_width = self._cached_term_width

        # Rebuild sky gradient cache on theme change (expensive — 4000 pixels)
        if self._cached_dark_mode != self.dark_mode:
            self._cached_sky_pixels = self._build_sky_cache()
            self._cached_dark_mode = self.dark_mode
            # Full rebuild: repaint sky into persistent buffer
            buffer.clear()
            for z, x, y, color in self._cached_sky_pixels:
                buffer.add_pixel(z, x, y, color)

        # Clear all dynamic layers each frame (everything except Z0)
        for z in list(buffer.layers):
            if z != Z0:
                buffer.clear_layer(z)

        if self.dark_mode:
            # 2. Stars at Z10 (behind clouds)
            for star in self.stars:
                twinkle = (math.sin(frame * star["speed"] + star["phase"]) + 1.0) / 2.0
                if twinkle > 0.88:
                    buffer.add_pixel(Z10, star["pos"][0], star["pos"][1], star["char"])

            # 3. Moon — quarter celestial at top-right
            self._render_quarter_celestial(buffer, term_width)
        else:
            # 2. Weather change check — re-spawn all entities with new cloud group
            now = time.time()
            if now >= self._next_weather_change:
                self._weather = self.rng.choices(self._WEATHER_NAMES, weights=self._WEATHER_WEIGHTS, k=1)[0]
                self._sky_entities = self._spawn_initial_entities()
                self._next_weather_change = now + self.rng.uniform(30 * 60, 120 * 60)

            # 3. Sun — quarter celestial at top-right
            self._render_quarter_celestial(buffer, term_width)

        # 5. Sky entities (both modes — drift horizontally at assigned Z-levels)
        for entity in self._sky_entities:
            if not entity.get("fixed_speed"):
                # Speed easing: periodically pick new target, interpolate toward it
                next_change = int(entity.get("next_speed_change", 0))
                if frame >= next_change:
                    sprite_ref = entity["sprite"]
                    new_target = self._pick_weighted_float(sprite_ref.speed_weights)  # type: ignore[union-attr]
                    if not self._sprite_owns_direction(sprite_ref):  # type: ignore[arg-type]
                        direction = 1 if float(entity["speed"]) >= 0 else -1
                        new_target = abs(new_target) * direction
                    entity["target_speed"] = new_target
                    entity["next_speed_change"] = frame + self.rng.randint(80, 300)
                current = float(entity["speed"])
                target = float(entity.get("target_speed", current))
                entity["speed"] = current + (target - current) * 0.05

            # Accumulate position from speed (avoids jumps when speed changes)
            entity["x"] = float(entity["x"]) + float(entity["speed"])
            sprite = entity["sprite"]
            renderable = sprite.tick(frame)  # type: ignore[union-attr]
            sprite_w = int(entity["sprite_w"])
            wrap = self.width + sprite_w + 20
            ex = int(entity["x"]) % wrap - sprite_w - 10
            ey = int(entity["y"])
            # Per-frame Y offset (bobbing) for AnimatedSprite with y_offsets
            y_offsets = getattr(sprite, "y_offsets", None)
            if y_offsets:
                ey += y_offsets[frame % len(y_offsets)]
            render_sprite(buffer, int(entity["z"]), ex, ey, renderable, self.width, self.height)

        return buffer
