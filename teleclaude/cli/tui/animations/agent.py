"""Agent-specific activity animations."""

from __future__ import annotations

import random

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_LETTERS,
    LOGO_HEIGHT,
    LOGO_LETTERS,
    PixelMap,
)


class AgentPulse(Animation):
    """A1: All letter pixels pulse synchronously through agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        color_idx = frame % len(self.palette)
        color_pair = self.palette.get(color_idx)
        # Force high vibrancy
        safe_color = self.enforce_vibrancy(color_pair)

        result = {}
        for i in range(len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                result[(x, y)] = safe_color
        return result


class AgentWaveLR(Animation):
    """A2: Letter-by-letter wave using agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = frame % num_letters

        hi_color = self.enforce_vibrancy(self.palette.get(2))
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

        try:
            r, g, b = hex_to_rgb(hi_color)
            dim_color = rgb_to_hex(int(r * 0.6), int(g * 0.6), int(b * 0.6))
        except (ValueError, TypeError):
            dim_color = hi_color

        result = {}
        for i in range(num_letters):
            color = hi_color if i == active_letter_idx else dim_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class AgentWaveRL(Animation):
    """A3: Letter-by-letter wave right-to-left using agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = (num_letters - 1) - (frame % num_letters)

        hi_color = self.enforce_vibrancy(self.palette.get(2))
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

        try:
            r, g, b = hex_to_rgb(hi_color)
            dim_color = rgb_to_hex(int(r * 0.6), int(g * 0.6), int(b * 0.6))
        except (ValueError, TypeError):
            dim_color = hi_color

        result = {}
        for i in range(num_letters):
            color = hi_color if i == active_letter_idx else dim_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class AgentLineSweep(Animation):
    """A9: Volumetric horizontal line sweep through neon tubes."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        active_row = frame % height

        hi_color = self.enforce_vibrancy(self.palette.get(2))
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

        try:
            r, g, b = hex_to_rgb(hi_color)
            dim_color = rgb_to_hex(int(r * 0.6), int(g * 0.6), int(b * 0.6))
        except (ValueError, TypeError):
            dim_color = hi_color

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for x, y in PixelMap.get_letter_pixels(self.is_big, i):
                color = hi_color if y == active_row else dim_color
                result[(x, y)] = color
        return result


class AgentMiddleOut(Animation):
    """A14: Vertical volumetric center expansion (Big only)."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        step = frame % 3
        active_rows = {2 - step, 3 + step}

        hi_color = self.enforce_vibrancy(self.palette.get(2))
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

        try:
            r, g, b = hex_to_rgb(hi_color)
            dim_color = rgb_to_hex(int(r * 0.6), int(g * 0.6), int(b * 0.6))
        except (ValueError, TypeError):
            dim_color = hi_color

        result = {}
        for i in range(len(BIG_BANNER_LETTERS)):
            for x, y in PixelMap.get_letter_pixels(True, i):
                color = hi_color if y in active_rows else dim_color
                result[(x, y)] = color
        return result


class AgentSparkle(Animation):
    """A7: Random pixels flash with agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        num_sparkles = len(all_pixels) // 15

        result: dict[tuple[int, int], str | int] = {p: -1 for p in all_pixels}
        # Only sparkle on letters
        letter_pixels = [p for p in all_pixels if PixelMap.get_is_letter(self.target, p[0], p[1])]
        sparkle_pixels = random.sample(letter_pixels, min(num_sparkles, len(letter_pixels)))
        for p in sparkle_pixels:
            result[p] = self.enforce_vibrancy(self.palette.get(random.randint(0, len(self.palette) - 1)))
        return result


class AgentHeartbeat(Animation):
    """A4: Strong beat highlight on neon tubes."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        pattern = [2, 0, 2, 0, 0, 0]
        color_idx = pattern[frame % len(pattern)]
        color_pair = self.enforce_vibrancy(self.palette.get(color_idx))

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color_pair
        return result


class AgentWordSplit(Animation):
    """A6: \"TELE\" and \"CLAUDE\" blink alternately."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        parity = frame % 2
        hi_color = self.enforce_vibrancy(self.palette.get(2))
        from teleclaude.cli.tui.animation_colors import hex_to_rgb, rgb_to_hex

        try:
            r, g, b = hex_to_rgb(hi_color)
            dim_color = rgb_to_hex(int(r * 0.6), int(g * 0.6), int(b * 0.6))
        except (ValueError, TypeError):
            dim_color = hi_color

        result = {}
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        for i in range(num_letters):
            is_tele = i < 4
            color = hi_color if (is_tele and parity == 0) or (not is_tele and parity == 1) else dim_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class AgentFadeCycle(Animation):
    """A8: Smooth transition through agent colors on neon tubes."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        sequence = [0, 1, 2, 1]
        color_idx = sequence[frame % len(sequence)]
        color_pair = self.enforce_vibrancy(self.palette.get(color_idx))

        result = {}
        for i in range(len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)):
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color_pair
        return result


class AgentBreathing(Animation):
    """A12: Gentle synchronized pulse on neon tubes."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        sequence = [0, 0, 1, 1, 2, 2, 1, 1]
        color_idx = sequence[frame % len(sequence)]
        color_pair = self.enforce_vibrancy(self.palette.get(color_idx))

        result = {}
        for i in range(len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)):
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color_pair
        return result


# Selection list for randomizer
AGENT_ANIMATIONS = [
    AgentPulse,
    AgentWaveLR,
    AgentWaveRL,
    AgentLineSweep,
    AgentMiddleOut,
    AgentHeartbeat,
    AgentWordSplit,
    AgentFadeCycle,
    AgentBreathing,
]
