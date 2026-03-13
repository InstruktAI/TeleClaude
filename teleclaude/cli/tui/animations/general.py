"""General-purpose TUI animations (gradients, sweeps, atmospheric)."""

from __future__ import annotations

import math

from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex
from teleclaude.cli.tui.animations.base import Animation, Spectrum
from teleclaude.cli.tui.animations.creative import ColorSweep, EQBars, Glitch, LaserScan, LavaLamp, NeonFlicker, Plasma

# Re-exported from submodules for backward-compatible import paths.
from teleclaude.cli.tui.animations.particles import (
    Bioluminescence,
    CinematicPrismSweep,
    FireBreath,
    MatrixRain,
    SearchlightSweep,
)
from teleclaude.cli.tui.animations.sky import GlobalSky, SkyEntity
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_LETTERS,
    BIG_BANNER_WIDTH,
    LOGO_HEIGHT,
    LOGO_LETTERS,
    LOGO_WIDTH,
    PixelMap,
)

__all__ = [
    "GENERAL_ANIMATIONS",
    "Bioluminescence",
    "BlinkSweep",
    "CinematicPrismSweep",
    "DiagonalSweepDL",
    "DiagonalSweepDR",
    "FireBreath",
    "FullSpectrumCycle",
    "GlobalSky",
    "LetterShimmer",
    "LetterWaveLR",
    "LetterWaveRL",
    "LineSweepBottomTop",
    "LineSweepTopBottom",
    "MatrixRain",
    "MiddleOutVertical",
    "SearchlightSweep",
    "SkyEntity",
    "SunsetGradient",
    "WavePulse",
    "WithinLetterSweepLR",
    "WithinLetterSweepRL",
    "WordSplitBlink",
]


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
