"""Triggers for TUI animations."""

import asyncio
import random
from typing import Dict, List, Optional, Tuple, Type

from teleclaude.cli.tui.animation_colors import palette_registry
from teleclaude.cli.tui.animation_engine import AnimationEngine, AnimationPriority
from teleclaude.cli.tui.animations.agent import AGENT_ANIMATIONS
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.animations.general import GENERAL_ANIMATIONS


def filter_animations(animations: List[Type[Animation]], subset: List[str]) -> List[Type[Animation]]:
    """Filter animation classes by name subset.

    Args:
        animations: List of animation classes
        subset: List of animation class names to include. Empty list means all.

    Returns:
        Filtered list of animation classes
    """
    if not subset:
        return animations
    return [cls for cls in animations if cls.__name__ in subset]


class PeriodicTrigger:
    """Trigger for periodic random animations."""

    def __init__(self, engine: AnimationEngine, interval_sec: int = 60, animations_subset: Optional[List[str]] = None):
        self.engine = engine
        self.interval_sec = interval_sec
        self.animations_subset = animations_subset or []
        self.task: Optional[asyncio.Task[None]] = None

    async def start(self):
        """Run the periodic trigger loop."""
        while True:
            await asyncio.sleep(self.interval_sec)
            if not self.engine.is_enabled:
                continue

            palette = palette_registry.get("spectrum")
            duration = random.uniform(3, 8)

            # Filter animations by subset configuration
            filtered_animations = filter_animations(GENERAL_ANIMATIONS, self.animations_subset)
            if not filtered_animations:
                continue  # No animations available after filtering

            # Play for big banner (periodic priority)
            anim_class_big = random.choice(filtered_animations)
            self.engine.play(
                anim_class_big(palette=palette, is_big=True, duration_seconds=duration),
                priority=AnimationPriority.PERIODIC,
            )

            # Play for small logo (filter to only small-compatible animations)
            small_compatible = [cls for cls in filtered_animations if cls.supports_small]
            if small_compatible:
                anim_class_small = random.choice(small_compatible)
                self.engine.play(
                    anim_class_small(palette=palette, is_big=False, duration_seconds=duration),
                    priority=AnimationPriority.PERIODIC,
                )

    def stop(self):
        if self.task:
            self.task.cancel()
            self.task = None


class ActivityTrigger:
    """Trigger for agent-activity-based animations."""

    def __init__(self, engine: AnimationEngine, animations_subset: Optional[List[str]] = None):
        self.engine = engine
        self.animations_subset = animations_subset or []

    def on_agent_activity(self, agent_name: str, is_big: bool = True):
        """Called when agent activity is detected."""
        if not self.engine.is_enabled:
            return

        # Filter animations by subset configuration
        animations = filter_animations(AGENT_ANIMATIONS, self.animations_subset)
        if not animations:
            return  # No animations available after filtering

        # Filter to small-compatible animations if needed
        if not is_big:
            animations = [cls for cls in animations if cls.supports_small]
            if not animations:
                return  # No compatible animations for small logo

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
        # Registry: (section_id, state) -> AnimationClass
        self._registry: Dict[Tuple[str, str], Type[Animation]] = {}
        # Current: (target, section_id, state)
        self._current_context: Optional[Tuple[str, str, str]] = None

    def register(self, section_id: str, state: str, animation_cls: Type[Animation]) -> None:
        """Register an animation class for a specific section and state."""
        self._registry[(section_id, state)] = animation_cls

    def set_context(self, target: str, section_id: str, state: str, progress: float = 0.0) -> None:
        """Update the current context and trigger animation if changed.

        Args:
            target: Render target name
            section_id: Config section ID
            state: "idle", "interacting", "success", "error"
            progress: 0.0-1.0 (unused by trigger, but available for animations if needed)
        """
        if not self.engine.is_enabled:
            return

        # Check if context changed
        new_context = (target, section_id, state)
        if self._current_context == new_context:
            return

        self._current_context = new_context

        # Look up animation
        anim_cls = self._registry.get((section_id, state))
        if not anim_cls:
            # Fallback or silent?
            # For now silent, assuming registration covers needs or UI handles fallback visuals
            return

        # Get palette (assuming section-aware palette exists, or fallback)
        palette = palette_registry.get(section_id)
        if not palette:
            palette = palette_registry.get("spectrum")  # Fallback

        # Determine duration and looping
        is_idle = state == "idle"
        duration = 2.0 if is_idle else 1.0  # Idle duration irrelevant as it loops

        # Instantiate
        # Note: We pass is_big=True as dummy, target is what matters
        animation = anim_cls(palette=palette, is_big=True, duration_seconds=duration, target=target)

        # Play with appropriate priority and looping
        # State driven implies user focus, so ACTIVITY priority is reasonable,
        # but idle might be lower?
        # Actually, if it's the active section, it should probably override periodic.
        # But maybe not agent activity?
        # Let's use ACTIVITY for now as it's user-driven config.

        self.engine.play(animation, priority=AnimationPriority.ACTIVITY, target=target)

        # Access the slot directly to set looping if idle
        # This relies on engine implementation details, but they are in same package.
        if is_idle:
            slot = self.engine._targets.get(target)
            if slot:
                slot.looping = True
