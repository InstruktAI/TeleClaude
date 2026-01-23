"""Core animation engine for TUI banner and logo."""

from typing import Dict, Optional, Tuple

from teleclaude.cli.tui.animations.base import Animation


class AnimationEngine:
    """Manages animation state and timing for the banner and logo."""

    def __init__(self):
        self._big_animation: Optional[Animation] = None
        self._small_animation: Optional[Animation] = None
        self._big_frame_count: int = 0
        self._small_frame_count: int = 0
        # Double-buffering: front buffer for rendering, back buffer for updates
        self._colors_front: Dict[Tuple[int, int], int] = {}
        self._colors_back: Dict[Tuple[int, int], int] = {}
        self._logo_colors_front: Dict[Tuple[int, int], int] = {}
        self._logo_colors_back: Dict[Tuple[int, int], int] = {}
        self._is_enabled: bool = True

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool) -> None:
        self._is_enabled = value
        if not value:
            self.stop()

    def play(self, animation: Animation) -> None:
        """Start a new animation, interrupting the current one."""
        if not self._is_enabled:
            return

        if animation.is_big:
            self._big_animation = animation
            self._big_frame_count = 0
        else:
            self._small_animation = animation
            self._small_frame_count = 0

    def stop(self) -> None:
        """Stop all animations and clear colors."""
        self._big_animation = None
        self._small_animation = None
        self._big_frame_count = 0
        self._small_frame_count = 0
        self._colors_front.clear()
        self._colors_back.clear()
        self._logo_colors_front.clear()
        self._logo_colors_back.clear()

    def update(self) -> None:
        """Update animation state. Call this once per render cycle (~100ms).

        Uses double-buffering: updates are written to back buffer, then swapped to front.
        """
        # Update big animation in back buffer
        if self._big_animation:
            new_colors = self._big_animation.update(self._big_frame_count)
            self._colors_back.update(new_colors)
            self._big_frame_count += 1
            if self._big_animation.is_complete(self._big_frame_count):
                self._big_animation = None
                self._colors_back.clear()  # Clear colors to revert to default rendering
        else:
            self._colors_back.clear()

        # Update small animation in back buffer
        if self._small_animation:
            new_colors = self._small_animation.update(self._small_frame_count)
            self._logo_colors_back.update(new_colors)
            self._small_frame_count += 1
            if self._small_animation.is_complete(self._small_frame_count):
                self._small_animation = None
                self._logo_colors_back.clear()  # Clear colors to revert to default rendering
        else:
            self._logo_colors_back.clear()

        # Swap buffers atomically
        self._colors_front, self._colors_back = self._colors_back, self._colors_front
        self._logo_colors_front, self._logo_colors_back = (
            self._logo_colors_back,
            self._logo_colors_front,
        )

    def get_color(self, x: int, y: int, is_big: bool = True) -> Optional[int]:
        """Get the color pair ID for a specific pixel.

        Reads from front buffer (stable snapshot during rendering).

        Returns:
            Color pair ID or None if no animation color is set for this pixel.
        """
        if not self._is_enabled:
            return None

        colors = self._colors_front if is_big else self._logo_colors_front
        color = colors.get((x, y))
        if color == -1:
            return None
        return color

    def clear_colors(self) -> None:
        """Clear all active animation colors (both buffers)."""
        self._colors_front.clear()
        self._colors_back.clear()
        self._logo_colors_front.clear()
        self._logo_colors_back.clear()
