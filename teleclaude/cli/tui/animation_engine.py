"""Core animation engine for TUI banner and logo."""

import time
from collections import deque
from enum import IntEnum
from typing import Deque, Dict, Optional, Tuple

from teleclaude.cli.tui.animations.base import Animation


class AnimationPriority(IntEnum):
    """Animation priority levels (higher value = higher priority)."""

    PERIODIC = 1
    ACTIVITY = 2


class AnimationEngine:
    """Manages animation state and timing for the banner and logo.

    Supports priority-based animation queuing:
    - Activity animations (higher priority) interrupt periodic animations
    - Periodic animations queue behind activity animations
    """

    def __init__(self):
        self._big_animation: Optional[Animation] = None
        self._small_animation: Optional[Animation] = None
        self._big_frame_count: int = 0
        self._small_frame_count: int = 0
        self._big_last_update_ms: float = 0
        self._small_last_update_ms: float = 0
        self._big_priority: AnimationPriority = AnimationPriority.PERIODIC
        self._small_priority: AnimationPriority = AnimationPriority.PERIODIC
        # Double-buffering: front buffer for rendering, back buffer for updates
        self._colors_front: Dict[Tuple[int, int], int] = {}
        self._colors_back: Dict[Tuple[int, int], int] = {}
        self._logo_colors_front: Dict[Tuple[int, int], int] = {}
        self._logo_colors_back: Dict[Tuple[int, int], int] = {}
        # Priority queues for big/small animations
        self._big_queue: Deque[Tuple[Animation, AnimationPriority]] = deque(maxlen=5)
        self._small_queue: Deque[Tuple[Animation, AnimationPriority]] = deque(maxlen=5)
        self._is_enabled: bool = True

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool) -> None:
        self._is_enabled = value
        if not value:
            self.stop()

    def play(self, animation: Animation, priority: AnimationPriority = AnimationPriority.PERIODIC) -> None:
        """Start a new animation with priority-based queuing.

        Args:
            animation: The animation to play
            priority: Priority level (ACTIVITY interrupts PERIODIC)

        Rules:
            - Higher priority animations interrupt lower priority ones
            - Same priority animations replace current animation
            - Interrupted animations are NOT queued (dropped)
        """
        if not self._is_enabled:
            return

        if animation.is_big:
            # Higher priority interrupts current animation
            if self._big_animation is None or priority >= self._big_priority:
                self._big_animation = animation
                self._big_frame_count = 0
                self._big_last_update_ms = time.time() * 1000
                self._big_priority = priority
            # Lower priority gets queued (if queue has space)
            else:
                self._big_queue.append((animation, priority))
        else:
            # Higher priority interrupts current animation
            if self._small_animation is None or priority >= self._small_priority:
                self._small_animation = animation
                self._small_frame_count = 0
                self._small_last_update_ms = time.time() * 1000
                self._small_priority = priority
            # Lower priority gets queued (if queue has space)
            else:
                self._small_queue.append((animation, priority))

    def stop(self) -> None:
        """Stop all animations, clear queues, and clear colors."""
        self._big_animation = None
        self._small_animation = None
        self._big_frame_count = 0
        self._small_frame_count = 0
        self._big_queue.clear()
        self._small_queue.clear()
        self._colors_front.clear()
        self._colors_back.clear()
        self._logo_colors_front.clear()
        self._logo_colors_back.clear()

    def update(self) -> None:
        """Update animation state. Call this once per render cycle (~100ms).

        Respects per-animation speed_ms timing:
        - Only advances frame when enough time has elapsed
        - Uses double-buffering: updates written to back buffer, then swapped to front
        - Handles queue progression when animations complete
        """
        current_time_ms = time.time() * 1000

        # Update big animation in back buffer (respecting speed_ms timing)
        if self._big_animation:
            elapsed_ms = current_time_ms - self._big_last_update_ms
            if elapsed_ms >= self._big_animation.speed_ms:
                # Time to advance frame
                new_colors = self._big_animation.update(self._big_frame_count)
                self._colors_back.update(new_colors)
                self._big_frame_count += 1
                self._big_last_update_ms = current_time_ms

                if self._big_animation.is_complete(self._big_frame_count):
                    # Animation complete - check queue for next animation
                    if self._big_queue:
                        next_animation, next_priority = self._big_queue.popleft()
                        self._big_animation = next_animation
                        self._big_frame_count = 0
                        self._big_last_update_ms = current_time_ms
                        self._big_priority = next_priority
                    else:
                        self._big_animation = None
                        self._colors_back.clear()  # Clear colors to revert to default rendering
        else:
            self._colors_back.clear()

        # Update small animation in back buffer (respecting speed_ms timing)
        if self._small_animation:
            elapsed_ms = current_time_ms - self._small_last_update_ms
            if elapsed_ms >= self._small_animation.speed_ms:
                # Time to advance frame
                new_colors = self._small_animation.update(self._small_frame_count)
                self._logo_colors_back.update(new_colors)
                self._small_frame_count += 1
                self._small_last_update_ms = current_time_ms

                if self._small_animation.is_complete(self._small_frame_count):
                    # Animation complete - check queue for next animation
                    if self._small_queue:
                        next_animation, next_priority = self._small_queue.popleft()
                        self._small_animation = next_animation
                        self._small_frame_count = 0
                        self._small_last_update_ms = current_time_ms
                        self._small_priority = next_priority
                    else:
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
