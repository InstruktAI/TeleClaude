"""Core animation engine for TUI banner and logo."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Deque, Optional, Tuple

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.animations.base import Animation, RenderBuffer, Z_BILLBOARD, Z_SKY

logger = get_logger(__name__)


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


# A buffer maps Z-level -> (pixel -> color)
_ZBufferDict = dict[int, dict[tuple[int, int], str | int]]


class AnimationEngine:
    """Manages animation state and timing for multiple render targets.

    Supports priority-based animation queuing per target.
    Handles layered Z-Buffer compositing for physical occlusion.
    """

    def __init__(self) -> None:
        self._targets: dict[str, AnimationSlot] = {}
        self._buffers_front: dict[str, _ZBufferDict] = {}
        self._buffers_back: dict[str, _ZBufferDict] = {}
        self._is_enabled: bool = True
        self._animation_mode: str = "periodic"
        self._has_active_animation: bool = False
        # Optional callback when a new animation starts
        self.on_animation_start: Optional[Callable[[str, Animation], None]] = None

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
    def animation_mode(self) -> str:
        return self._animation_mode

    @animation_mode.setter
    def animation_mode(self, value: str) -> None:
        self._animation_mode = value

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
        animation.animation_mode = self._animation_mode
        animation.seed = random.randint(0, 1000000)
        animation.rng = random.Random(animation.seed)

        if slot.animation is None or priority >= slot.priority:
            slot.animation = animation
            slot.frame_count = 0
            slot.last_update_ms = time.time() * 1000
            slot.priority = priority
            slot.looping = False
            self._has_active_animation = True
            
            if self.on_animation_start:
                self.on_animation_start(target_name, animation)
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
                    try:
                        result = slot.animation.update(slot.frame_count)
                    except Exception:
                        logger.exception(
                            "Animation update crashed",
                            animation=type(slot.animation).__name__,
                            target=target_name,
                            frame=slot.frame_count,
                        )
                        slot.animation = None
                        back_buffer.clear()
                        continue

                    back_buffer.clear()
                    if isinstance(result, RenderBuffer):
                        # Multi-layer update
                        for z, pixels in result.layers.items():
                            if z not in back_buffer: back_buffer[z] = {}
                            back_buffer[z].update(pixels)
                    else:
                        # Legacy single-layer update (default to billboard level)
                        if Z_BILLBOARD not in back_buffer: back_buffer[Z_BILLBOARD] = {}
                        back_buffer[Z_BILLBOARD].update(result)
                        
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
                            if self.on_animation_start:
                                self.on_animation_start(target_name, next_animation)
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
        """Get the composited Rich color string for a specific pixel.
        Traverses Z-layers from front to back (10 -> 0).
        """
        if not self._is_enabled:
            return None

        z_buffer = self._buffers_front.get(target)
        if not z_buffer:
            return None

        # Compositor: Traverse layers from front-most (10) to back-most (0)
        for z in sorted(z_buffer.keys(), reverse=True):
            layer = z_buffer[z]
            color = layer.get((x, y))
            # Only return strings that look like colors (Hex or color(N))
            # Skip single-character entity markers (Stars/Clouds)
            if isinstance(color, str) and len(color) > 1:
                return color
            # If -1 or missing, continue to lower layer
            
        return None

    def get_layer_color(self, z: int, x: int, y: int, target: str = "banner") -> str | int | None:
        """Get the raw color value for a specific Z-layer."""
        z_buffer = self._buffers_front.get(target)
        if z_buffer and z in z_buffer:
            return z_buffer[z].get((x, y))
        return None

    def clear_colors(self) -> None:
        """Clear all active animation colors (both buffers)."""
        for buf in self._buffers_front.values():
            buf.clear()
        for buf in self._buffers_back.values():
            buf.clear()

    def is_external_light(self, target: str = "banner") -> bool:
        """True if the current animation for the target is an external light source."""
        slot = self._targets.get(target)
        if slot and slot.animation:
            return slot.animation.is_external_light
        return False
