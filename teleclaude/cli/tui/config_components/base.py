"""Base class for TUI config components."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from teleclaude.cli.tui.types import CursesWindow


class ConfigComponentCallback(Protocol):
    """Callback interface for config components to notify the parent view."""

    def on_animation_context_change(self, target: str, section_id: str, state: str, progress: float) -> None:
        """Notify that animation context has changed."""
        ...

    def request_redraw(self) -> None:
        """Request a redraw of the component."""
        ...


class ConfigComponent(ABC):
    """Base class for a configuration section component."""

    def __init__(self, callback: ConfigComponentCallback) -> None:
        self.callback = callback

    @abstractmethod
    def render(self, stdscr: CursesWindow, start_row: int, height: int, width: int) -> None:
        """Render the component.

        Args:
            stdscr: Curses screen object
            start_row: Row to start rendering at
            height: Maximum height available
            width: Maximum width available
        """

    @abstractmethod
    def handle_key(self, key: int) -> bool:
        """Handle key input.

        Args:
            key: Key code

        Returns:
            True if key was handled, False otherwise
        """

    @abstractmethod
    def get_section_id(self) -> str:
        """Return unique ID for this config section (e.g. 'adapters.telegram')."""

    @abstractmethod
    def get_animation_state(self) -> str:
        """Return current animation state: 'idle', 'interacting', 'success', 'error'."""

    def get_progress(self) -> float:
        """Return completion/validation progress (0.0 - 1.0)."""
        return 0.0

    def on_focus(self) -> None:
        """Called when component gains focus."""
        pass

    def on_blur(self) -> None:
        """Called when component loses focus."""
        pass

    def notify_animation_change(self) -> None:
        """Helper to emit current animation state.

        Uses section-specific target so config animations render within
        their own pane area, not the main banner.
        """
        self.callback.on_animation_context_change(
            target=self.get_section_id(),
            section_id=self.get_section_id(),
            state=self.get_animation_state(),
            progress=self.get_progress(),
        )
