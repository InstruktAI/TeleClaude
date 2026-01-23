"""Triggers for TUI animations."""

import asyncio
import random
from typing import Optional

from teleclaude.cli.tui.animation_colors import palette_registry
from teleclaude.cli.tui.animation_engine import AnimationEngine
from teleclaude.cli.tui.animations.agent import AGENT_ANIMATIONS
from teleclaude.cli.tui.animations.general import GENERAL_ANIMATIONS


class PeriodicTrigger:
    """Trigger for periodic random animations."""

    def __init__(self, engine: AnimationEngine, interval_sec: int = 60):
        self.engine = engine
        self.interval_sec = interval_sec
        self.task: Optional[asyncio.Task[None]] = None

    async def start(self):
        """Run the periodic trigger loop."""
        while True:
            await asyncio.sleep(self.interval_sec)
            if not self.engine.is_enabled:
                continue

            palette = palette_registry.get("spectrum")
            duration = random.uniform(3, 8)

            # Play for big banner
            anim_class_big = random.choice(GENERAL_ANIMATIONS)
            self.engine.play(anim_class_big(palette=palette, is_big=True, duration_seconds=duration))

            # Play for small logo (filter to only small-compatible animations)
            small_compatible = [cls for cls in GENERAL_ANIMATIONS if cls.supports_small]
            if small_compatible:
                anim_class_small = random.choice(small_compatible)
                self.engine.play(anim_class_small(palette=palette, is_big=False, duration_seconds=duration))

    def stop(self):
        if self.task:
            self.task.cancel()
            self.task = None


class ActivityTrigger:
    """Trigger for agent-activity-based animations."""

    def __init__(self, engine: AnimationEngine):
        self.engine = engine

    def on_agent_activity(self, agent_name: str, is_big: bool = True):
        """Called when agent activity is detected."""
        if not self.engine.is_enabled:
            return

        # Filter to small-compatible animations if needed
        animations = AGENT_ANIMATIONS
        if not is_big:
            animations = [cls for cls in AGENT_ANIMATIONS if cls.supports_small]
            if not animations:
                return  # No compatible animations for small logo

        anim_class = random.choice(animations)
        palette = palette_registry.get(f"agent_{agent_name}")
        if not palette:
            palette = palette_registry.get("agent_claude")

        animation = anim_class(palette=palette, is_big=is_big, duration_seconds=random.uniform(2, 5))
        self.engine.play(animation)
