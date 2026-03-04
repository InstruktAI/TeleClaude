"""General-purpose TUI animations (gradients, sweeps, atmospheric)."""

from __future__ import annotations

import math
import random
import shutil
import time
from typing import TYPE_CHECKING

from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
from teleclaude.cli.tui.animations.base import (
    Z0,
    Z10,
    Z20,
    Animation,
    RenderBuffer,
    Spectrum,
    render_sprite,
)
from teleclaude.cli.tui.animations.creative import ColorSweep, EQBars, Glitch, LaserScan, LavaLamp, NeonFlicker, Plasma
from teleclaude.cli.tui.animations.sprites import MOON_SPRITE, SUN_SPRITE
from teleclaude.cli.tui.animations.sprites.composite import AnimatedSprite, CompositeSprite
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_LETTERS,
    BIG_BANNER_WIDTH,
    LOGO_HEIGHT,
    LOGO_LETTERS,
    LOGO_WIDTH,
    PixelMap,
)

if TYPE_CHECKING:
    pass


class GlobalSky(Animation):
    """TC20: Global background canvas with Day/Night physical states.
    Paints the entire header area (Z-0) including margins.
    Dynamic weather system with parallax clouds at weighted Z-levels.
    Quarter celestial (sun/moon) anchored at top-right corner.
    UFO as rare sky entity with weighted depth.
    """

    _WEATHER_NAMES = ["clear", "fair", "cloudy", "overcast"]
    _WEATHER_WEIGHTS = [30, 35, 25, 10]

    # City glow: 3 rows behind tab bar (y=7,8,9)
    _CITY_GLOW = ["#1A0035", "#270055", "#0A0010"]

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs.setdefault("target", "header")
        super().__init__(*args, **kwargs)
        self.width = 400
        self.height = 10
        self._all_pixels = [(x, y) for y in range(self.height) for x in range(self.width)]

        # Sky gradients
        self.day_sky = Spectrum(["#87CEEB", "#C8E8F8"])
        self.night_sky = Spectrum(["#000000", "#05000A", "#0F001A", "#05000A"])

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
        self._sky_entities: list[dict[str, object]] = self._spawn_initial_entities()

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

    def _theme_matches(self, sprite: object) -> bool:
        """Check if a sprite's theme matches the current mode."""
        theme = getattr(sprite, "theme", None)
        if theme is None:
            return True
        return theme == ("dark" if self.dark_mode else "light")

    def _spawn_initial_entities(self) -> list[dict[str, object]]:
        """Spawn sky entities: standalone sprites + non-cloud groups + weather clouds."""
        from teleclaude.cli.tui.animations.sprites import get_sky_entities, get_sprite_groups, get_weather_clouds

        entities: list[dict[str, object]] = []
        # Standalone sprites (15% chance each)
        for sprite in get_sky_entities():
            if self._theme_matches(sprite) and self.rng.random() < 0.15:
                entities.append(self._spawn_sky_entity(sprite))
        # Non-cloud sprite groups (birds, etc.)
        cloud_group = get_weather_clouds(self._weather)
        for group in get_sprite_groups():
            if group is cloud_group:
                continue
            for sprite, _weight, (lo, hi) in group.entries:
                if not self._theme_matches(sprite):
                    continue
                n = self.rng.randint(lo, hi)
                for _ in range(n):
                    entities.append(self._spawn_sky_entity(sprite))
        # Weather-specific clouds
        for sprite, _weight, (lo, hi) in cloud_group.entries:
            if not self._theme_matches(sprite):
                continue
            n = self.rng.randint(lo, hi)
            for _ in range(n):
                entities.append(self._spawn_sky_entity(sprite))
        return entities

    # Vertical lane ranges: (min_y, max_y) for top/mid/bottom of the header
    _LANE_Y_RANGES = {0: (0, 1), 1: (2, 4), 2: (5, 7)}

    def _pick_weighted_float(self, weights: list[tuple[float, int]]) -> float:
        """Pick a float value from a weighted distribution."""
        values, wts = zip(*weights)
        return self.rng.choices(values, weights=wts, k=1)[0]

    @staticmethod
    def _sprite_max_width(sprite: CompositeSprite | AnimatedSprite) -> int:
        """Compute stable bounding-box width across all frames/layers."""
        w = 0
        renderables: list = sprite.frames if isinstance(sprite, AnimatedSprite) else [sprite]
        for r in renderables:
            if isinstance(r, CompositeSprite):
                for layer in r.layers:
                    for rows in (layer.positive, layer.negative):
                        if rows:
                            w = max(w, *(len(row) for row in rows))
            else:
                w = max(w, *(len(row) for row in r))
        return w

    def _spawn_sky_entity(self, sprite: CompositeSprite | AnimatedSprite) -> dict[str, object]:
        """Spawn a sky entity from any CompositeSprite or AnimatedSprite."""
        z_level = self._pick_z_level(sprite.z_weights)
        lane = self._pick_z_level(sprite.y_weights) if sprite.y_weights else 1
        y_lo, y_hi = self._LANE_Y_RANGES.get(lane, (0, 3))
        direction = self.rng.choice([-1, 1])
        initial_speed = self._pick_weighted_float(sprite.speed_weights)
        return {
            "sprite": sprite,
            "sprite_w": self._sprite_max_width(sprite),
            "x": self.rng.randint(0, self.width),
            "speed": initial_speed * direction,
            "target_speed": initial_speed * direction,
            "y": self.rng.randint(y_lo, y_hi),
            "z": z_level,
            "next_speed_change": self.rng.randint(80, 300),
        }

    def force_spawn_ufo(self) -> None:
        """Force a random sky entity to appear immediately (debug keybinding)."""
        from teleclaude.cli.tui.animations.sprites import get_sky_entities

        entities = get_sky_entities()
        if entities:
            self._sky_entities.append(self._spawn_sky_entity(self.rng.choice(entities)))

    def _build_sky_cache(self) -> list[tuple[int, int, int, str]]:
        """Pre-compute static sky gradient pixels for the current theme."""
        pixels: list[tuple[int, int, int, str]] = []
        sky = self.night_sky if self.dark_mode else self.day_sky
        for x, y in self._all_pixels:
            pos_factor = y / max(1, self.height - 1)
            pixels.append((Z0, x, y, sky.get_color(pos_factor)))
        if self.dark_mode:
            for dy, glow_color in enumerate(self._CITY_GLOW):
                for x in range(self.width):
                    pixels.append((Z0, x, 7 + dy, glow_color))
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
            cx += 7
            cy -= 3

        top_left_x = cx - sprite_w + 1
        render_sprite(buffer, Z20, top_left_x, cy, sprite, self.width, self.height)

    def update(self, frame: int) -> RenderBuffer:
        # Reuse persistent buffer — avoid allocating 4000+ dict entries per frame
        if not hasattr(self, "_buffer"):
            self._buffer = RenderBuffer()
        buffer = self._buffer
        is_party = self.animation_mode == "party"

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
                speed = star["speed"] * (2.5 if is_party else 1.0)
                twinkle = (math.sin(frame * speed + star["phase"]) + 1.0) / 2.0
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
            # Speed easing: periodically pick new target, interpolate toward it
            next_change = int(entity.get("next_speed_change", 0))
            if frame >= next_change:
                sprite_ref = entity["sprite"]
                direction = 1 if float(entity["speed"]) >= 0 else -1
                new_target = self._pick_weighted_float(sprite_ref.speed_weights) * direction  # type: ignore[union-attr]
                entity["target_speed"] = new_target
                entity["next_speed_change"] = frame + self.rng.randint(80, 300)
            current = float(entity["speed"])
            target = float(entity.get("target_speed", current))
            entity["speed"] = current + (target - current) * 0.05

            entity_z = int(entity["z"])
            entity_speed = float(entity["speed"])
            sprite = entity["sprite"]
            renderable = sprite.tick(frame)  # type: ignore[union-attr]
            sprite_w = int(entity["sprite_w"])
            wrap = self.width + sprite_w + 20
            ex = int(int(entity["x"]) + frame * entity_speed) % wrap - sprite_w - 10
            ey = int(entity["y"])
            render_sprite(buffer, entity_z, ex, ey, renderable, self.width, self.height)

        return buffer


