"""Agent-specific activity animations."""

from __future__ import annotations

import random

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


class AgentPulse(Animation):
    """A1: All pixels pulse synchronously through agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        # Cycle through Muted (0), Normal (1), Highlight (2)
        # We can use a sine wave or just simple cycling
        color_idx = frame % len(self.palette)
        color_pair = self.palette.get(color_idx)

        all_pixels = PixelMap.get_all_pixels(self.is_big)
        return {pixel: color_pair for pixel in all_pixels}


class AgentWaveLR(Animation):
    """A2: Letter-by-letter wave using agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = frame % num_letters
        
        mid_color = self.palette.get(2) # Highlight
        base_color = self.palette.get(0) # Muted

        result = {}
        for i in range(num_letters):
            color = mid_color if i == active_letter_idx else base_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class AgentWaveRL(Animation):
    """A3: Letter-by-letter wave right-to-left using agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter_idx = (num_letters - 1) - (frame % num_letters)
        
        mid_color = self.palette.get(2)
        base_color = self.palette.get(0)

        result = {}
        for i in range(num_letters):
            color = mid_color if i == active_letter_idx else base_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class AgentLineSweep(Animation):
    """A9: Volumetric horizontal line sweep through letters using agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        height = BIG_BANNER_HEIGHT if self.is_big else LOGO_HEIGHT
        active_row = frame % height
        
        # Muted (0) for base, Highlight (2) for surge
        mid_color = self.palette.get(2)
        base_color = self.palette.get(0)

        result = {}
        for r in range(height):
            current_color = mid_color if r == active_row else base_color
            for p in PixelMap.get_row_pixels(self.is_big, r):
                result[p] = current_color
        return result


class AgentMiddleOut(Animation):
    """A14: Vertical volumetric center expansion (Big only) using agent colors."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}

        height = BIG_BANNER_HEIGHT
        step = frame % 3
        active_rows = {2 - step, 3 + step}
        
        mid_color = self.palette.get(2) # Highlight
        base_color = self.palette.get(0) # Muted

        result = {}
        for r in range(height):
            current_color = mid_color if r in active_rows else base_color
            for p in PixelMap.get_row_pixels(self.is_big, r):
                result[p] = current_color
        return result


class AgentSparkle(Animation):
    """A7: Random pixels flash with random agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        num_sparkles = len(all_pixels) // 15

        result: dict[tuple[int, int], str | int] = {p: -1 for p in all_pixels}
        sparkle_pixels = random.sample(all_pixels, num_sparkles)
        for p in sparkle_pixels:
            result[p] = self.palette.get(random.randint(0, len(self.palette) - 1))
        return result


class AgentWithinLetterSweep(Animation):
    """A11: Within each letter, pixels sweep L→R using agent colors (Big only)."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}

        num_letters = len(BIG_BANNER_LETTERS)
        mid_color = self.palette.get(2) # Highlight
        base_color = self.palette.get(0) # Muted
        
        result = {}
        for i in range(num_letters):
            start_x, end_x = BIG_BANNER_LETTERS[i]
            letter_width = end_x - start_x + 1
            active_col_offset = frame % letter_width
            active_col = start_x + active_col_offset

            for x in range(start_x, end_x + 1):
                current_color = mid_color if x == active_col else base_color
                for p in PixelMap.get_column_pixels(self.is_big, x):
                    result[p] = current_color
        return result


class AgentHeartbeat(Animation):
    """A4: All pixels pulse with strong beat (Highlight) then rest (Muted)."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        # Beat pattern: Highlight, Muted, Highlight, Muted, Muted, Muted
        pattern = [2, 0, 2, 0, 0, 0]
        color_idx = pattern[frame % len(pattern)]
        color_pair = self.palette.get(color_idx)

        all_pixels = PixelMap.get_all_pixels(self.is_big)
        return {pixel: color_pair for pixel in all_pixels}


class AgentWordSplit(Animation):
    """A6: "TELE" and "CLAUDE" alternate between Muted and Normal/Highlight."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        split_x = 33 if self.is_big else 15

        # Parity 0: TELE Highlight, CLAUDE Muted
        # Parity 1: TELE Muted, CLAUDE Highlight
        parity = frame % 2

        result = {}
        for x, y in all_pixels:
            is_tele = x < split_x
            if (is_tele and parity == 0) or (not is_tele and parity == 1):
                result[(x, y)] = self.palette.get(2)  # Highlight
            else:
                result[(x, y)] = self.palette.get(0)  # Muted
        return result


class AgentLetterCascade(Animation):
    """A5: Letters light up sequentially, each using one of the agent colors."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        num_letters = len(BIG_BANNER_LETTERS if self.is_big else LOGO_LETTERS)
        active_letter = frame % num_letters
        
        mid_color = self.palette.get(2) # Highlight
        base_color = self.palette.get(0) # Muted
        
        result = {}
        for i in range(num_letters):
            color = mid_color if i == active_letter else base_color
            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color
        return result


class AgentFadeCycle(Animation):
    """A8: All pixels smoothly transition Muted <-> Normal <-> Highlight."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        # Simple cycle 0-1-2-1-0
        sequence = [0, 1, 2, 1]
        color_idx = sequence[frame % len(sequence)]
        color_pair = self.palette.get(color_idx)
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        return {p: color_pair for p in all_pixels}


class AgentSpotlight(Animation):
    """A10: Bright pixel cluster travels through word."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        width = BIG_BANNER_WIDTH if self.is_big else LOGO_WIDTH
        active_x = frame % width
        radius = 4
        result = {}
        for x in range(width):
            dist = abs(x - active_x)
            if dist < radius:
                # 2 for Highlight, 1 for Normal
                palette_idx = 2 if dist < 2 else 1
                color_pair = self.palette.get(palette_idx)
            else:
                color_pair = self.palette.get(0)  # Muted
            for p in PixelMap.get_column_pixels(self.is_big, x):
                result[p] = color_pair
        return result


class AgentBreathing(Animation):
    """A12: Gentle synchronized pulse with easing (simplified)."""

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        # Longer sequence for "breathing" effect
        # 0, 0, 1, 1, 2, 2, 1, 1, 0, 0
        sequence = [0, 0, 1, 1, 2, 2, 1, 1]
        color_idx = sequence[frame % len(sequence)]
        color_pair = self.palette.get(color_idx)
        all_pixels = PixelMap.get_all_pixels(self.is_big)
        return {p: color_pair for p in all_pixels}


class AgentDiagonalWave(Animation):
    """A13: Volumetric diagonal pixel sweep using agent color sequence."""

    supports_small = False

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        if not self.is_big:
            return {}
        max_val = BIG_BANNER_WIDTH + BIG_BANNER_HEIGHT
        active = frame % max_val
        
        hi_color = self.palette.get(2) # Highlight
        mid_color = self.palette.get(1) # Normal
        base_color = self.palette.get(0) # Muted
        
        result = {}
        for x, y in PixelMap.get_all_pixels(True):
            dist = abs(((x - 1) + y) - active)
            if dist == 0:
                color = hi_color
            elif dist < 3:
                color = mid_color
            else:
                color = base_color
            result[(x, y)] = color
        return result


# Helper to provide some animations for random selection
AGENT_ANIMATIONS = [
    AgentPulse,
    AgentWaveLR,
    AgentWaveRL,
    AgentLineSweep,
    AgentMiddleOut,
    AgentWithinLetterSweep,
    AgentHeartbeat,
    AgentWordSplit,
    AgentLetterCascade,
    AgentFadeCycle,
    AgentSpotlight,
    AgentBreathing,
    AgentDiagonalWave,
]
