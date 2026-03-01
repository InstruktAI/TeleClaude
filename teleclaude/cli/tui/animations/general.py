"""General-purpose TUI animations (gradients, sweeps, atmospheric)."""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Dict, List, Tuple

from teleclaude.cli.tui.animations.base import (
    Animation,
    RenderBuffer,
    Spectrum,
    Z_BILLBOARD,
    Z_FOREGROUND,
    Z_SKY,
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
    from teleclaude.cli.tui.animation_colors import ColorPalette


class GlobalSky(Animation):
    """TC20: Global background canvas with Day/Night physical states.
    Paints the entire header area (Z-0) including margins.
    """

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs.setdefault("target", "header")
        super().__init__(*args, **kwargs)
        # Full possible terminal width
        self.width = 200
        self.height = 10
        self._all_pixels = [(x, y) for y in range(self.height) for x in range(self.width)]
        
        # Day: Azure gradient. Night: Super Dark Purple Glow.
        self.day_sky = Spectrum(["#87CEEB", "#B0E0E6", "#E0F7FA", "#B0E0E6"])
        # From Deep Black to Super Dark Midnight Purple
        self.night_sky = Spectrum(["#000000", "#05000A", "#0F001A", "#05000A"])
        
        # Symmetric Stars ONLY (No moons/dots)
        self.star_types = ["+", "*", "\u2726"] # Plus, Star, Sparkle
        self.stars = []
        for _ in range(80):
            self.stars.append({
                "pos": (self.rng.randint(0, self.width - 1), self.rng.randint(0, self.height - 1)),
                "char": self.rng.choice(self.star_types),
                "phase": self.rng.random() * math.pi * 2,
                "speed": 0.3 + self.rng.random() * 0.4
            })
            
        # Drifting Clouds (Day)
        self.clouds = []
        for _ in range(6):
            self.clouds.append({
                "x": self.rng.randint(0, self.width),
                "y": self.rng.randint(0, self.height - 3),
                "speed": 0.25 + self.rng.random() * 0.3
            })

    def update(self, frame: int) -> RenderBuffer:
        buffer = RenderBuffer()
        is_party = self.animation_mode == "party"
        
        if self.dark_mode:
            # 1. Background Super Dark Purple Gradient
            for x, y in self._all_pixels:
                pos_factor = y / max(1, self.height - 1)
                buffer.add_pixel(Z_SKY, x, y, self.night_sky.get_color(pos_factor))
            
            # 2. Stars (Mode Aware Twinkling)
            for star in self.stars:
                if is_party:
                    # Animate twinkling in Party Mode
                    twinkle = (math.sin(frame * star["speed"] + star["phase"]) + 1.0) / 2.0
                else:
                    # Fixed stars in Periodic Mode (based on unique phase)
                    twinkle = (math.sin(star["phase"]) + 1.0) / 2.0
                
                if twinkle > 0.4:
                    buffer.add_pixel(Z_FOREGROUND, star["pos"][0], star["pos"][1], star["char"])
        else:
            # 1. Background Blue Gradient
            for x, y in self._all_pixels:
                pos_factor = y / max(1, self.height - 1)
                buffer.add_pixel(Z_SKY, x, y, self.day_sky.get_color(pos_factor))
                
            # 2. Drifting Vapor Clouds
            for cloud in self.clouds:
                # Clouds drift in both modes
                cx = int(cloud["x"] + frame * cloud["speed"]) % (self.width + 40) - 20
                cy = cloud["y"]
                for dx in range(12):
                    for dy in range(2):
                        if 0 <= cx + dx < self.width:
                            buffer.add_pixel(Z_FOREGROUND, cx + dx, cy + dy, "\u2501")

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
                color = self.spec.get_color(y / max(1, height - 1))
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
        return result


class LineSweepBottomTop(Animation):
    """G7: Vertical volumetric sweep through neon tubes from bottom to top."""

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
                color = self.spec.get_color(y / max(1, height - 1))
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
        return result


class MiddleOutVertical(Animation):
    """G8: Vertical volumetric center expansion (Big only)."""

    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF0000", "#FFFF00", "#FF0000"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big: return {}
        height = BIG_BANNER_HEIGHT
        modulation = self.get_modulation(frame)
        active_step = (frame * modulation * 0.5) % 4
        active_rows = {2 - int(active_step), 3 + int(active_step)}
        
        result = {}
        for i in range(len(BIG_BANNER_LETTERS)):
            for x, y in PixelMap.get_letter_pixels(True, i):
                min_dist = min(abs(y - ar) for ar in active_rows)
                surge = 1.0 - (min_dist / 2.0) if min_dist < 2 else 0.0
                color = self.spec.get_color(y / max(1, height - 1))
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
        return result


class WithinLetterSweepLR(Animation):
    """G4: Vertical volumetric surge L→R through neon tubes."""

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
                color = self.spec.get_color((x-1)/width)
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
            
        return result


class WithinLetterSweepRL(Animation):
    """G5: Vertical volumetric surge R→L through neon tubes."""

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
                color = self.spec.get_color((x-1)/width)
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
            
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

    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#00FF00", "#FFFF00", "#00FF00"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big: return {}
        width, height = BIG_BANNER_WIDTH, BIG_BANNER_HEIGHT
        max_val = width + height
        modulation = self.get_modulation(frame)
        active = (frame * modulation * 1.5) % (max_val + 10) - 5
        
        result = {}
        num_letters = len(BIG_BANNER_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(True, i):
                surge = self.linear_surge((x - 1) + y, active, 4.0)
                color = self.spec.get_color(((x - 1) + y) / max_val)
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
        return result


class DiagonalSweepDL(Animation):
    """G12: Volumetric diagonal surge from top-right to bottom-left."""

    supports_small = False

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF00FF", "#00FFFF", "#FF00FF"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big: return {}
        width, height = BIG_BANNER_WIDTH, BIG_BANNER_HEIGHT
        max_val = width + height
        modulation = self.get_modulation(frame)
        active = (width - 1) - ((frame * modulation * 1.5) % (max_val + 10) - 5)
        
        result = {}
        num_letters = len(BIG_BANNER_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(True, i):
                surge = self.linear_surge((x - 1) - y, active, 4.0)
                color = self.spec.get_color(((x - 1) + y) / max_val)
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
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
            color_idx = (frame + i * 3) % len(self.palette)
            color_pair = self.palette.get(color_idx)
            color = self.enforce_vibrancy(self.get_contrast_safe_color(color_pair))
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class WavePulse(Animation):
    """G15: Volumetric color surge travels through neon tubes."""

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
                color = self.spec.get_color((x-1)/width)
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
            
        return result


class BlinkSweep(Animation):
    """TC21: High-speed high-vibrancy sawtooth pulse sweeping L->R."""

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
                color = self.spec.get_color((x-1)/width)
                color = self.enforce_vibrancy(color)
                intensity = 0.6 + (surge * 0.4)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))
        return result


# ---------------------------------------------------------------------------
# TrueColor (24-bit HEX) animation suite
# ---------------------------------------------------------------------------


class SunsetGradient(Animation):
    """TC1: Smooth sunset gradient with procedural hue-rotation."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        
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


class CloudsPassing(Animation):
    """TC2: Fluffy white clouds drifting horizontally.
    Rooftop atmosphere that lets the billboard show through.
    """

    theme_filter = "light"
    is_external_light = True
    _CLOUD = "#E0E0E0"

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        modulation = self.get_modulation(frame)
        
        # Multiple cloud anchors
        clouds = [
            int(frame * 0.2 * modulation) % (width + 20) - 10,
            int(frame * 0.15 * modulation + 30) % (width + 20) - 10,
        ]
        
        result = {}
        for x, y in PixelMap.get_all_pixels(self.is_big):
            # Check proximity to any cloud
            in_cloud = any(abs(x - cx) < 5 and abs(y - 2) < 2 for cx in clouds)
            if in_cloud:
                color = self.get_contrast_safe_color(self._CLOUD)
                result[(x, y)] = color
            else:
                result[(x, y)] = -1
        return result


class FloatingBalloons(Animation):
    """TC3: Colorful balloons floating upward."""

    _COLORS = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF"]

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        modulation = self.get_modulation(frame)
        
        result = {}
        for i in range(5):
            bx = (i * 15 + int(frame * 0.1 * modulation)) % width
            by = (height - 1) - int(frame * 0.2 * modulation + i * 2) % (height + 5)
            
            if 0 <= by < height:
                color = self.get_contrast_safe_color(self._COLORS[i % len(self._COLORS)])
                result[(bx, by)] = color
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
                    result[(x, y)] = "#FFFFFF" # Bright head
                elif 0 < dist < 8:
                    intensity = int(255 * (1.0 - dist / 8.0))
                    result[(x, y)] = rgb_to_hex(0, intensity, 0)
        return result


class FireBreath(Animation):
    """TC10: Volumetric fireplace effect across all neon tubes."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.spec = Spectrum(["#FF0000", "#FF4500", "#FFFF00", "#FF4500", "#FF0000"])

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        result = {}
        modulation = self.get_modulation(frame)
        
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                y_factor = y / max(height - 1, 1)
                # Organic flicker (per-pixel noise)
                flicker = self.rng.random() * 0.4 * modulation
                # Heat intensity: 1.0 at bottom, 0.0 at top
                intensity = min(1.0, (1.0 - y_factor) + flicker)
                
                color = self.spec.get_color(y_factor)
                color = self.enforce_vibrancy(color)
                from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
                r, g, b = hex_to_rgb(color)
                # Vivid Dimmed base 60% + heat highlight
                v = 0.6 + (intensity * 0.4)
                result[(x, y)] = rgb_to_hex(int(r * v), int(g * v), int(b * v))
            
        return result


class HighSunBird(Animation):
    """TC16: Silhouette of a bird passing in front of a bright sun (Light Mode only)."""

    theme_filter = "light"
    is_external_light = True

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._all_pixels = PixelMap.get_all_pixels(self.is_big)

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        
        modulation = self.get_modulation(frame)
        # Bird moves horizontally
        bx = int((frame * modulation * 2) % (width + 40)) - 20
        by = 2
        
        result: dict[tuple[int, int], str | int] = {}
        for x, y in self._all_pixels:
            # The Sun (High intensity yellow flare)
            dist_sun = math.sqrt((x - 10)**2 + (y - 1)**2)
            if dist_sun < 5:
                color = rgb_to_hex(255, 255, int(200 * (dist_sun/5)))
                result[(x, y)] = self.get_contrast_safe_color(color)
            # The Bird (V-shape silhouette)
            elif abs(x - bx) < 3 and abs(y - by) < 1:
                result[(x, y)] = "#333333"
            else:
                result[(x, y)] = -1
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
                    from teleclaude.cli.tui.animation_colors import rgb_to_hex
                    result[(x, y)] = rgb_to_hex(flare, flare, flare)
            else:
                # Outside the beam
                result[(x, y)] = -1

        return result


class CinematicPrismSweep(Animation):
    """TC18: Volumetric prism beam with random hue morphing and pivoting angle."""

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
        from teleclaude.cli.tui.animation_colors import rgb_to_hex, hex_to_rgb
        color = rgb_to_hex(r, g, b)
        safe_color = self.get_electric_neon(self.get_contrast_safe_color(color))
        
        max_dist = width * math.cos(angle_rad) + height * math.sin(angle_rad)
        active_dist = progress * max_dist * modulation * 1.5
        
        result: dict[tuple[int, int], str | int] = {}
        
        # 1. Base Neon state (Vivid Dimmed 60%)
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                d = (x - 1) * math.cos(angle_rad) + y * math.sin(angle_rad)
                surge = 1.0 - (abs(d - active_dist) / 4.0) if abs(d - active_dist) < 4 else 0.0
                intensity = 0.6 + (surge * 0.4)
                r, g, b = hex_to_rgb(safe_color)
                result[(x, y)] = rgb_to_hex(int(r * intensity), int(g * intensity), int(b * intensity))

        # 2. Billboard Reflection (only where beam hits)
        for x, y in self._all_pixels:
            if (x, y) in result: continue # Skip neon (already handled)
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
        self._agents = [[random.randint(0, self.width - 1), random.randint(0, self.height - 1)] for _ in range(self._NUM_AGENTS)]
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


# Helper to provide some animations for random selection
GENERAL_ANIMATIONS = [
    # Neon Core
    LineSweepTopBottom,
    MiddleOutVertical,
    WithinLetterSweepLR,
    WordSplitBlink,
    LetterShimmer,
    WavePulse,
    BlinkSweep,
    # Unified Atmosphere
    GlobalSky,
    FireBreath,
    HighSunBird,
    SearchlightSweep,
    CinematicPrismSweep,
]
