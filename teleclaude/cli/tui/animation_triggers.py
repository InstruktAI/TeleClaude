"""Triggers for TUI animations."""

from __future__ import annotations

import asyncio
import random

from teleclaude.cli.tui.animation_colors import palette_registry
from teleclaude.cli.tui.animation_engine import AnimationEngine, AnimationPriority
from teleclaude.cli.tui.animations.agent import AGENT_ANIMATIONS
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.animations.general import GENERAL_ANIMATIONS


def filter_animations(animations: list[type[Animation]], subset: list[str], dark_mode: bool = True) -> list[type[Animation]]:
    """Filter animation classes by name subset and current theme mode.

    Args:
        animations: List of animation classes
        subset: List of animation class names to include. Empty list means all.
        dark_mode: Current theme mode.

    Returns:
        Filtered list of animation classes
    """
    mode_str = "dark" if dark_mode else "light"
    return [
        cls for cls in animations 
        if (not subset or cls.__name__ in subset) and 
           (cls.theme_filter is None or cls.theme_filter == mode_str)
    ]


class PeriodicTrigger:
    """Trigger for periodic random animations."""

    def __init__(self, engine: AnimationEngine, interval_sec: int = 60, animations_subset: list[str] | None = None):
        self.engine = engine
        self.interval_sec = interval_sec
        self.animations_subset = animations_subset or []
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Run the periodic trigger loop."""
        while True:
            await asyncio.sleep(self.interval_sec)
            if not self.engine.is_enabled:
                continue

            from teleclaude.cli.tui.theme import is_dark_mode
            dark = is_dark_mode()
            palette = palette_registry.get("spectrum")
            duration = random.uniform(12, 20)

            filtered_animations = filter_animations(GENERAL_ANIMATIONS, self.animations_subset, dark)
            if not filtered_animations:
                continue

            anim_class_big = random.choice(filtered_animations)
            self.engine.play(
                anim_class_big(palette=palette, is_big=True, duration_seconds=duration),
                priority=AnimationPriority.PERIODIC,
            )

            small_compatible = [cls for cls in filtered_animations if cls.supports_small]
            if small_compatible:
                anim_class_small = random.choice(small_compatible)
                self.engine.play(
                    anim_class_small(palette=palette, is_big=False, duration_seconds=duration),
                    priority=AnimationPriority.PERIODIC,
                )

    def stop(self) -> None:
        if self.task:
            self.task.cancel()
            self.task = None


class ActivityTrigger:
    """Trigger for agent-activity-based animations."""

    def __init__(self, engine: AnimationEngine, animations_subset: list[str] | None = None):
        self.engine = engine
        self.animations_subset = animations_subset or []

    def on_agent_activity(self, agent_name: str, is_big: bool = True) -> None:
        """Called when agent activity is detected."""
        if not self.engine.is_enabled:
            return

        from teleclaude.cli.tui.theme import is_dark_mode
        animations = filter_animations(AGENT_ANIMATIONS, self.animations_subset, is_dark_mode())
        if not animations:
            return

        if not is_big:
            animations = [cls for cls in animations if cls.supports_small]
            if not animations:
                return

        anim_class = random.choice(animations)
        palette = palette_registry.get(f"agent_{agent_name}")
        if not palette:
            palette = palette_registry.get("agent_claude")

        animation = anim_class(palette=palette, is_big=is_big, duration_seconds=random.uniform(2, 5))
        self.engine.play(animation, priority=AnimationPriority.ACTIVITY)


class StateDrivenTrigger:
    """Trigger for state-driven animations (e.g., Config tab)."""

    def __init__(self, engine: AnimationEngine):
        self.engine = engine
        self._registry: dict[tuple[str, str], type[Animation]] = {}
        self._current_context: tuple[str, str, str] | None = None

    def register(self, section_id: str, state: str, animation_cls: type[Animation]) -> None:
        self._registry[(section_id, state)] = animation_cls

    def set_context(self, target: str, section_id: str, state: str, progress: float = 0.0) -> None:
        """Update the current context and trigger animation if changed."""
        if not self.engine.is_enabled:
            return

        new_context = (target, section_id, state)
        if self._current_context == new_context:
            return

        self._current_context = new_context

        anim_cls = self._registry.get((section_id, state))
        if not anim_cls:
            return

        palette_key = section_id.split(".")[-1] if "." in section_id else section_id
        palette = palette_registry.get(palette_key) or palette_registry.get("spectrum")

        is_idle = state == "idle"
        duration = 2.0 if is_idle else 1.0

        animation = anim_cls(palette=palette, is_big=True, duration_seconds=duration, target=target)
        self.engine.play(animation, priority=AnimationPriority.ACTIVITY, target=target)

        if is_idle:
            self.engine.set_looping(target, True)
