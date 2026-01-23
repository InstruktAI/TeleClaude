"""Base classes for TUI animations."""

from abc import ABC, abstractmethod
from typing import Dict, Tuple

from teleclaude.cli.tui.animation_colors import ColorPalette


class Animation(ABC):
    """Abstract base class for all banner/logo animations."""

    # Class attribute: Override to False for big-only animations
    supports_small: bool = True

    def __init__(
        self,
        palette: ColorPalette,
        is_big: bool,
        duration_seconds: float,
        speed_ms: int = 100,
    ):
        """
        Args:
            palette: Color palette to use
            is_big: True for big banner, False for small logo
            duration_seconds: Total duration of the animation
            speed_ms: Milliseconds per frame (defaults to 100ms)
        """
        self.palette = palette
        self.is_big = is_big
        self.duration_frames = int(duration_seconds * 1000 / speed_ms)
        self.speed_ms = speed_ms

    @abstractmethod
    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        """Calculate colors for the given frame.

        Args:
            frame: Current frame number (0 to duration_frames - 1)

        Returns:
            Dictionary mapping (x, y) to color pair ID.
            Should only return pixels that have changed or are active in animation.
        """
        pass

    def is_complete(self, frame: int) -> bool:
        """Check if animation has finished."""
        return frame >= self.duration_frames
