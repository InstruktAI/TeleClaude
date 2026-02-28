"""Core animation engine for TUI banner and logo."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Deque, Optional, Tuple

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


# Buffer values are Rich color strings (from palettes) or -1 (clear sentinel).
_BufferDict = dict[tuple[int, int], str | int]


class AnimationEngine:
    """Manages animation state and timing for multiple render targets.

    Supports priority-based animation queuing per target:
    - Activity animations (higher priority) interrupt periodic animations
    - Periodic animations queue behind activity animations

    Color values are Rich-compatible color strings (e.g., "color(196)", "#ff5f5f").
    The sentinel value -1 means "no animation color" (clear pixel).
    """

    def __init__(self) -> None:
        self._targets: dict[str, AnimationSlot] = {}
        self._buffers_front: dict[str, _BufferDict] = {}
        self._buffers_back: dict[str, _BufferDict] = {}
        self._is_enabled: bool = True
        self._has_active_animation: bool = False

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

    @property
    def has_active_animation(self) -> bool:
        """True if any target has a running animation."""
        return self._has_active_animation

    def _ensure_target(self, target: str) -> AnimationSlot:
        if target not in self._targets:
            self._targets[target] = AnimationSlot()
            self._buffers_front[target] = {}
            self._buffers_back[target] = {}
        return self._targets[target]

    def play(
        self,
        animation: Animation,
        priority: AnimationPriority = AnimationPriority.PERIODIC,
        target: str | None = None,
    ) -> None:
        """Start a new animation with priority-based queuing."""
        if not self._is_enabled:
            return

        from teleclaude.cli.tui.theme import is_dark_mode, get_terminal_background
        import random

        target_name = target or animation.target
        slot = self._ensure_target(target_name)

        # Update animation with current theme context before starting
        animation.dark_mode = is_dark_mode()
        animation.background_hex = get_terminal_background()
        animation.seed = random.randint(0, 1000000)
        animation.rng = random.Random(animation.seed)

        if slot.animation is None or priority >= slot.priority:
            slot.animation = animation
            slot.frame_count = 0
            slot.last_update_ms = time.time() * 1000
            slot.priority = priority
            slot.looping = False
            self._has_active_animation = True
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
        self._has_active_animation = False

    def set_looping(self, target: str, looping: bool) -> None:
        if target in self._targets:
            self._targets[target].looping = looping

    def update(self) -> bool:
        """Update animation state. Call this once per render cycle (~100ms).

        Returns True if any animation produced new frame data (banner needs refresh).
        """
        current_time_ms = time.time() * 1000
        changed = False
        any_active = False

        for target_name, slot in self._targets.items():
            back_buffer = self._buffers_back[target_name]

            if slot.animation:
                any_active = True
                elapsed_ms = current_time_ms - slot.last_update_ms
                if elapsed_ms >= slot.animation.speed_ms:
                    new_colors = slot.animation.update(slot.frame_count)
                    back_buffer.update(new_colors)
                    slot.frame_count += 1
                    slot.last_update_ms = current_time_ms
                    changed = True

                    if slot.animation.is_complete(slot.frame_count):
                        if slot.looping:
                            slot.frame_count = 0
                        elif slot.queue:
                            next_animation, next_priority = slot.queue.popleft()
                            slot.animation = next_animation
                            slot.frame_count = 0
                            slot.priority = next_priority
                            slot.looping = False
                        else:
                            slot.animation = None
                            back_buffer.clear()
            else:
                back_buffer.clear()

        # Swap buffers atomically
        self._buffers_front, self._buffers_back = self._buffers_back, self._buffers_front
        self._has_active_animation = any_active
        return changed

    def get_color(self, x: int, y: int, target: str = "banner") -> str | None:
        """Get the Rich color string for a specific pixel.

        Reads from front buffer (stable snapshot during rendering).

        Returns:
            Rich color string or None if no animation color is set.
        """
        if not self._is_enabled:
            return None

        colors = self._buffers_front.get(target)
        if colors is None:
            return None

        color = colors.get((x, y))
        # Only return actual color strings; -1 sentinel and missing = no color
        if isinstance(color, str):
            return color
        return None

    def clear_colors(self) -> None:
        """Clear all active animation colors (both buffers)."""
        for buf in self._buffers_front.values():
            buf.clear()
        for buf in self._buffers_back.values():
            buf.clear()
