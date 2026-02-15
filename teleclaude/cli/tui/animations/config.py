"""Config section animations."""

import random
from typing import Dict, Tuple

from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.pixel_mapping import target_registry


class PulseAnimation(Animation):
    """Simple pulsing animation for idle state."""

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        target = target_registry.get(self.target)
        if not target:
            return {}

        width = target.width
        progress = frame / self.duration_frames if self.duration_frames else 0

        pixels: Dict[Tuple[int, int], int] = {}

        # Use full width
        bar_width = int(width * 0.8)
        start_x = (width - bar_width) // 2

        # Moving wave
        offset = int(progress * width)

        for x in range(width):
            # Simple moving gradient
            val = (x + offset) % width
            color_idx = int((val / width) * len(self.palette))
            # Only draw if in center region to avoid edge flickering
            if start_x <= x < start_x + bar_width:
                pixels[(x, 0)] = self.palette.get(color_idx)

        return pixels


class TypingAnimation(Animation):
    """Typing animation for interacting state."""

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        target = target_registry.get(self.target)
        if not target:
            return {}

        width = target.width
        pixels: Dict[Tuple[int, int], int] = {}

        # Random flickering chars
        for _ in range(5):
            x = random.randint(0, width - 1)
            color_idx = random.randint(0, len(self.palette) - 1)
            pixels[(x, 0)] = self.palette.get(color_idx)

        return pixels


class SuccessAnimation(Animation):
    """Success burst animation."""

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        target = target_registry.get(self.target)
        if not target:
            return {}

        width = target.width
        progress = frame / self.duration_frames if self.duration_frames else 0

        pixels: Dict[Tuple[int, int], int] = {}
        center_x = width // 2

        # Expanding from center
        radius = int(progress * (width // 2))

        for x in range(width):
            dist = abs(x - center_x)
            if abs(dist - radius) < 2:  # Thin expanding ring
                color_idx = int(progress * len(self.palette)) % len(self.palette)
                pixels[(x, 0)] = self.palette.get(color_idx)

        return pixels


class ErrorAnimation(Animation):
    """Error flash animation."""

    def update(self, frame: int) -> Dict[Tuple[int, int], int]:
        target = target_registry.get(self.target)
        if not target:
            return {}

        width = target.width
        progress = frame / self.duration_frames if self.duration_frames else 0

        pixels: Dict[Tuple[int, int], int] = {}

        # Flash entire line on/off
        if int(progress * 10) % 2 == 0:
            for x in range(width):
                pixels[(x, 0)] = self.palette.get(0)  # Use first color (usually red for error palette)

        return pixels
