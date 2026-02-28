"""General purpose rainbow animations."""

from __future__ import annotations

import math
import random

from teleclaude.cli.tui.animation_colors import MultiGradient, rgb_to_hex
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_LETTERS,
    BIG_BANNER_WIDTH,
    LOGO_HEIGHT,
    LOGO_LETTERS,
    LOGO_WIDTH,
    PixelMap,
)


class FullSpectrumCycle(Animation):
    """G1: All pixels synchronously cycle through the color palette."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        color_idx = frame % len(self.palette)
        color_pair = self.palette.get(color_idx)

        all_pixels = PixelMap.get_all_pixels(self.is_big)
        return {pixel: color_pair for pixel in all_pixels}


class LetterWaveLR(Animation):
    """G2: Each letter lights up sequentially from left to right."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = frame % num_letters
        color_pair = self.palette.get(frame // num_letters)
        safe_color = self.get_contrast_safe_color(color_pair)
        
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        try:
            if safe_color.startswith("#"):
                r, g, b = hex_to_rgb(safe_color)
            else:
                r, g, b = 150, 150, 150
        except (ValueError, TypeError, AttributeError):
            r, g, b = 150, 150, 150
            
        dim_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.4), int(g * 0.4), int(b * 0.4)))

        result = {}
        for i in range(num_letters):
            color = safe_color if i == active_letter_idx else dim_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class LetterWaveRL(Animation):
    """G3: Each letter lights up sequentially from right to left."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = (num_letters - 1) - (frame % num_letters)
        color_pair = self.palette.get(frame // num_letters)
        safe_color = self.get_contrast_safe_color(color_pair)

        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        try:
            if safe_color.startswith("#"):
                r, g, b = hex_to_rgb(safe_color)
            else:
                r, g, b = 150, 150, 150
        except (ValueError, TypeError, AttributeError):
            r, g, b = 150, 150, 150
            
        dim_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.4), int(g * 0.4), int(b * 0.4)))

        result = {}
        for i in range(num_letters):
            color = safe_color if i == active_letter_idx else dim_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class LineSweepTopBottom(Animation):
    """G6: Vertical volumetric sweep through neon tubes from top to bottom.
    Entire letters remain colored; a 3-row surge provides high-intensity highlight.
    """

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        active_row = frame % height
        color_pair = self.palette.get(frame // height)
        safe_color = self.get_contrast_safe_color(color_pair)
        
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        try:
            if safe_color.startswith("#"):
                r, g, b = hex_to_rgb(safe_color)
            else:
                r, g, b = 150, 150, 150
        except (ValueError, TypeError, AttributeError):
            r, g, b = 150, 150, 150
            
        # Define the volumetric pulse colors
        mid_color = safe_color
        side_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.7), int(g * 0.7), int(b * 0.7)))
        base_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.4), int(g * 0.4), int(b * 0.4)))

        result = {}
        for r in range(height):
            dist = abs(r - active_row)
            if dist == 0:
                current_color = mid_color
            elif dist == 1:
                current_color = side_color
            else:
                current_color = base_color
                
            for p in PixelMap.get_row_pixels(self.is_big, r):
                result[p] = current_color
        return result


class LineSweepBottomTop(Animation):
    """G7: Vertical volumetric sweep through neon tubes from bottom to top."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        active_row = (height - 1) - (frame % height)
        color_pair = self.palette.get(frame // height)
        safe_color = self.get_contrast_safe_color(color_pair)

        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        try:
            if safe_color.startswith("#"):
                r, g, b = hex_to_rgb(safe_color)
            else:
                r, g, b = 150, 150, 150
        except (ValueError, TypeError, AttributeError):
            r, g, b = 150, 150, 150
            
        mid_color = safe_color
        side_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.7), int(g * 0.7), int(b * 0.7)))
        base_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.4), int(g * 0.4), int(b * 0.4)))

        result = {}
        for r in range(height):
            dist = abs(r - active_row)
            if dist == 0:
                current_color = mid_color
            elif dist == 1:
                current_color = side_color
            else:
                current_color = base_color
                
            for p in PixelMap.get_row_pixels(self.is_big, r):
                result[p] = current_color
        return result


