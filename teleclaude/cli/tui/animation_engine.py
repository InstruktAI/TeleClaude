"""Core animation engine for TUI banner and logo."""

import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Deque, Dict, Optional, Tuple

from teleclaude.cli.tui.animations.base import Animation


class AnimationPriority(IntEnum):
    """Animation priority levels (higher value = higher priority)."""

    PERIODIC = 1
    ACTIVITY = 2


@dataclass
class AnimationSlot:
    """State for a single animation target."""

    animation: Optional[Animation] = None
    frame_count: int = 0
    last_update_ms: float = 0
    priority: AnimationPriority = AnimationPriority.PERIODIC
    queue: Deque[Tuple[Animation, AnimationPriority]] = field(default_factory=lambda: deque(maxlen=5))
    looping: bool = False


class AnimationEngine:
    """Manages animation state and timing for multiple render targets.

    Supports priority-based animation queuing per target:
    - Activity animations (higher priority) interrupt periodic animations
    - Periodic animations queue behind activity animations
    """

    def __init__(self):
        # State per target
        self._targets: Dict[str, AnimationSlot] = {}

        # Double-buffering per target: target -> { (x,y) -> color_pair }
        self._buffers_front: Dict[str, Dict[Tuple[int, int], int]] = {}
        self._buffers_back: Dict[str, Dict[Tuple[int, int], int]] = {}

        self._is_enabled: bool = True

        # Initialize default targets
        self._ensure_target("banner")
        self._ensure_target("logo")

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool) -> None:
        self._is_enabled = value
        if not value:
            self.stop()

    def _ensure_target(self, target: str) -> AnimationSlot:
        """Ensure a target slot exists."""
        if target not in self._targets:
            self._targets[target] = AnimationSlot()
            self._buffers_front[target] = {}
            self._buffers_back[target] = {}
        return self._targets[target]

    def play(
        self,
        animation: Animation,
        priority: AnimationPriority = AnimationPriority.PERIODIC,
        target: Optional[str] = None,
    ) -> None:
        """Start a new animation with priority-based queuing.

        Args:
            animation: The animation to play
            priority: Priority level (ACTIVITY interrupts PERIODIC)
            target: Target name (defaults to animation.target)

        Rules:
            - Higher priority animations interrupt lower priority ones
            - Same priority animations replace current animation
            - Interrupted animations are NOT queued (dropped)
        """
        if not self._is_enabled:
            return

        target_name = target or animation.target
        slot = self._ensure_target(target_name)

        # Higher priority interrupts current animation
        if slot.animation is None or priority >= slot.priority:
            slot.animation = animation
            slot.frame_count = 0
            slot.last_update_ms = time.time() * 1000
            slot.priority = priority
            slot.looping = False  # Reset looping state
        # Lower priority gets queued (if queue has space)
        else:
            slot.queue.append((animation, priority))

    def stop(self) -> None:
        """Stop all animations, clear queues, and clear colors."""
        for slot in self._targets.values():
            slot.animation = None
            slot.frame_count = 0
            slot.queue.clear()
            slot.looping = False

        for buf in self._buffers_front.values():
            buf.clear()
        for buf in self._buffers_back.values():
            buf.clear()

    def update(self) -> None:
        """Update animation state. Call this once per render cycle (~100ms).

        Respects per-animation speed_ms timing:
        - Only advances frame when enough time has elapsed
        - Uses double-buffering: updates written to back buffer, then swapped to front
        - Handles queue progression when animations complete
        """
        current_time_ms = time.time() * 1000

        for target_name, slot in self._targets.items():
            back_buffer = self._buffers_back[target_name]

            if slot.animation:
                elapsed_ms = current_time_ms - slot.last_update_ms
                if elapsed_ms >= slot.animation.speed_ms:
                    # Time to advance frame
                    new_colors = slot.animation.update(slot.frame_count)
                    back_buffer.update(new_colors)
                    slot.frame_count += 1
                    slot.last_update_ms = current_time_ms

                    if slot.animation.is_complete(slot.frame_count):
                        if slot.looping:
                            # Loop animation
                            slot.frame_count = 0
                        elif slot.queue:
                            # Animation complete - check queue for next animation
                            next_animation, next_priority = slot.queue.popleft()
                            slot.animation = next_animation
                            slot.frame_count = 0
                            slot.priority = next_priority
                            slot.looping = False  # Reset looping for queued item
                        else:
                            # No more animations
                            slot.animation = None
                            back_buffer.clear()
            else:
                back_buffer.clear()

        # Swap buffers atomically
        self._buffers_front, self._buffers_back = self._buffers_back, self._buffers_front

    def get_color(self, x: int, y: int, is_big: bool = True, target: Optional[str] = None) -> Optional[int]:
        """Get the color pair ID for a specific pixel.

        Reads from front buffer (stable snapshot during rendering).

        Args:
            x, y: Coordinates
            is_big: Legacy flag for banner/logo selection (deprecated)
            target: Explicit target name (overrides is_big)

        Returns:
            Color pair ID or None if no animation color is set for this pixel.
        """
        if not self._is_enabled:
            return None

        # Resolve target
        target_name = target if target is not None else ("banner" if is_big else "logo")

        # Check if target exists (don't create on get_color to avoid noise)
        if target_name not in self._buffers_front:
            return None

        colors = self._buffers_front[target_name]
        color = colors.get((x, y))
        if color == -1:
            return None
        return color

    def clear_colors(self) -> None:
        """Clear all active animation colors (both buffers)."""
        for buf in self._buffers_front.values():
            buf.clear()
        for buf in self._buffers_back.values():
            buf.clear()