class FullSpectrumCycle(Animation):
    """G1: Cycle through the entire seven-color spectrum synchronously."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        color_idx = frame % len(self.palette)
        color_pair = self.palette.get(color_idx)
        # Use target-specific grid coordinates
        all_pixels = PixelMap.get_all_pixels(self.target)
        return {pixel: color_pair for pixel in all_pixels}


class LetterWaveLR(Animation):
    """G2: Each letter lights up sequentially from left to right."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = frame % num_letters
        color_pair = self.palette.get(frame // num_letters)

        base_color = self.enforce_vibrancy(self.get_contrast_safe_color(color_pair))
        from teleclaude.cli.tui.animation_colors import rgb_to_hex

        r, g, b = hex_to_rgb(base_color)
        dim_color = rgb_to_hex(int(r * 0.6), int(g * 0.6), int(b * 0.6))

        result = {}
        for i in range(num_letters):
            color = base_color if i == active_letter_idx else dim_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class LetterWaveRL(Animation):
    """G3: Each letter lights up sequentially from right to left."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = (num_letters - 1) - (frame % num_letters)
        color_pair = self.palette.get(frame // num_letters)

        base_color = self.enforce_vibrancy(self.get_contrast_safe_color(color_pair))
        from teleclaude.cli.tui.animation_colors import rgb_to_hex

        r, g, b = hex_to_rgb(base_color)
        dim_color = rgb_to_hex(int(r * 0.6), int(g * 0.6), int(b * 0.6))

        result = {}
        for i in range(num_letters):
            color = base_color if i == active_letter_idx else dim_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class LineSweepTopBottom(Animation):
    """G6: Vertical volumetric sweep through neon tubes from top to bottom."""

    theme_filter = "dark"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#0000FF", "#00FFFF", "#0000FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        modulation = self.get_modulation(frame)
        active_y = (frame * modulation * 0.5) % (height + 2) - 1

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                surge = self.linear_surge(y, active_y, 1.5)
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color(y / max(1, height - 1))
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))
        return result


class LineSweepBottomTop(Animation):
    """G7: Vertical volumetric sweep through neon tubes from bottom to top."""

    theme_filter = "dark"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF00FF", "#FF0000", "#FF00FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        modulation = self.get_modulation(frame)
        active_y = (height - 1) - ((frame * modulation * 0.5) % (height + 2) - 1)

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                surge = self.linear_surge(y, active_y, 1.5)
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color(y / max(1, height - 1))
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))
        return result


class MiddleOutVertical(Animation):
    """G8: Vertical volumetric center expansion (Big only)."""

    theme_filter = "dark"

    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF0000", "#FFFF00", "#FF0000"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        height = BIG_BANNER_HEIGHT
        modulation = self.get_modulation(frame)
        active_step = (frame * modulation * 0.5) % 4
        active_rows = {2 - int(active_step), 3 + int(active_step)}

        result = {}
        for i in range(len(BIG_BANNER_LETTERS)):
            for x, y in PixelMap.get_letter_pixels(True, i):
                min_dist = min(abs(y - ar) for ar in active_rows)
                surge = 1.0 - (min_dist / 2.0) if min_dist < 2 else 0.0
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color(y / max(1, height - 1))
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))
        return result


class WithinLetterSweepLR(Animation):
    """G4: Vertical volumetric surge L→R through neon tubes."""

    theme_filter = "dark"
    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#00FF00", "#00FFFF", "#00FF00"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH
        modulation = self.get_modulation(frame)
        active_x = (frame * modulation * 1.5) % (width + 10) - 5

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                surge = self.linear_surge(x - 1, active_x, 3.0)
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color((x - 1) / width)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))

        return result


class WithinLetterSweepRL(Animation):
    """G5: Vertical volumetric surge R→L through neon tubes."""

    theme_filter = "dark"
    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#00FFFF", "#0000FF", "#00FFFF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH
        modulation = self.get_modulation(frame)
        active_x = (width - 1) - ((frame * modulation * 1.5) % (width + 10) - 5)

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                surge = self.linear_surge(x - 1, active_x, 3.0)
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color((x - 1) / width)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))

        return result


class WordSplitBlink(Animation):
    """G9: \"TELE\" vs \"CLAUDE\" blink alternately."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        color_pair = self.palette.get(frame // 2)
        safe_color = self.enforce_vibrancy(self.get_contrast_safe_color(color_pair))
        parity = frame % 2

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            is_first_word = i < 4
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                if (is_first_word and parity == 0) or (not is_first_word and parity == 1):
                    result[(x, y)] = safe_color
                else:
                    from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

                    r, g, b = hex_to_rgb(safe_color)
                    result[(x, y)] = rgb_to_hex(int(r * 0.6), int(g * 0.6), int(b * 0.6))
        return result


class DiagonalSweepDR(Animation):
    """G11: Volumetric diagonal surge from top-left to bottom-right."""

    theme_filter = "dark"
    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#00FF00", "#FFFF00", "#00FF00"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        width, height = BIG_BANNER_WIDTH, BIG_BANNER_HEIGHT
        max_val = width + height
        modulation = self.get_modulation(frame)
        active = (frame * modulation * 1.5) % (max_val + 10) - 5

        result = {}
        num_letters = len(BIG_BANNER_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(True, i):
                surge = self.linear_surge((x - 1) + y, active, 4.0)
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color(((x - 1) + y) / max_val)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))
        return result


class DiagonalSweepDL(Animation):
    """G12: Volumetric diagonal surge from top-right to bottom-left."""

    theme_filter = "dark"

    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF00FF", "#00FFFF", "#FF00FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        width, height = BIG_BANNER_WIDTH, BIG_BANNER_HEIGHT
        max_val = width + height
        modulation = self.get_modulation(frame)
        active = (width - 1) - ((frame * modulation * 1.5) % (max_val + 10) - 5)

        result = {}
        num_letters = len(BIG_BANNER_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(True, i):
                surge = self.linear_surge((x - 1) - y, active, 4.0)
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color(((x - 1) + y) / max_val)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))
        return result