class MiddleOutVertical(Animation):
    """G8: Vertical volumetric center expansion (Big only)."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}  # Not supported for small logo

        height = BIG_BANNER_HEIGHT
        # For 6 lines, middle is between 2 and 3.
        # Steps: 0: (2,3), 1: (1,4), 2: (0,5)
        step = frame % 3
        active_rows = {2 - step, 3 + step}
        color_pair = self.palette.get(frame // 3)
        safe_color = self.get_contrast_safe_color(color_pair)

        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
        try:
            if safe_color.startswith("#"):
                r, g, b = hex_to_rgb(safe_color)
            else:
                r, g, b = 150, 150, 150
        except (ValueError, TypeError, AttributeError):
            r, g, b = 150, 150, 150
            
        mid_color = safe_color
        side_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.7), int(g * 0.7), int(b * 0.7)))
        base_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.4), int(g * 0.4), int(b * 0.4)))

        result = {}
        for r in range(height):
            # Check proximity to ANY active row
            min_dist = min(abs(r - ar) for ar in active_rows)
            if min_dist == 0:
                current_color = mid_color
            elif min_dist == 1:
                current_color = side_color
            else:
                current_color = base_color
                
            for p in PixelMap.get_row_pixels(self.is_big, r):
                result[p] = current_color
        return result


class WithinLetterSweepLR(Animation):
    """G4: Volumetric vertical sweep L→R through neon tubes (Big only)."""

    supports_small = False
    is_external_light = True

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}

        num_letters = len(BIG_BANNER_LETTERS)
        result = {}
        for i in range(num_letters):
            start_x, end_x = BIG_BANNER_LETTERS[i]
            letter_width = end_x - start_x + 1
            active_col_offset = frame % letter_width
            active_col = start_x + active_col_offset

            # Palette cycle
            color_pair = self.palette.get(frame // letter_width)
            safe_color = self.get_contrast_safe_color(color_pair)
            
            from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
            try:
                if safe_color.startswith("#"):
                    r, g, b = hex_to_rgb(safe_color)
                else:
                    r, g, b = 150, 150, 150
            except (ValueError, TypeError, AttributeError):
                r, g, b = 150, 150, 150
                
            dim_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.4), int(g * 0.4), int(b * 0.4)))

            for x in range(start_x, end_x + 1):
                # Only return the active column surge and keep others dimmed
                color = safe_color if x == active_col else dim_color
                for p in PixelMap.get_column_pixels(self.is_big, x):
                    result[p] = color
        return result


class WithinLetterSweepRL(Animation):
    """G5: Volumetric vertical sweep R→L through neon tubes (Big only)."""

    supports_small = False
    is_external_light = True

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}

        num_letters = len(BIG_BANNER_LETTERS)
        result = {}
        for i in range(num_letters):
            start_x, end_x = BIG_BANNER_LETTERS[i]
            letter_width = end_x - start_x + 1
            active_col_offset = (letter_width - 1) - (frame % letter_width)
            active_col = start_x + active_col_offset

            color_pair = self.palette.get(frame // letter_width)
            safe_color = self.get_contrast_safe_color(color_pair)

            from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
            try:
                if safe_color.startswith("#"):
                    r, g, b = hex_to_rgb(safe_color)
                else:
                    r, g, b = 150, 150, 150
            except (ValueError, TypeError, AttributeError):
                r, g, b = 150, 150, 150
                
            dim_color = self.get_contrast_safe_color(rgb_to_hex(int(r * 0.4), int(g * 0.4), int(b * 0.4)))

            for x in range(start_x, end_x + 1):
                color = safe_color if x == active_col else dim_color
                for p in PixelMap.get_column_pixels(self.is_big, x):
                    result[p] = color
        return result


class RandomPixelSparkle(Animation):
    """G10: Random individual character pixels flash random colors.
    Uses seed-based RNG and low density to avoid chaos.
    """

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        # Sane density: 3% instead of 10%
        num_sparkles = len(all_pixels) // 33 

        result: dict[tuple[int, int], str | int] = {}

        # Use the animation's RNG for consistency within the frame but variety between runs
        sparkle_pixels = self.rng.sample(all_pixels, min(num_sparkles, len(all_pixels)))
        for p in sparkle_pixels:
            color_idx = self.rng.randint(0, len(self.palette) - 1)
            result[p] = self.get_contrast_safe_color(self.palette.get(color_idx))

        return result


class CheckerboardFlash(Animation):
    """G13: Alternating pixels flash in checkerboard pattern."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        color_pair = self.palette.get(frame // 2)
        # 0 or 1
        parity = frame % 2

        result = {}
        for x, y in all_pixels:
            if (x + y) % 2 == parity:
                result[(x, y)] = color_pair
            else:
                result[(x, y)] = -1
        return result


