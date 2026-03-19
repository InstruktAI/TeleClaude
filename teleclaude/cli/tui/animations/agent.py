"""Agent-specific activity animations."""

from __future__ import annotations

import random
from collections.abc import Callable

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_HEIGHT,
    BIG_BANNER_LETTERS,
    LOGO_HEIGHT,
    LOGO_LETTERS,
    PixelMap,
)


def _letter_count(is_big: bool) -> int:
    return len(BIG_BANNER_LETTERS if is_big else LOGO_LETTERS)


def _render_letter_colors(
    is_big: bool,
    color_for_letter: Callable[[int], str | int],
) -> dict[tuple[int, int], str | int]:
    result: dict[tuple[int, int], str | int] = {}
    for index in range(_letter_count(is_big)):
        color = color_for_letter(index)
        for pixel in PixelMap.get_letter_pixels(is_big, index):
            result[pixel] = color
    return result


def _highlight_and_dim(anim: Animation) -> tuple[str, str]:
    highlight = anim.enforce_vibrancy(anim.palette.get(2))
    return highlight, anim.get_dim_color(highlight)


class AgentPulse(Animation):
    """A1: All letter pixels pulse synchronously through agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        color_idx = frame % len(self.palette)
        color_pair = self.palette.get(color_idx)
        safe_color = self.enforce_vibrancy(color_pair)
        return _render_letter_colors(self.is_big, lambda _index: safe_color)


class AgentWaveLR(Animation):
    """A2: Letter-by-letter wave using agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = _letter_count(self.is_big)
        active_letter_idx = frame % num_letters
        hi_color, dim_color = _highlight_and_dim(self)
        return _render_letter_colors(
            self.is_big,
            lambda index: hi_color if index == active_letter_idx else dim_color,
        )


class AgentWaveRL(Animation):
    """A3: Letter-by-letter wave right-to-left using agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = _letter_count(self.is_big)
        active_letter_idx = (num_letters - 1) - (frame % num_letters)
        hi_color, dim_color = _highlight_and_dim(self)
        return _render_letter_colors(
            self.is_big,
            lambda index: hi_color if index == active_letter_idx else dim_color,
        )


class AgentLineSweep(Animation):
    """A9: Volumetric horizontal line sweep through neon tubes."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        active_row = frame % height
        hi_color, dim_color = _highlight_and_dim(self)

        result: dict[tuple[int, int], str | int] = {}
        for index in range(_letter_count(self.is_big)):
            for x, y in PixelMap.get_letter_pixels(self.is_big, index):
                result[(x, y)] = hi_color if y == active_row else dim_color
        return result


class AgentMiddleOut(Animation):
    """A14: Vertical volumetric center expansion (Big only)."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        step = frame % 3
        active_rows = {2 - step, 3 + step}
        hi_color, dim_color = _highlight_and_dim(self)

        result: dict[tuple[int, int], str | int] = {}
        for index in range(len(BIG_BANNER_LETTERS)):
            for x, y in PixelMap.get_letter_pixels(True, index):
                result[(x, y)] = hi_color if y in active_rows else dim_color
        return result


class AgentSparkle(Animation):
    """A7: Random pixels flash with agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        num_sparkles = len(all_pixels) // 15

        result: dict[tuple[int, int], str | int] = {pixel: -1 for pixel in all_pixels}
        letter_pixels = [pixel for pixel in all_pixels if PixelMap.get_is_letter(self.target, pixel[0], pixel[1])]
        sparkle_pixels = random.sample(letter_pixels, min(num_sparkles, len(letter_pixels)))
        for pixel in sparkle_pixels:
            result[pixel] = self.enforce_vibrancy(self.palette.get(random.randint(0, len(self.palette) - 1)))
        return result


class AgentHeartbeat(Animation):
    """A4: Strong beat highlight on neon tubes."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        pattern = [2, 0, 2, 0, 0, 0]
        color_idx = pattern[frame % len(pattern)]
        color_pair = self.enforce_vibrancy(self.palette.get(color_idx))
        return _render_letter_colors(self.is_big, lambda _index: color_pair)


class AgentWordSplit(Animation):
    """A6: "TELE" and "CLAUDE" blink alternately."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        parity = frame % 2
        hi_color, dim_color = _highlight_and_dim(self)
        return _render_letter_colors(
            self.is_big,
            lambda index: hi_color if (index < 4 and parity == 0) or (index >= 4 and parity == 1) else dim_color,
        )


class AgentFadeCycle(Animation):
    """A8: Smooth transition through agent colors on neon tubes."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        sequence = [0, 1, 2, 1]
        color_idx = sequence[frame % len(sequence)]
        color_pair = self.enforce_vibrancy(self.palette.get(color_idx))
        return _render_letter_colors(self.is_big, lambda _index: color_pair)


class AgentBreathing(Animation):
    """A12: Gentle synchronized pulse on neon tubes."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        sequence = [0, 0, 1, 1, 2, 2, 1, 1]
        color_idx = sequence[frame % len(sequence)]
        color_pair = self.enforce_vibrancy(self.palette.get(color_idx))
        return _render_letter_colors(self.is_big, lambda _index: color_pair)


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
