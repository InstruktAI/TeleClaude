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


from teleclaude.cli.tui.animations.base import (
    Animation,
    RenderBuffer,
    Spectrum,
    Z_BILLBOARD,
    Z_FOREGROUND,
    Z_SKY,
)


class GlobalSky(Animation):
    """TC20: Global background canvas with Day/Night physical states."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)
        # Create harmonious spectrums
        self.day_sky = Spectrum(["#87CEEB", "#B0E0E6", "#ADD8E6"]) # Sky Blue -> Powder -> Light Blue
        self.night_sky = Spectrum(["#000000", "#08001A", "#191970"]) # Black -> Deep Purple -> Midnight Blue
        
        # Twinkling Stars (Symmetric ONLY)
        self.star_types = [".", "+", "*", "\u2022"] # Dot, Plus, Star, Bullet
        self.stars = []
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        for _ in range(30):
            self.stars.append({
                "pos": (self.rng.randint(0, width - 1), self.rng.randint(0, height - 1)),
                "char": self.rng.choice(self.star_types),
                "phase": self.rng.random() * math.pi * 2
            })
            
        # Drifting Clouds
        self.clouds = []
        for _ in range(3):
            self.clouds.append({
                "x": self.rng.randint(0, width),
                "y": self.rng.randint(0, height - 2),
                "speed": 0.05 + self.rng.random() * 0.1
            })

    def update(self, frame: int) -> RenderBuffer:
        buffer = RenderBuffer()
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        
        # 1. The Background (Z_SKY)
        if self.dark_mode:
            # Night Sky
            for x, y in self._all_pixels:
                pos_factor = y / max(1, height - 1)
                buffer.add_pixel(Z_SKY, x, y, self.night_sky.get_color(pos_factor))
            
            # Stars (Twinkling)
            for star in self.stars:
                twinkle = (math.sin(frame * 0.1 + star["phase"]) + 1.0) / 2.0
                if twinkle > 0.3: # Only show if bright enough
                    buffer.add_pixel(Z_FOREGROUND, star["pos"][0], star["pos"][1], star["char"])
        else:
            # Day Sky
            for x, y in self._all_pixels:
                pos_factor = y / max(1, height - 1)
                buffer.add_pixel(Z_SKY, x, y, self.day_sky.get_color(pos_factor))
                
            # Clouds (Simple drift)
            for cloud in self.clouds:
                cx = int(cloud["x"] + frame * cloud["speed"]) % (width + 20) - 10
                cy = cloud["y"]
                # Cloud shape (procedural vapor)
                for dx in range(5):
                    for dy in range(2):
                        if (cx + dx, cy + dy) in self._all_pixels:
                            buffer.add_pixel(Z_FOREGROUND, cx + dx, cy + dy, "\u2501") # Horizontal bar

        return buffer


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
    """G6: Vertical volumetric sweep through neon tubes from top to bottom."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        # Harmonious 3-stop spectrum (e.g. Electric Blue -> Cyan -> Electric Blue)
        self.spec = Spectrum(["#0000FF", "#00FFFF", "#0000FF"]) 

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        modulation = self.get_modulation(frame)
        active_y = (frame * modulation * 0.5) % (height + 2) - 1
        
        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                # 1. Surge Intensity
                surge = self.linear_surge(y, active_y, 1.5)
                # 2. Get Color from Spectrum
                color = self.spec.get_color(y / max(1, height - 1))
                color = self.enforce_vibrancy(color)
                # 3. Material Response (Neon): Dimmed 40% base + surge highlight
                intensity = 0.4 + (surge * 0.6)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
        return result


