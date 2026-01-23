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

            anim_class = random.choice(GENERAL_ANIMATIONS)
            palette = palette_registry.get("spectrum")
            duration = random.uniform(3, 8)

            # Play for both big and small
            self.engine.play(anim_class(palette=palette, is_big=True, duration_seconds=duration))
            self.engine.play(anim_class(palette=palette, is_big=False, duration_seconds=duration))

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

        anim_class = random.choice(AGENT_ANIMATIONS)
        palette = palette_registry.get(f"agent_{agent_name}")
        if not palette:
            palette = palette_registry.get("agent_claude")

        animation = anim_class(palette=palette, is_big=is_big, duration_seconds=random.uniform(2, 5))
        self.engine.play(animation)