class WordSplitBlink(Animation):
    """G9: "TELE" vs "CLAUDE" blink alternately."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        # Shifted +1: adjust split boundary
        split_x = 34 if self.is_big else 16

        color_pair = self.palette.get(frame // 2)
        safe_color = self.get_contrast_safe_color(color_pair)
        parity = frame % 2

        result = {}
        for x, y in all_pixels:
            is_tele = x < split_x
            if (is_tele and parity == 0) or (not is_tele and parity == 1):
                result[(x, y)] = safe_color
            else:
                result[(x, y)] = -1
        return result


class DiagonalSweepDR(Animation):
    """G11: Volumetric diagonal surge from top-left to bottom-right."""

    supports_small = False
    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(True)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        max_val = BIG_BANNER_WIDTH + BIG_BANNER_HEIGHT
        active = frame % max_val
        color_pair = self.palette.get(frame // max_val)
        safe_color = self.get_contrast_safe_color(color_pair)
        
        result = {}
        for x, y in self._all_pixels:
            dist = abs(((x - 1) + y) - active)
            # Volumetric surge width: 3 pixels
            if dist < 3:
                # Intensity falloff within the surge
                result[(x, y)] = safe_color
            else:
                result[(x, y)] = -1
        return result


class DiagonalSweepDL(Animation):
    """G12: Volumetric diagonal surge from top-right to bottom-left."""

    supports_small = False
    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(True)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        max_val = BIG_BANNER_WIDTH + BIG_BANNER_HEIGHT
        offset = BIG_BANNER_HEIGHT
        active = (frame % max_val) - offset
        color_pair = self.palette.get(frame // max_val)
        safe_color = self.get_contrast_safe_color(color_pair)

        result = {}
        for x, y in self._all_pixels:
            dist = abs(((x - 1) - y) - active)
            if dist < 3:
                result[(x, y)] = safe_color
            else:
                result[(x, y)] = -1
        return result


class LetterShimmer(Animation):
    """G14: Each letter rapidly cycles through colors independently."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        result = {}
        for i in range(num_letters):
            # Each letter has its own random-ish phase
            color_idx = (frame + i * 3) % len(self.palette)
            color_pair = self.palette.get(color_idx)
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color_pair
        return result