class LineSweepBottomTop(Animation):
    """G7: Vertical volumetric sweep through neon tubes from bottom to top."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF00FF", "#FF0000", "#FF00FF"]) # Magenta -> Red -> Magenta

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        modulation = self.get_modulation(frame)
        active_y = (height - 1) - ((frame * modulation * 0.5) % (height + 2) - 1)
        
        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                surge = self.linear_surge(y, active_y, 1.5)
                color = self.spec.get_color(y / max(1, height - 1))
                color = self.enforce_vibrancy(color)
                intensity = 0.4 + (surge * 0.6)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
        return result


class MiddleOutVertical(Animation):
    """G8: Vertical volumetric center expansion (Big only)."""

    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF0000", "#FFFF00", "#FF0000"]) # Red -> Yellow -> Red
        self._all_pixels = PixelMap.get_all_pixels(True)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big: return {}
        height = BIG_BANNER_HEIGHT
        modulation = self.get_modulation(frame)
        active_step = (frame * modulation * 0.5) % 4 # 0, 1, 2, 3
        # Middle rows: 2 and 3
        active_rows = {2 - int(active_step), 3 + int(active_step)}
        
        result = {}
        for x, y in self._all_pixels:
            is_letter = PixelMap.get_is_letter("banner", x, y)
            if not is_letter:
                result[(x, y)] = -1
                continue
                
            # Proximity to any active row
            min_dist = min(abs(y - ar) for ar in active_rows)
            surge = 1.0 - (min_dist / 2.0) if min_dist < 2 else 0.0
            
            color = self.spec.get_color(y / max(1, height - 1))
            color = self.enforce_vibrancy(color)
            
            intensity = 0.4 + (surge * 0.6)
            from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
            r, g, b = hex_to_rgb(color)
            result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
            
        return result


class WithinLetterSweepLR(Animation):
    """G4: Volumetric vertical sweep L→R through sign area."""

    supports_small = False
    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#00FF00", "#00FFFF", "#00FF00"]) # Green -> Cyan -> Green
        self._all_pixels = PixelMap.get_all_pixels(True)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH
        modulation = self.get_modulation(frame)
        active_x = (frame * modulation * 1.5) % (width + 10) - 5
        
        result = {}
        for x, y in self._all_pixels:
            surge = self.linear_surge(x - 1, active_x, 3.0)
            is_letter = PixelMap.get_is_letter("banner", x, y)
            
            if surge > 0 or is_letter:
                color = self.spec.get_color((x-1)/width)
                color = self.enforce_vibrancy(color)
                # Material response: letters are always at least 40%
                intensity = (0.4 if is_letter else 0.0) + (surge * 0.6)
                if intensity > 0:
                    from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                    r, g, b = hex_to_rgb(color)
                    result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
                else:
                    result[(x, y)] = -1
            else:
                result[(x, y)] = -1
        return result


class WithinLetterSweepRL(Animation):
    """G5: Volumetric vertical sweep R→L through sign area."""

    supports_small = False
    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#00FFFF", "#0000FF", "#00FFFF"]) # Cyan -> Blue -> Cyan
        self._all_pixels = PixelMap.get_all_pixels(True)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH
        modulation = self.get_modulation(frame)
        active_x = (width - 1) - ((frame * modulation * 1.5) % (width + 10) - 5)
        
        result = {}
        for x, y in self._all_pixels:
            surge = self.linear_surge(x - 1, active_x, 3.0)
            is_letter = PixelMap.get_is_letter("banner", x, y)
            
            if surge > 0 or is_letter:
                color = self.spec.get_color((x-1)/width)
                color = self.enforce_vibrancy(color)
                intensity = (0.4 if is_letter else 0.0) + (surge * 0.6)
                if intensity > 0:
                    from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                    r, g, b = hex_to_rgb(color)
                    result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
                else:
                    result[(x, y)] = -1
            else:
                result[(x, y)] = -1
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

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#00FF00", "#FFFF00", "#00FF00"]) # Green -> Yellow -> Green
        self._all_pixels = PixelMap.get_all_pixels(True)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big: return {}
        width, height = BIG_BANNER_WIDTH, BIG_BANNER_HEIGHT
        max_val = width + height
        modulation = self.get_modulation(frame)
        active = (frame * modulation * 1.5) % (max_val + 10) - 5
        
        result = {}
        for x, y in self._all_pixels:
            is_letter = PixelMap.get_is_letter("banner", x, y)
            if not is_letter:
                result[(x, y)] = -1
                continue
                
            # Surge intensity based on diagonal projection
            surge = self.linear_surge((x - 1) + y, active, 4.0)
            color = self.spec.get_color(((x - 1) + y) / max_val)
            color = self.enforce_vibrancy(color)
            
            # Neon response: 40% base + 60% surge
            intensity = 0.4 + (surge * 0.6)
            from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
            r, g, b = hex_to_rgb(color)
            result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
            
        return result


class DiagonalSweepDL(Animation):
    """G12: Volumetric diagonal surge from top-right to bottom-left."""

    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF00FF", "#00FFFF", "#FF00FF"]) # Magenta -> Cyan -> Magenta
        self._all_pixels = PixelMap.get_all_pixels(True)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big: return {}
        width, height = BIG_BANNER_WIDTH, BIG_BANNER_HEIGHT
        max_val = width + height
        modulation = self.get_modulation(frame)
        active = (width - 1) - ((frame * modulation * 1.5) % (max_val + 10) - 5)
        
        result = {}
        for x, y in self._all_pixels:
            is_letter = PixelMap.get_is_letter("banner", x, y)
            if not is_letter:
                result[(x, y)] = -1
                continue
                
            surge = self.linear_surge((x - 1) - y, active, 4.0)
            color = self.spec.get_color(((x - 1) + y) / max_val)
            color = self.enforce_vibrancy(color)
            
            intensity = 0.4 + (surge * 0.6)
            from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
            r, g, b = hex_to_rgb(color)
            result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
            
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
    """G15: Volumetric color surge travels through billboard sign area."""

    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#0000FF", "#00FFFF", "#FFFFFF", "#00FFFF", "#0000FF"])
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        modulation = self.get_modulation(frame)
        active_x = (frame * modulation * 1.5) % (width + 10) - 5
        
        result = {}
        for x, y in self._all_pixels:
            surge = self.linear_surge(x - 1, active_x, 4.0)
            is_letter = PixelMap.get_is_letter(self.target, x, y)
            
            if surge > 0 or is_letter:
                color = self.spec.get_color((x-1)/width)
                color = self.enforce_vibrancy(color)
                intensity = (0.4 if is_letter else 0.0) + (surge * 0.6)
                if intensity > 0:
                    from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                    r, g, b = hex_to_rgb(color)
                    result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
                else:
                    result[(x, y)] = -1
            else:
                result[(x, y)] = -1
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
            return adx <= 2 # Wider feet
            
        # Ears/Head (top of silhouette)
        if dy == -1: return adx == 1
        if dy == 0:  return adx <= 1
        
        # Wide Wings/Cape (middle rows) - wingspan 19 total
        if dy == 1:  return adx <= 9 
        if dy == 2:  return adx <= 6 # Cape narrowing
        
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
            if dist < radius:
                if self._is_batman_mask(x, y, cx, cy):
                    # Grounded shadow silhouette
                    result[(x, y)] = "#151515" 
                else:
                    # Bright searchlight flare (high intensity)
                    intensity = 1.0 - (dist / radius)
                    flare = int(180 + intensity * 75)
                    result[(x, y)] = rgb_to_hex(flare, flare, flare)
            else:
                # Outside the beam
                result[(x, y)] = -1

        return result


class CinematicPrismSweep(Animation):
    """TC18: Volumetric neon beam with random hue morphing and pivoting angle."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        # Choose two random hue anchors
        self.hue_start = self.rng.randint(0, 360)
        self.hue_end = (self.hue_start + self.rng.randint(60, 180)) % 360
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)

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
        progress = frame / self.duration_frames
        
        # Pivot angle from 30 to 60 degrees
        angle_deg = 30 + (progress * 30)
        angle_rad = math.radians(angle_deg)
        
        # Current hue
        current_hue = (self.hue_start + (self.hue_end - self.hue_start) * progress) / 360.0
        r, g, b = self._hsv_to_rgb(current_hue, 0.8, 1.0)
        color = rgb_to_hex(r, g, b)
        
        # Volumetric colors: ALL must be Electric Neon
        safe_color = self.get_electric_neon(self.get_contrast_safe_color(color))
        dim_color = self.get_electric_neon(self.get_contrast_safe_color(rgb_to_hex(int(r * 0.4), int(g * 0.4), int(b * 0.4))))
        
        # Sweep position
        max_dist = width * math.cos(angle_rad) + height * math.sin(angle_rad)
        active_dist = progress * max_dist * modulation * 1.5
        
        result: dict[tuple[int, int], str | int] = {}
        for x, y in self._all_pixels:
            # Projection onto the sweep vector (shifted +1)
            d = (x - 1) * math.cos(angle_rad) + y * math.sin(angle_rad)
            result[(x, y)] = safe_color if abs(d - active_dist) < 4 else dim_color
                
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
        self.hue_anchor = self.rng.randint(0, 360)
        self.spec = Spectrum(["#FF0000", "#FF4500", "#FFFF00", "#FF4500", "#FF0000"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        modulation = self.get_modulation(frame)
        
        # Flame sway (Slow horizontal sine)
        sway = math.sin(frame * 0.1) * 2.0
        
        for x, y in self._all_pixels:
            y_factor = y / max(height - 1, 1)
            # Organic flicker (faster noise)
            flicker = self.rng.random() * 0.4 * modulation
            # Heat intensity: higher at bottom
            intensity = min(1.0, (1.0 - y_factor) + flicker)
            
            # Apply sway to the x-coordinate for organic "licking" flames
            dist_from_sway = abs((x - 1) - (BIG_BANNER_WIDTH // 2 + sway))
            sway_factor = 1.0 - (dist_from_sway / 20.0) if dist_from_sway < 20 else 0.0
            
            if intensity * sway_factor > 0.3:
                color = self.spec.get_color(y_factor)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                # Value floor 0.4, surges with heat
                v = 0.4 + (intensity * sway_factor * 0.6)
                result[(x, y)] = rgb_to_hex(int(r * v), int(g * v), int(b * v))
            else:
                result[(x, y)] = -1
            
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
    is_external_light = True
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
    # Unified Atmosphere
    GlobalSky,
    FireBreath,
    HighSunBird,
    SearchlightSweep,
    CinematicPrismSweep,
]