class LetterShimmer(Animation):
    """G14: Each letter rapidly cycles through colors independently."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        result = {}
        for i in range(num_letters):
            color_pair = self.palette.get((frame + i * 3) % len(self.palette))
            color = self.enforce_vibrancy(self.get_contrast_safe_color(color_pair))
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class WavePulse(Animation):
    """G15: Volumetric color surge travels through neon tubes."""

    theme_filter = "dark"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#0000FF", "#00FFFF", "#FFFFFF", "#00FFFF", "#0000FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        modulation = self.get_modulation(frame)
        active_x = (frame * modulation * 1.5) % (width + 10) - 5

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                surge = self.linear_surge(x - 1, active_x, 4.0)
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color((x - 1) / width)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))

        return result


class BlinkSweep(Animation):
    """TC21: High-speed high-vibrancy sawtooth pulse sweeping L->R."""

    theme_filter = "dark"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FFFFFF", "#00FFFF", "#0000FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        active_x = (frame * 2.0) % (width + 5) - 2

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                surge = self.linear_surge(x - 1, active_x, 2.0)
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                color = self.spec.get_color((x - 1) / width)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * surge), int(g * surge), int(b * surge))
        return result


# ---------------------------------------------------------------------------
# TrueColor (24-bit HEX) animation suite
# ---------------------------------------------------------------------------


class SunsetGradient(Animation):
    """TC1: Smooth sunset gradient with procedural hue-rotation."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        _height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT

        modulation = self.get_modulation(frame)
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            # Slow multi-color gradient
            progress = (frame * 0.01 * modulation + x / width) % 1.0
            r = int(127 + 127 * math.sin(progress * 2 * math.pi))
            g = int(127 + 127 * math.sin(progress * 2 * math.pi + 2))
            b = int(127 + 127 * math.sin(progress * 2 * math.pi + 4))
            result[(x, y)] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
        return result