class WavePulse(Animation):
    """G15: Color wave travels through word with trailing brightness gradient."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        active_x = frame % width

        result = {}
        for x in range(width):
            dist = abs(x - active_x)
            if dist == 0:
                color_pair = self.palette.get(frame // width)
            elif dist < 5:
                # Dimmer trailing effect (using palette indices if possible, or just -1)
                color_pair = self.palette.get((frame // width) - 1)
            else:
                color_pair = -1

            for p in PixelMap.get_column_pixels(self.is_big, x):
                result[p] = color_pair
        return result


# ---------------------------------------------------------------------------
# TrueColor (24-bit HEX) animation suite
# ---------------------------------------------------------------------------


class SunsetGradient(Animation):
    """TC1: Smooth sunset gradient with procedural hue-rotation."""

    theme_filter = "light"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        self.hue_anchor = self.rng.randint(0, 360)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i; p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i %= 6
        if i == 0: return int(v * 255), int(t * 255), int(p * 255)
        if i == 1: return int(q * 255), int(v * 255), int(p * 255)
        if i == 2: return int(p * 255), int(v * 255), int(t * 255)
        if i == 3: return int(p * 255), int(q * 255), int(v * 255)
        if i == 4: return int(t * 255), int(p * 255), int(v * 255)
        return int(v * 255), int(p * 255), int(q * 255)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        modulation = self.get_modulation(frame)
        shift = (frame * 0.5 * modulation) % 1.0
        
        result = {}
        for x, y in self._all_pixels:
            x_factor = x / max(width - 1, 1)
            # Hue morphs across the width and over time
            hue = (self.hue_anchor + (x_factor + shift) * 60) % 360 / 360.0
            r, g, b = self._hsv_to_rgb(hue, 0.8, 0.9)
            result[(x, y)] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
        return result


class CloudsPassing(Animation):
    """TC2: Fluffy white clouds drifting horizontally.
    Rooftop atmosphere that lets the billboard show through.
    """

    theme_filter = "light"
    is_external_light = True
    _CLOUD = "#FFFFFF"
    _NUM_CLOUDS = 3

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result: dict[tuple[int, int], str | int] = {}
        modulation = self.get_modulation(frame)
        
        for i in range(self._NUM_CLOUDS):
            speed = (i + 1) * modulation
            cx = int(self.seed + frame * speed + i * (width // self._NUM_CLOUDS)) % width
            cy = i % height
            color = self.get_contrast_safe_color(self._CLOUD)
            for dx in range(-2, 3):
                nx = (cx + dx) % width
                result[(nx, cy)] = color
                if height > 1:
                    result[(nx, (cy + 1) % height)] = color
        return result


class FloatingBalloons(Animation):
    """TC3: Brightly colored clusters floating upward from the bottom."""

    theme_filter = "light"
    _COLORS = ["#FF3366", "#FFD700", "#33CC66", "#FF3366", "#FFD700"]
    _NUM_BALLOONS = 5

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result: dict[tuple[int, int], str | int] = {}
        period = height + 4
        for i in range(self._NUM_BALLOONS):
            cx = (i * 13 + (frame // period) * 7) % width
            cy = (height - 1) - (frame % period)
            color = self.get_contrast_safe_color(self._COLORS[i % len(self._COLORS)])
            for dx in range(-1, 2):
                for dy in range(-1, 1):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        result[(nx, ny)] = color
        return result


class NeonCyberpunk(Animation):
    """TC4: High-contrast cyan and magenta pulsing in diagonal waves."""

    _CYAN = "#00FFFF"
    _MAGENTA = "#FF00FF"
    _PERIOD = 8

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        half = self._PERIOD
        full = self._PERIOD * 2
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            diagonal = (x + y * 2 + frame * 2) % full
            result[(x, y)] = self._CYAN if diagonal < half else self._MAGENTA
        return result


class AuroraBorealis(Animation):
    """TC5: Wavy, organic vertical pulses with procedural hue-shifting."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        self.hue_anchor = self.rng.randint(0, 360)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i; p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i %= 6
        if i == 0: return int(v * 255), int(t * 255), int(p * 255)
        if i == 1: return int(q * 255), int(v * 255), int(p * 255)
        if i == 2: return int(p * 255), int(v * 255), int(t * 255)
        if i == 3: return int(p * 255), int(q * 255), int(v * 255)
        if i == 4: return int(t * 255), int(p * 255), int(v * 255)
        return int(v * 255), int(p * 255), int(q * 255)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        modulation = self.get_modulation(frame)
        phase = self.seed % 100
        
        for x, y in self._all_pixels:
            wave = math.sin(x * 0.3 + frame * 0.1 * modulation + phase) * 0.3 + 0.5
            y_factor = y / max(height - 1, 1)
            # Procedural hue shift for aurora variety
            hue = (self.hue_anchor + (y_factor * 0.7 + wave * 0.3) * 120) % 360 / 360.0
            r, g, b = self._hsv_to_rgb(hue, 0.8, 0.8)
            result[(x, y)] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
        return result


