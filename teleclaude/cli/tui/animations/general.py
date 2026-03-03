"""General-purpose TUI animations (gradients, sweeps, atmospheric)."""

from __future__ import annotations

import math
import random
import shutil
import time
from typing import TYPE_CHECKING

from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
from teleclaude.cli.tui.animations.base import (
    Z_CELESTIAL,
    Z_CLOUDS_FAR,
    Z_CLOUDS_MID,
    Z_CLOUDS_NEAR,
    Z_SKY,
    Z_STARS,
    Animation,
    RenderBuffer,
    Spectrum,
)
from teleclaude.cli.tui.animations.creative import (
    ColorSweep,
    EQBars,
    Glitch,
    LaserScan,
    LavaLamp,
    NeonFlicker,
    Plasma,
)
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

    # Cloud templates built dynamically from sprite definitions.
    # Size categories: 0=wisp (1 row), 1=puff (2-3 rows), 2=medium (3-4 rows), 3=cumulus (4+ rows)
    @staticmethod
    def _build_cloud_templates() -> list[tuple[list[str], int]]:
        from teleclaude.cli.tui.animations.sprites import (
            CLOUD_SPRITES_FAR,
            CLOUD_SPRITES_MID,
            CLOUD_SPRITES_NEAR,
        )

        templates: list[tuple[list[str], int]] = []
        for sprite in CLOUD_SPRITES_FAR:
            templates.append((sprite, 0))  # 1-row wisps
        for sprite in CLOUD_SPRITES_MID:
            rows = len(sprite)
            size = 1 if rows <= 2 else 2  # 2 rows = puff, 3+ = medium
            templates.append((sprite, size))
        for sprite in CLOUD_SPRITES_NEAR:
            templates.append((sprite, 3))  # 4+ row cumulus
        return templates

    _CLOUD_TEMPLATES: list[tuple[list[str], int]] = []  # populated in __init_subclass__ / __init__
    _SPEED_RANGES = {
        0: (0.08, 0.18),  # wisps: slow, far
        1: (0.15, 0.30),  # puffs: slow-medium
        2: (0.25, 0.45),  # medium: medium
        3: (0.40, 0.65),  # cumulus: fast, close
    }
    # Weighted Z-level distribution per cloud size category
    _CLOUD_Z_WEIGHTS: dict[int, list[tuple[int, int]]] = {
        0: [(Z_CLOUDS_FAR, 60), (Z_CLOUDS_MID, 30), (Z_CLOUDS_NEAR, 10)],  # wisps: mostly far, can be foggy
        1: [(Z_CLOUDS_FAR, 50), (Z_CLOUDS_MID, 40), (Z_CLOUDS_NEAR, 10)],  # puffs: far/mid
        2: [(Z_CLOUDS_FAR, 40), (Z_CLOUDS_MID, 55), (Z_CLOUDS_NEAR, 5)],  # medium: mostly mid
        3: [(Z_CLOUDS_FAR, 70), (Z_CLOUDS_MID, 30)],  # cumulus: NEVER near, mostly far
    }
    _WEATHER_CONFIGS = {
        "clear": {"sizes": [0], "count": (3, 6)},  # wisps only, more of them
        "fair": {"sizes": [0, 0, 1], "count": (5, 9)},  # doubled wisps in pool
        "cloudy": {"sizes": [0, 0, 1, 2], "count": (7, 12)},  # wisps still most common
        "overcast": {"sizes": [0, 1, 1, 2, 3], "count": (10, 16)},  # cumulus rare even here
    }
    _WEATHER_NAMES = ["clear", "fair", "cloudy", "overcast"]
    _WEATHER_WEIGHTS = [30, 35, 25, 10]

    # Celestial shapes — rendered as quarter disc anchored at top-right corner
    _SUN_ROWS = [
        "    \u2588\u2588\u2588\u2588\u2588\u2588\u2588    ",
        "  \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588  ",
        " \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588 ",
        " \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588 ",
        "  \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588  ",
        "    \u2588\u2588\u2588\u2588\u2588\u2588\u2588    ",
    ]
    _MOON_ROWS = [
        " ,/\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588&.  ",
        " \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588&  ",
        "\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588& ",
        "\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588& ",
        "'\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588&' ",
        "  '\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588&'  ",
    ]
    # Celestial ambient glow — painted at gap positions in the bounding box so
    # cloud shade chars pick up a warm/cool tint instead of raw sky gradient.
    _SUN_GLOW = "#4A3000"
    _MOON_GLOW = "#2A2A3A"

    # City glow: 3 rows behind tab bar (y=7,8,9)
    _CITY_GLOW = ["#1A0035", "#270055", "#0A0010"]

    # UFO Z-level weights: 50% far, 35% mid, 15% near
    _UFO_Z_WEIGHTS = [(Z_CLOUDS_FAR, 50), (Z_CLOUDS_MID, 35), (Z_CLOUDS_NEAR, 15)]

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs.setdefault("target", "header")
        super().__init__(*args, **kwargs)
        # Build cloud templates from sprites on first instantiation
        if not GlobalSky._CLOUD_TEMPLATES:
            GlobalSky._CLOUD_TEMPLATES = GlobalSky._build_cloud_templates()
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
        for _ in range(40):
            self.stars.append(
                {
                    "pos": (self.rng.randint(0, self.width - 1), self.rng.randint(0, self.height - 1)),
                    "char": self.rng.choices(_star_types, weights=_star_weights, k=1)[0],
                    "phase": self.rng.random() * math.pi * 2,
                    "speed": 0.010 + self.rng.random() * 0.018,
                }
            )

        # Weather system — randomized cloud patterns that change every 30-120 min
        self._weather = self.rng.choices(self._WEATHER_NAMES, weights=self._WEATHER_WEIGHTS, k=1)[0]
        self._clouds: list[dict[str, object]] = self._generate_clouds()
        self._next_weather_change = time.time() + self.rng.uniform(30 * 60, 120 * 60)

        # UFO — rare sky entity (~15% chance per weather cycle)
        self._ufo: dict[str, object] | None = self._maybe_spawn_ufo()

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

    def _generate_clouds(self) -> list[dict[str, object]]:
        """Generate cloud set for current weather state with parallax depth."""
        config = self._WEATHER_CONFIGS[self._weather]
        size_pool = config["sizes"]  # repeated entries weight the selection
        # Pre-group templates by size for weighted selection
        by_size: dict[int, list[list[str]]] = {}
        for rows, size in self._CLOUD_TEMPLATES:
            by_size.setdefault(size, []).append(rows)
        if not any(s in by_size for s in size_pool):
            return []
        count = self.rng.randint(*config["count"])
        clouds: list[dict[str, object]] = []

        for _ in range(count):
            size = self.rng.choice(size_pool)  # weighted by repeats in pool
            templates = by_size.get(size, by_size.get(0, []))
            rows = self.rng.choice(templates)
            cloud = self._make_cloud(rows, size)
            clouds.append(cloud)

            # Wisps: 40% chance of a companion (parallax pair, never aligned)
            if size == 0 and self.rng.random() < 0.4:
                wisp_templates = by_size.get(0, [])
                comp_rows = self.rng.choice(wisp_templates)
                comp_y = int(cloud["y"]) + self.rng.choice([-1, 1])
                comp_y = max(0, min(self.height - len(comp_rows), comp_y))
                companion = self._make_cloud(comp_rows, 0)
                companion["y"] = comp_y
                companion["x"] = int(cloud["x"]) + self.rng.randint(2, 6)
                companion["speed"] = float(cloud["speed"]) * (0.80 + self.rng.random() * 0.15)
                clouds.append(companion)

        return clouds

    def _make_cloud(self, rows: list[str], size: int) -> dict[str, object]:
        """Create a single cloud with randomized position, speed, and Z-level."""
        max_y = max(0, self.height - len(rows))
        lo, hi = self._SPEED_RANGES[size]
        z_level = self._pick_z_level(self._CLOUD_Z_WEIGHTS[size])
        return {
            "shape": rows,
            "x": self.rng.randint(0, self.width),
            "y": self.rng.randint(0, max_y),
            "speed": lo + self.rng.random() * (hi - lo),
            "size": size,
            "z": z_level,
        }

    def _maybe_spawn_ufo(self) -> dict[str, object] | None:
        """~15% chance to spawn a UFO as a sky entity."""
        if self.rng.random() > 0.15:
            return None
        from teleclaude.cli.tui.animations.sprites import UFO_SPRITE

        z_level = self._pick_z_level(self._UFO_Z_WEIGHTS)
        return {
            "sprite": UFO_SPRITE,
            "x": self.rng.randint(0, self.width),
            "speed": 0.55 + self.rng.random() * 0.35,
            "y": self.rng.randint(0, 3),
            "z": z_level,
        }

    def _build_sky_cache(self) -> list[tuple[int, int, int, str]]:
        """Pre-compute static sky gradient pixels for the current theme."""
        pixels: list[tuple[int, int, int, str]] = []
        sky = self.night_sky if self.dark_mode else self.day_sky
        for x, y in self._all_pixels:
            pos_factor = y / max(1, self.height - 1)
            pixels.append((Z_SKY, x, y, sky.get_color(pos_factor)))
        if self.dark_mode:
            for dy, glow_color in enumerate(self._CITY_GLOW):
                for x in range(self.width):
                    pixels.append((Z_SKY, x, 7 + dy, glow_color))
        return pixels

    def _render_quarter_celestial(self, buffer: RenderBuffer, rows: list[str], term_width: int) -> None:
        """Render bottom-left quarter of celestial body at top-right corner."""
        sprite_w = max(len(r) for r in rows)
        # Anchor center at (term_width - 1, -2) so only bottom-left quarter is visible
        cx = term_width - 1
        cy = -2

        # Narrow pane (split view): push celestial partially off-screen
        if term_width <= 130:
            cx += 6
            cy -= 2

        is_sun = rows is self._SUN_ROWS
        glow = self._SUN_GLOW if is_sun else self._MOON_GLOW

        for dy, row in enumerate(rows):
            y = cy + dy
            if y < 0:
                continue
            if y >= self.height:
                break
            for dx, ch in enumerate(row):
                x = cx - sprite_w + 1 + dx
                if 0 <= x < self.width:
                    if ch != " ":
                        buffer.add_pixel(Z_CELESTIAL, x, y, ch)
                    else:
                        # Ambient glow at gap positions — invisible in empty sky
                        # (space char ignores fg color) but picked up as bg
                        # by cloud shade chars passing over the celestial area.
                        buffer.add_pixel(Z_CELESTIAL, x, y, glow)

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

        # Clear only dynamic layers each frame (stars, celestials, clouds)
        buffer.clear_layer(Z_STARS)
        buffer.clear_layer(Z_CELESTIAL)
        buffer.clear_layer(Z_CLOUDS_FAR)
        buffer.clear_layer(Z_CLOUDS_MID)
        buffer.clear_layer(Z_CLOUDS_NEAR)

        if self.dark_mode:
            # 2. Stars at Z_STARS (behind celestials and clouds)
            for star in self.stars:
                speed = star["speed"] * (2.5 if is_party else 1.0)
                twinkle = (math.sin(frame * speed + star["phase"]) + 1.0) / 2.0
                if twinkle > 0.88:
                    buffer.add_pixel(Z_STARS, star["pos"][0], star["pos"][1], star["char"])

            # 3. Moon — quarter celestial at top-right
            self._render_quarter_celestial(buffer, self._MOON_ROWS, term_width)
        else:
            # 2. Weather change check
            now = time.time()
            if now >= self._next_weather_change:
                self._weather = self.rng.choices(self._WEATHER_NAMES, weights=self._WEATHER_WEIGHTS, k=1)[0]
                self._clouds = self._generate_clouds()
                self._ufo = self._maybe_spawn_ufo()
                self._next_weather_change = now + self.rng.uniform(30 * 60, 120 * 60)

            # 3. Drifting clouds with weighted Z-level parallax
            for cloud in self._clouds:
                shape = cloud["shape"]
                cloud_z = int(cloud["z"])
                cx = int(int(cloud["x"]) + frame * float(cloud["speed"])) % (self.width + 60) - 30
                cy = int(cloud["y"])
                for dy, row in enumerate(shape):
                    for dx, ch in enumerate(row):
                        if ch != " ":
                            px = cx + dx
                            py = cy + dy
                            if 0 <= px < self.width and 0 <= py < self.height:
                                buffer.add_pixel(cloud_z, px, py, ch)

            # 4. Sun — quarter celestial at top-right
            self._render_quarter_celestial(buffer, self._SUN_ROWS, term_width)

        # 5. UFO sky entity (both modes — drifts horizontally at assigned Z-level)
        if self._ufo:
            sprite = self._ufo["sprite"]
            ufo_z = int(self._ufo["z"])
            ufo_speed = float(self._ufo["speed"])
            sprite_w = max(len(r) for r in sprite)
            ux = int(int(self._ufo["x"]) + frame * ufo_speed) % (self.width + sprite_w + 20) - sprite_w - 10
            uy = int(self._ufo["y"])
            for dy, row in enumerate(sprite):
                for dx, ch in enumerate(row):
                    if ch != " ":
                        px = ux + dx
                        py = uy + dy
                        if 0 <= px < self.width and 0 <= py < self.height:
                            buffer.add_pixel(ufo_z, px, py, ch)

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
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

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
