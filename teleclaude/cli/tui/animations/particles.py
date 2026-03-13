"""Particle and atmospheric TUI animations (rain, fire, searchlight, prism, bioluminescence)."""

from __future__ import annotations

import math
import random

from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
from teleclaude.cli.tui.animations.base import Animation, Spectrum
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_LETTERS,
    BIG_BANNER_WIDTH,
    LOGO_HEIGHT,
    LOGO_LETTERS,
    LOGO_WIDTH,
    PixelMap,
)


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
