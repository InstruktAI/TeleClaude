"""People 'Heartbeat' section animations — prototype.

4 Animation subclasses for config section states:
  - PeopleIdle: Heartbeat double-pulse (bump-BUMP...rest...bump-BUMP)
  - PeopleInteraction: Stadium wave (letters illuminate sequentially)
  - PeopleSuccess: Group hug (all highlight, gold cascade from center)
  - PeopleError: Lonely ping (center letter blinks, others dim)

All extend the Animation ABC. Use PixelMap for coordinates.
Return Dict[(x,y), int] from update() where int is curses pair ID.

Palette indices (via PeoplePalette):
  0=subtle(95), 1=muted(131), 2=normal(174), 3=highlight(210), 4=accent/gold(220)
"""

from typing import Dict, Tuple

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import (
    BIG_BANNER_LETTERS,
    LOGO_LETTERS,
    PixelMap,
)


class PeopleIdle(Animation):
    """Heartbeat: double-beat pulse pattern (bump-BUMP ... bump-BUMP ...).

    All pixels pulse through a heartbeat rhythm:
    muted, muted, normal, highlight, normal, muted, muted, highlight, normal, muted
    Quick double-tap (bump-BUMP) then rest. Like a human heartbeat.

    Pattern from Art Director: [1, 1, 2, 3, 2, 1, 1, 3, 2, 1]

    Speed: 150ms/frame. Loops indefinitely.
    """

    def __init__(self, palette, is_big, duration_seconds=9999, speed_ms=150):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        # Double-beat pattern: bump(normal)-BUMP(highlight)-rest-bump-BUMP-rest
        self._pattern = [1, 1, 2, 3, 2, 1, 1, 3, 2, 1]

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        idx = self._pattern[frame % len(self._pattern)]
        color = self.palette.get(idx)
        return {p: color for p in self._all_pixels}

    def is_complete(self, frame: int) -> bool:
        # Idle: never completes (looping in production)
        return False


class PeopleInteraction(Animation):
    """Stadium wave: letters light up sequentially L->R with 2-frame delay.

    Each letter peaks at highlight(3) then relaxes to normal(2).
    Letters activate with a 2-frame delay between them, creating a
    cascading wave effect. Like doing "the wave" in a stadium.

    Speed: 120ms/frame. Duration ~3s.
    """

    def __init__(self, palette, is_big, duration_seconds=3.0, speed_ms=120):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        self._num_letters = len(self._letters)
        self._delay = 2  # frames between letter activations

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        for i in range(self._num_letters):
            # When this letter activates (based on 2-frame delay)
            activation_frame = i * self._delay
            elapsed = frame - activation_frame

            if elapsed < 0:
                # Not yet activated
                color = self.palette.get(1)  # muted
            elif elapsed == 0:
                # Peak — highlight
                color = self.palette.get(3)  # highlight
            elif elapsed == 1:
                # Relaxing — normal
                color = self.palette.get(2)  # normal
            else:
                # Settled — normal (stays warm)
                color = self.palette.get(2)  # normal

            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color

        return result


class PeopleSuccess(Animation):
    """Group hug: all highlight simultaneously, then gold cascade from center.

    Phase 1 (frames 0-3): All pixels pulse to highlight(3).
    Phase 2 (frames 4-14): Gold accent(4) expands outward from center letter,
    one letter per frame. Creates a warm embracing feel.
    Phase 3 (frames 15+): All gold(4).

    Speed: 100ms/frame. Duration ~2s.
    """

    def __init__(self, palette, is_big, duration_seconds=2.0, speed_ms=100):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        self._num_letters = len(self._letters)
        self._all_pixels = PixelMap.get_all_pixels(is_big)
        self._center = self._num_letters // 2
        self._pulse_end = 4
        self._cascade_end = self._pulse_end + self._center + 1

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        if frame < self._pulse_end:
            # Phase 1: All highlight
            for p in self._all_pixels:
                result[p] = self.palette.get(3)  # highlight

        elif frame < self._cascade_end:
            # Phase 2: Gold expanding from center
            radius = frame - self._pulse_end
            for i in range(self._num_letters):
                dist = abs(i - self._center)
                if dist <= radius:
                    color = self.palette.get(4)  # accent (gold)
                else:
                    color = self.palette.get(3)  # highlight
                for p in PixelMap.get_letter_pixels(self.is_big, i):
                    result[p] = color
        else:
            # Phase 3: All gold
            for p in self._all_pixels:
                result[p] = self.palette.get(4)  # accent (gold)

        return result


class PeopleError(Animation):
    """Lonely ping: center letter blinks muted, all others subtle.

    The middle letter (index 5, 'L' in CLAUDE) blinks between muted(1)
    and subtle(0). All other letters stay at subtle(0). Like a single
    person reaching out with no response — isolated, waiting.

    Speed: 300ms/frame (slow, lonely). Duration ~3s.
    """

    def __init__(self, palette, is_big, duration_seconds=3.0, speed_ms=300):
        super().__init__(palette, is_big, duration_seconds, speed_ms)
        self._letters = BIG_BANNER_LETTERS if is_big else LOGO_LETTERS
        self._num_letters = len(self._letters)
        self._center_idx = self._num_letters // 2

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        result = {}

        for i in range(self._num_letters):
            if i == self._center_idx:
                # Center letter blinks
                if frame % 2 == 0:
                    color = self.palette.get(1)  # muted (visible ping)
                else:
                    color = self.palette.get(0)  # subtle (dim)
            else:
                color = self.palette.get(0)  # subtle (all others dim)

            for p in PixelMap.get_letter_pixels(self.is_big, i):
                result[p] = color

        return result
