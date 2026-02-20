"""Pixel mapping for TUI animations."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Legacy constants for backward compatibility/initialization
BIG_BANNER_WIDTH = 82
BIG_BANNER_HEIGHT = 6
BIG_BANNER_LETTERS = [
    (0, 8),  # T
    (9, 16),  # E
    (17, 24),  # L
    (25, 32),  # E
    (33, 40),  # C
    (41, 48),  # L
    (49, 56),  # A
    (57, 65),  # U
    (66, 73),  # D
    (74, 81),  # E
]

LOGO_WIDTH = 39
LOGO_HEIGHT = 3
LOGO_LETTERS = [
    (0, 2),  # T
    (4, 6),  # E
    (8, 10),  # L
    (12, 14),  # E
    (16, 18),  # C
    (20, 22),  # L
    (24, 26),  # A
    (28, 30),  # U
    (32, 34),  # D
    (36, 38),  # E
]


@dataclass
class RenderTarget:
    """Definition of a render target area."""

    name: str
    width: int
    height: int
    letters: List[Tuple[int, int]]  # List of (start_x, end_x) tuples for each letter


class TargetRegistry:
    """Registry for animation render targets."""

    def __init__(self):
        self._targets: Dict[str, RenderTarget] = {}
        # Register default targets
        self.register("banner", BIG_BANNER_WIDTH, BIG_BANNER_HEIGHT, BIG_BANNER_LETTERS)
        self.register("logo", LOGO_WIDTH, LOGO_HEIGHT, LOGO_LETTERS)

    def register(self, name: str, width: int, height: int, letters: Optional[List[Tuple[int, int]]] = None) -> None:
        """Register a new render target."""
        self._targets[name] = RenderTarget(name, width, height, letters or [])

    def get(self, name: str) -> Optional[RenderTarget]:
        return self._targets.get(name)


# Global registry instance
target_registry = TargetRegistry()


class PixelMap:
    """Helper for pixel-based calculations."""

    @staticmethod
    def _resolve_target(target_arg: bool | str) -> str:
        if isinstance(target_arg, bool):
            return "banner" if target_arg else "logo"
        return target_arg

    @staticmethod
    def get_letter_pixels(
        target_arg: bool | str | None = None, letter_idx: int = 0, *, is_big: bool | None = None
    ) -> List[Tuple[int, int]]:
        """Get all (x, y) coordinates for a specific letter in the target."""
        if is_big is not None:
            target_name = "banner" if is_big else "logo"
        elif target_arg is not None:
            target_name = PixelMap._resolve_target(target_arg)
        else:
            return []

        target = target_registry.get(target_name)

        # No letters defined for this target
        if not target or not target.letters:
            return []

        if letter_idx < 0 or letter_idx >= len(target.letters):
            return []

        start_x, end_x = target.letters[letter_idx]
        pixels = []
        for y in range(target.height):
            for x in range(start_x, end_x + 1):
                pixels.append((x, y))
        return pixels

    @staticmethod
    def get_all_pixels(target_arg: bool | str | None = None, *, is_big: bool | None = None) -> List[Tuple[int, int]]:
        """Get all (x, y) coordinates for the entire grid of the target."""
        if is_big is not None:
            target_name = "banner" if is_big else "logo"
        elif target_arg is not None:
            target_name = PixelMap._resolve_target(target_arg)
        else:
            return []

        target = target_registry.get(target_name)
        if not target:
            return []

        pixels = []
        for y in range(target.height):
            for x in range(target.width):
                pixels.append((x, y))
        return pixels

    @staticmethod
    def get_row_pixels(
        target_arg: bool | str | None = None, row_idx: int = 0, *, is_big: bool | None = None
    ) -> List[Tuple[int, int]]:
        """Get all pixels in a specific row of the target."""
        if is_big is not None:
            target_name = "banner" if is_big else "logo"
        elif target_arg is not None:
            target_name = PixelMap._resolve_target(target_arg)
        else:
            return []

        target = target_registry.get(target_name)
        if not target:
            return []

        if row_idx < 0 or row_idx >= target.height:
            return []

        return [(x, row_idx) for x in range(target.width)]

    @staticmethod
    def get_column_pixels(
        target_arg: bool | str | None = None, col_idx: int = 0, *, is_big: bool | None = None
    ) -> List[Tuple[int, int]]:
        """Get all pixels in a specific column of the target."""
        if is_big is not None:
            target_name = "banner" if is_big else "logo"
        elif target_arg is not None:
            target_name = PixelMap._resolve_target(target_arg)
        else:
            return []

        target = target_registry.get(target_name)
        if not target:
            return []

        if col_idx < 0 or col_idx >= target.width:
            return []

        return [(col_idx, y) for y in range(target.height)]