class LavaLamp(Animation):
    """TC6: Organic morphing blobs with procedural hue-shifting."""

    theme_filter = "light"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        self.hue_anchor = self.rng.randint(0, 360)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i; p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i %= 6
        if i == 0: return int(v * 255), int(t * 255), int(p * 255)
        if i == 1: return int(q * 255), int(v * 255), int(p * 255)
        if i == 2: return int(p * 255), int(v * 255), int(t * 255)
        if i == 3: return int(p * 255), int(q * 255), int(v * 255)
        if i == 4: return int(t * 255), int(p * 255), int(v * 255)
        return int(v * 255), int(p * 255), int(q * 255)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        result = {}
        modulation = self.get_modulation(frame)
        phase = self.seed % 50
        for x, y in self._all_pixels:
            blob = math.sin(x * 0.2 + frame * 0.05 * modulation + phase) * math.cos(y * 0.5 + frame * 0.03 * modulation)
            factor = (blob + 1) / 2
            # Procedural hue shift for lava variety
            hue = (self.hue_anchor + factor * 40) % 360 / 360.0
            r, g, b = self._hsv_to_rgb(hue, 0.9, 0.9)
            result[(x, y)] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
        return result


class StarryNight(Animation):
    """TC7: Midnight blue sky with randomly twinkling white and yellow stars."""

    theme_filter = "dark"
    _BG = "#0B1021"
    _STAR_WHITE = "#FFFFFF"
    _STAR_YELLOW = "#FFFACD"

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        result = {}
        for p in PixelMap.get_all_pixels(self.is_big):
            if self.rng.random() < 0.05:
                color = self._STAR_WHITE if self.rng.random() < 0.7 else self._STAR_YELLOW
                result[p] = self.get_contrast_safe_color(color)
            else:
                result[p] = -1
        return result


class MatrixRain(Animation):
    """TC8: Neon green raindrop columns with fading trails falling downward.
    Integrated with neon-tube physics: drops splash when hitting letters.
    """

    theme_filter = "dark"
    _TRAIL = 4

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        # Use billboard plate gray as background if needed, but here we return -1 for transparent parts
        result: dict[tuple[int, int], str | int] = {}
        period = height + self._TRAIL
        
        # Organic velocity: each column has a slightly different offset/speed logic
        modulation = self.get_modulation(frame)

        for x in range(width):
            # Column-specific random seed-based offset
            col_seed = (self.seed + x * 123) % 100
            head_y = int((frame * modulation + col_seed) % period)
            
            for dy in range(self._TRAIL + 1):
                y = head_y - dy
                if 0 <= y < height:
                    # Check if hitting a letter for "splash" effect
                    is_letter = any(x >= start and x <= end for start, end in (BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS))
                    
                    if dy == 0:
                        color = "#39FF14" # Neon Green
                        if is_letter:
                            # Splash flare
                            color = "#AFFF80"
                    else:
                        factor = 1.0 - dy / self._TRAIL
                        g = int(0x64 * factor)
                        color = rgb_to_hex(0, g, 0)
                    
                    result[(x, y)] = self.get_contrast_safe_color(color)
        return result


