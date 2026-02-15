"""Shared interaction state used by tree-like TUI views."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TreeInteractionAction(str, Enum):
    """Common user interaction outcomes for preview/toggle gestures."""

    NONE = "none"
    PREVIEW = "preview"
    TOGGLE_STICKY = "toggle_sticky"
    CLEAR_STICKY_PREVIEW = "clear_sticky_preview"


@dataclass(frozen=True)
class TreeInteractionDecision:
    """Result of classifying a click/space gesture."""

    action: TreeInteractionAction
    now: float
    clear_preview: bool = False


@dataclass
class TreeInteractionState:
    """Debounce + toggle/preview state for list-gesture interactions."""

    double_press_threshold: float = 0.65
    last_press_time: float | None = None
    last_press_item_id: str | None = None
    double_press_guard_item_id: str | None = None
    double_press_guard_until: float | None = None

    def mark_press(self, item_id: str, now: float) -> None:
        """Track the latest press target and timestamp."""
        self.last_press_time = now
        self.last_press_item_id = item_id

    def mark_double_press_guard(self, item_id: str, now: float) -> None:
        """Suppress a third press immediately after a toggle gesture."""
        self.double_press_guard_item_id = item_id
        self.double_press_guard_until = now + self.double_press_threshold

    def is_double_press_guarded(self, item_id: str, now: float) -> bool:
        """Return True if a recent toggle guard suppresses repeat actions."""
        if self.double_press_guard_item_id != item_id:
            return False
        guard_until = self.double_press_guard_until
        if guard_until is None:
            return False
        if now >= guard_until:
            self.double_press_guard_item_id = None
            self.double_press_guard_until = None
            return False
        return True

    def decide_preview_action(
        self,
        item_id: str,
        now: float,
        *,
        is_sticky: bool,
        allow_sticky_toggle: bool,
    ) -> TreeInteractionDecision:
        """Build the next action for single-click/space-like interactions."""
        if allow_sticky_toggle and self.is_double_press_guarded(item_id, now):
            return TreeInteractionDecision(TreeInteractionAction.NONE, now=now)

        if (
            allow_sticky_toggle
            and self.last_press_item_id == item_id
            and self.last_press_time is not None
            and now - self.last_press_time < self.double_press_threshold
        ):
            self.last_press_item_id = None
            self.last_press_time = None
            return TreeInteractionDecision(
                action=TreeInteractionAction.TOGGLE_STICKY,
                now=now,
                clear_preview=is_sticky,
            )

        self.mark_press(item_id, now)
        if is_sticky:
            return TreeInteractionDecision(TreeInteractionAction.CLEAR_STICKY_PREVIEW, now=now)
        return TreeInteractionDecision(TreeInteractionAction.PREVIEW, now=now)