class MatrixRain(Animation):
    """TC12: Digital rain effect with green trails."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        self._columns = [random.randint(-20, 0) for _ in range(self.width)]

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result: dict[tuple[int, int], str | int] = {}

        for x in range(self.width):
            self._columns[x] += 1
            if self._columns[x] > height + 10:
                self._columns[x] = random.randint(-10, 0)

            head = self._columns[x]
            for y in range(height):
                dist = head - y
                if dist == 0:
                    result[(x, y)] = "#FFFFFF"  # Bright head
                elif 0 < dist < 8:
                    intensity = int(255 * (1.0 - dist / 8.0))
                    result[(x, y)] = rgb_to_hex(0, intensity, 0)
        return result


class FireBreath(Animation):
    """TC10: Volumetric fireplace effect — letters burn from the bottom up."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        # Bottom = white hot, mid = orange, top = dark red
        self.spec = Spectrum(["#400000", "#FF0000", "#FF4500", "#FFFF00", "#FFFFFF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        modulation = self.get_modulation(frame)

        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                y_factor = y / max(height - 1, 1)  # 0=top, 1=bottom
                fire_factor = 1.0 - y_factor  # 1=bottom (hottest), 0=top (coolest)
                # Per-column organic variation: irregular licking flames
                col_var = math.sin(x * 1.3 + frame * 0.45) * 0.28 + math.sin(x * 2.1 + frame * 0.3) * 0.15
                fire_factor = max(0.0, fire_factor + col_var)
                # Per-pixel flicker noise
                flicker = self.rng.random() * 0.35 * modulation
                # Heat intensity: peaks at bottom
                intensity = min(1.0, fire_factor + flicker)

                color = self.spec.get_color(fire_factor)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import rgb_to_hex

                r, g, b = hex_to_rgb(color)
                # 0.3 base so even cool top pixels have faint glow
                v = 0.3 + intensity * 0.7
                result[(x, y)] = rgb_to_hex(int(r * v), int(g * v), int(b * v))

        return result


class SearchlightSweep(Animation):
    """TC17: Fixed large searchlight from below with grounded wide Batman silhouette.
    Rooftop event that reflects on the physical billboard.
    """

    theme_filter = "dark"
    supports_small = True
    is_shadow_caster = True
    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)

    def _is_batman_mask(self, x: int, y: int, cx: int, cy: int) -> bool:
        """Truly Ultimate Wide & Grounded Batman Silhouette."""
        dx, dy = x - cx, y - (cy - 4)
        adx = abs(dx)

        # Grounded feet/body (bottom rows 4 and 5)
        if dy >= 3:
            return adx <= 2  # Wider feet

        # Ears/Head (top of silhouette)
        if dy == -1:
            return adx == 1
        if dy == 0:
            return adx <= 1

        # Wide Wings/Cape (middle rows) - wingspan 19 total
        if dy == 1:
            return adx <= 9
        if dy == 2:
            return adx <= 6  # Cape narrowing

        return False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.dark_mode:
            return {}

        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT

        modulation = self.get_modulation(frame)

        # Smooth Oscillation around center
        base_cx = width // 2
        offset = math.sin(frame * 0.05 * modulation) * 15
        cx = int(base_cx + offset)
        cy = height - 1

        # Truly large beam for visibility
        radius = 12

        result: dict[tuple[int, int], str | int] = {}
        for x, y in self._all_pixels:
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            effective_radius = radius - 1 if y == cy else radius
            if dist < effective_radius:
                if self._is_batman_mask(x, y, cx, cy):
                    # Grounded shadow silhouette
                    result[(x, y)] = "#060606"
                else:
                    # Bright searchlight flare (high intensity)
                    intensity = 1.0 - (dist / radius)
                    flare = int(180 + intensity * 75)
                    from teleclaude.cli.tui.animation_colors import rgb_to_hex

                    result[(x, y)] = rgb_to_hex(flare, flare, flare)
            else:
                # Outside the beam
                result[(x, y)] = -1

        return result


class CinematicPrismSweep(Animation):
    """TC18: Volumetric prism beam with random hue morphing and pivoting angle."""

    theme_filter = "dark"
    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.hue_start = self.rng.randint(0, 360)
        self.hue_end = (self.hue_start + self.rng.randint(60, 180)) % 360
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        import colorsys

        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return int(r * 255), int(g * 255), int(b * 255)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT

        modulation = self.get_modulation(frame)
        progress = frame / self.duration_frames
        angle_deg = 30 + (progress * 30)
        angle_rad = math.radians(angle_deg)

        current_hue = (self.hue_start + (self.hue_end - self.hue_start) * progress) / 360.0
        r, g, b = self._hsv_to_rgb(current_hue, 0.8, 1.0)
        from teleclaude.cli.tui.animation_colors import rgb_to_hex

        color = rgb_to_hex(r, g, b)
        safe_color = self.get_electric_neon(self.get_contrast_safe_color(color))

        max_dist = width * math.cos(angle_rad) + height * math.sin(angle_rad)
        active_dist = progress * max_dist * modulation * 1.5

        result: dict[tuple[int, int], str | int] = {}

        # 1. Beam on neon letters — beam-only, no pre-existing haze
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                d = (x - 1) * math.cos(angle_rad) + y * math.sin(angle_rad)
                surge = 1.0 - (abs(d - active_dist) / 4.0) if abs(d - active_dist) < 4 else 0.0
                if surge <= 0:
                    result[(x, y)] = -1
                    continue
                intensity = 0.6 + (surge * 0.4)
                r, g, b = hex_to_rgb(safe_color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))

        # 2. Billboard Reflection (only where beam hits)
        for x, y in self._all_pixels:
            if (x, y) in result:
                continue  # Skip neon (already handled)
            d = (x - 1) * math.cos(angle_rad) + y * math.sin(angle_rad)
            surge = 1.0 - (abs(d - active_dist) / 4.0) if abs(d - active_dist) < 4 else 0.0
            if surge > 0.1:
                r, g, b = hex_to_rgb(safe_color)
                result[(x, y)] = rgb_to_hex(int(r * surge * 0.4), int(g * surge * 0.4), int(b * surge * 0.4))
            else:
                result[(x, y)] = -1

        return result