class HighSunBird(Animation):
    """TC16: A bird flits across the top of the letters, casting a high-sun shadow.
    Light Mode / Day Mode only.
    """

    theme_filter = "light"
    supports_small = True
    is_shadow_caster = True
    is_external_light = True

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if self.dark_mode:
            return {} # Night mode doesn't have birds/sun

        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        
        # Bird movement: flapping and flitting across the top
        modulation = self.get_modulation(frame)
        bx = int((frame * modulation) % (width + 10)) - 5
        by = 0 # Stays at the top
        flap = (frame // 2) % 2 # Flap every 2 frames
        
        result: dict[tuple[int, int], str | int] = {}
        
        # Render Bird
        bird_pixels = [(bx, by)]
        if flap == 0:
            bird_pixels.extend([(bx - 1, by), (bx + 1, by)]) # Wings spread
        else:
            bird_pixels.extend([(bx, by - 1)]) # Wings up
            
        for px, py in bird_pixels:
            if 0 <= px < width and 0 <= py < height:
                result[(px, py)] = "#404040" # Bird color
                
        # Shadow: Cast downward/diagonal (Golden Angle)
        sx, sy = bx + 1, by + 1
        shadow_pixels = [(sx, sy)]
        if flap == 0:
            shadow_pixels.extend([(sx - 1, sy), (sx + 1, sy)])
        else:
            shadow_pixels.extend([(sx, sy - 1)])

        for px, py in shadow_pixels:
            if 0 <= px < width and 0 <= py < height:
                # Dim the underlying character
                result[(px, py)] = "#202020" # Shadow dimming
                
        return result


class SearchlightSweep(Animation):
    """TC17: Focused searchlight from below, casting upward shadows.
    Night Mode / Dark Mode only.
    """

    theme_filter = "dark"
    supports_small = True
    is_shadow_caster = True
    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)

    def _is_batman_mask(self, x: int, y: int, cx: int, cy: int) -> bool:
        """High-fidelity relative mask for a Batman-like silhouette."""
        # Normalize coordinates relative to mask center (cy-3)
        dx, dy = x - cx, y - (cy - 3)
        adx = abs(dx)
        
        # Row-by-row mask logic
        if dy == -1: # Ears
            return adx == 1
        if dy == 0:  # Head and upper body
            return adx <= 1
        if dy == 1:  # Upper wings
            return adx <= 3
        if dy == 2:  # Lower wings
            return adx <= 2
        return False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.dark_mode:
            return {}

        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        
        modulation = self.get_modulation(frame)
        # Searchlight center sweeps horizontally at the bottom
        cx = int((frame * modulation * 2) % (width + 40)) - 20
        cy = height - 1
        
        # Large beam for mask visibility
        radius = 6 + int(math.sin(frame * 0.1) * 2)
        
        result: dict[tuple[int, int], str | int] = {}
        for x, y in self._all_pixels:
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            if dist < radius:
                if self._is_batman_mask(x, y, cx, cy):
                    # The Silhouette (Shadow)
                    result[(x, y)] = "#151515" 
                else:
                    # The bright searchlight flare
                    intensity = 1.0 - (dist / radius)
                    flare = int(180 + intensity * 75)
                    result[(x, y)] = rgb_to_hex(flare, flare, flare)
            else:
                # Outside the beam
                result[(x, y)] = -1

        return result


class CinematicPrismSweep(Animation):
    """TC18: Volumetric beam with random hue morphing and pivoting angle."""

    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        # Choose two random hue anchors
        self.hue_start = self.rng.randint(0, 360)
        self.hue_end = (self.hue_start + self.rng.randint(60, 180)) % 360
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - f * s)
        t = v * (1.0 - (1.0 - f) * s)
        i %= 6
        if i == 0: return int(v * 255), int(t * 255), int(p * 255)
        if i == 1: return int(q * 255), int(v * 255), int(p * 255)
        if i == 2: return int(p * 255), int(v * 255), int(t * 255)
        if i == 3: return int(p * 255), int(q * 255), int(v * 255)
        if i == 4: return int(t * 255), int(p * 255), int(v * 255)
        if i == 5: return int(v * 255), int(p * 255), int(q * 255)
        return 0, 0, 0

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        
        modulation = self.get_modulation(frame)
        progress = frame / self.duration_frames
        
        # Pivot angle from 30 to 60 degrees
        angle_deg = 30 + (progress * 30)
        angle_rad = math.radians(angle_deg)
        
        # Current hue
        current_hue = (self.hue_start + (self.hue_end - self.hue_start) * progress) / 360.0
        r, g, b = self._hsv_to_rgb(current_hue, 0.8, 1.0)
        color = rgb_to_hex(r, g, b)
        safe_color = self.get_contrast_safe_color(color)
        
        # Sweep position
        max_dist = width * math.cos(angle_rad) + height * math.sin(angle_rad)
        active_dist = progress * max_dist * modulation * 1.5
        
        result: dict[tuple[int, int], str | int] = {}
        for x, y in self._all_pixels:
            # Projection onto the sweep vector
            d = x * math.cos(angle_rad) + y * math.sin(angle_rad)
            # Volumetric beam width: 4 pixels
            if abs(d - active_dist) < 4:
                result[(x, y)] = safe_color
            else:
                # Return transparent sentinel for areas outside the beam
                result[(x, y)] = -1
                
        return result


class OceanWaves(Animation):
    """TC9: Sine-wave water swells with procedural hue-shifting."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        self.hue_anchor = self.rng.randint(0, 360)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i; p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i %= 6
        if i == 0: return int(v * 255), int(t * 255), int(p * 255)
        if i == 1: return int(q * 255), int(v * 255), int(p * 255)
        if i == 2: return int(p * 255), int(v * 255), int(t * 255)
        if i == 3: return int(p * 255), int(q * 255), int(v * 255)
        if i == 4: return int(t * 255), int(p * 255), int(v * 255)
        return int(v * 255), int(p * 255), int(q * 255)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        modulation = self.get_modulation(frame)
        
        for x, y in self._all_pixels:
            wave = math.sin(x * 0.3 - frame * 0.1 * modulation + (self.seed % 10)) * 0.3 + 0.5
            y_factor = y / max(height - 1, 1)
            # Procedural hue shift for water variety
            hue = (self.hue_anchor + (y_factor + wave) * 30) % 360 / 360.0
            r, g, b = self._hsv_to_rgb(hue, 0.8, 0.8)
            result[(x, y)] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
        return result


class FireBreath(Animation):
    """TC10: Volumetric fire with procedural hue-morphing and organic flicker."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        # Randomize fire hue anchors
        self.hue_anchor = self.rng.randint(0, 360)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i; p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i %= 6
        if i == 0: return int(v * 255), int(t * 255), int(p * 255)
        if i == 1: return int(q * 255), int(v * 255), int(p * 255)
        if i == 2: return int(p * 255), int(v * 255), int(t * 255)
        if i == 3: return int(p * 255), int(q * 255), int(v * 255)
        if i == 4: return int(t * 255), int(p * 255), int(v * 255)
        return int(v * 255), int(p * 255), int(q * 255)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        modulation = self.get_modulation(frame)
        
        # Base hue shifts slightly per run, but stays in the fire range
        # Red is 0, Yellow is 60. We'll shift the anchor.
        hue_base = (self.hue_anchor % 40) / 360.0 # 0 to 40 deg
        
        for x, y in self._all_pixels:
            # Bottom (y=high) is hot (Yellow), Top (y=0) is cool (Red)
            y_factor = y / max(height - 1, 1)
            flicker = self.rng.random() * 0.3 * modulation
            intensity = min(1.0, y_factor + flicker)
            
            # Hotter (bottom) = more yellow shift (up to +40 degrees)
            # Cooler (top) = more red
            hue = (hue_base + (y_factor * 40 / 360.0)) % 1.0
            
            # Value (brightness) is higher at bottom
            val = 0.4 + (y_factor * 0.6)
            
            r, g, b = self._hsv_to_rgb(hue, 0.9, val)
            result[(x, y)] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
            
        return result