class Bioluminescence(Animation):
    """TC15: Pitch-black sea with neon blue agents leaving glowing trails."""

    theme_filter = "dark"
    is_external_light = True
    _NUM_AGENTS = 8
    _TRAIL_DECAY = 10

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        self.height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        self._agents = [
            [random.randint(0, self.width - 1), random.randint(0, self.height - 1)] for _ in range(self._NUM_AGENTS)
        ]
        self._trails: dict[tuple[int, int], int] = {}

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        # Decay trails
        self._trails = {pos: intensity - 1 for pos, intensity in self._trails.items() if intensity > 1}
        # Move agents
        for agent in self._agents:
            agent[0] = (agent[0] + random.randint(-1, 1)) % self.width
            agent[1] = (agent[1] + random.randint(-1, 1)) % self.height
            self._trails[(agent[0], agent[1])] = self._TRAIL_DECAY
        # Render ONLY the trails (others are transparent)
        result: dict[tuple[int, int], str | int] = {p: -1 for p in self._all_pixels}
        for pos, intensity in self._trails.items():
            factor = intensity / self._TRAIL_DECAY
            r = int(0x46 * factor)
            g = int(0x82 * factor)
            b = int(0xB4 * factor)
            result[pos] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
        return result


GENERAL_ANIMATIONS = [
    # Letter classics (restored)
    FullSpectrumCycle,
    LetterWaveLR,
    LetterWaveRL,
    LetterShimmer,
    WordSplitBlink,
    # Moving gradients
    SunsetGradient,
    # Original specials
    FireBreath,
    CinematicPrismSweep,
    # New creative animations
    NeonFlicker,
    Plasma,
    Glitch,
    EQBars,
    LavaLamp,
    # Sweeps
    LineSweepTopBottom,
    LineSweepBottomTop,
    MiddleOutVertical,
    WithinLetterSweepLR,
    WithinLetterSweepRL,
    DiagonalSweepDR,
    DiagonalSweepDL,
    ColorSweep,
    LaserScan,
    # Dark mode specials
    SearchlightSweep,
    # GlobalSky is lifecycle-managed (always-on), NOT in rotation pool
]