class SynthwaveWireframe(Animation):
    """TC11: Magenta horizon at bottom fading to dark purple sky at top."""

    _grad = MultiGradient(["#1A0533", "#6600CC", "#FF00FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            factor = y / max(height - 1, 1)
            result[(x, y)] = self._grad.get(factor)
        return result


class PrismaticShimmer(Animation):
    """TC12: Rapid, chaotic sparkling of bright jewel tones across all pixels."""

    _COLORS = ["#FF0000", "#0000FF", "#00FF00", "#FF00FF", "#00FFFF", "#FFD700", "#FF69B4", "#8A2BE2"]

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        result = {}
        for p in PixelMap.get_all_pixels(self.is_big):
            result[p] = random.choice(self._COLORS)
        return result


class BreathingHeart(Animation):
    """TC13: Organic central pulse with procedural hue-rotation."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        self.hue_anchor = self.rng.randint(0, 360)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i; p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i %= 6
        if i == 0: return int(v * 255), int(t * 255), int(p * 255)
        if i == 1: return int(q * 255), int(v * 255), int(p * 255)
        if i == 2: return int(p * 255), int(v * 255), int(t * 255)
        if i == 3: return int(p * 255), int(q * 255), int(v * 255)
        if i == 4: return int(t * 255), int(p * 255), int(v * 255)
        return int(v * 255), int(p * 255), int(q * 255)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        cx, cy = width / 2, height / 2
        max_dist = math.sqrt(cx**2 + cy**2)
        
        modulation = self.get_modulation(frame)
        pulse = (math.sin(frame * 0.3 * modulation) + 1) / 2
        
        result = {}
        for x, y in self._all_pixels:
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            norm_dist = dist / max_dist if max_dist > 0 else 0
            # Pulse intensity
            intensity = max(0.0, min(1.0, 1.0 - norm_dist + (pulse - 0.5) * 0.4))
            # Procedural hue shift for heartbeat variety
            hue = (self.hue_anchor + intensity * 30) % 360 / 360.0
            r, g, b = self._hsv_to_rgb(hue, 0.9, intensity)
            result[(x, y)] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
        return result


class IceCrystals(Animation):
    """TC14: Frosty ice with procedural hue-shifting."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        self.hue_anchor = self.rng.randint(0, 360)

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        i = int(h * 6.0); f = (h * 6.0) - i; p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
        i %= 6
        if i == 0: return int(v * 255), int(t * 255), int(p * 255)
        if i == 1: return int(q * 255), int(v * 255), int(p * 255)
        if i == 2: return int(p * 255), int(v * 255), int(t * 255)
        if i == 3: return int(p * 255), int(q * 255), int(v * 255)
        if i == 4: return int(t * 255), int(p * 255), int(v * 255)
        return int(v * 255), int(p * 255), int(q * 255)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        
        modulation = self.get_modulation(frame)
        progress = frame / max(self.duration_frames - 1, 1)
        coverage = progress * 1.5 * modulation
        
        result = {}
        for x, y in self._all_pixels:
            edge_x = min(x, width - 1 - x) / max(width / 2, 1)
            edge_y = min(y, height - 1 - y) / max(height / 2, 1)
            edge_dist = min(edge_x, edge_y)
            intensity = max(0.0, min(1.0, coverage - edge_dist))
            
            # Procedural hue shift for frosty variety
            hue = (self.hue_anchor + intensity * 20) % 360 / 360.0
            # Desaturated for 'ice' look
            r, g, b = self._hsv_to_rgb(hue, 0.3 * intensity, 0.9)
            result[(x, y)] = self.get_contrast_safe_color(rgb_to_hex(r, g, b))
        return result


class Bioluminescence(Animation):
    """TC15: Pitch-black sea with neon blue agents leaving glowing trails."""

    theme_filter = "dark"
    _NUM_AGENTS = 8
    _TRAIL_DECAY = 10

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        self._agents = [[self.rng.randint(0, width - 1), self.rng.randint(0, height - 1)] for _ in range(self._NUM_AGENTS)]
        self._trails: dict[tuple[int, int], int] = {}
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        # Move agents randomly
        for agent in self._agents:
            agent[0] = (agent[0] + self.rng.choice([-1, 0, 1])) % width
            agent[1] = (agent[1] + self.rng.choice([-1, 0, 1])) % height
        # Decay existing trails
        self._trails = {pos: val - 1 for pos, val in self._trails.items() if val > 1}
        # Stamp agent positions into trails
        for agent in self._agents:
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


# Helper to provide some animations for random selection
GENERAL_ANIMATIONS = [
    LetterWaveLR,
    LetterWaveRL,
    LineSweepTopBottom,
    LineSweepBottomTop,
    MiddleOutVertical,
    WithinLetterSweepLR,
    WithinLetterSweepRL,
    WordSplitBlink,
    DiagonalSweepDR,
    DiagonalSweepDL,
    LetterShimmer,
    WavePulse,
    # TrueColor animations
    SunsetGradient,
    CloudsPassing,
    FloatingBalloons,
    AuroraBorealis,
    LavaLamp,
    StarryNight,
    MatrixRain,
    OceanWaves,
    FireBreath,
    BreathingHeart,
    IceCrystals,
    Bioluminescence,
    HighSunBird,
    SearchlightSweep,
    CinematicPrismSweep,
]
