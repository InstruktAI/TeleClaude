"""Base classes and mixins for TUI views."""

from __future__ import annotations

from typing import Any


class ScrollableViewMixin:
    """Mixin providing scroll behavior for views with flat_items list.

    Requires these attributes on the class:
    - flat_items: list - Items to scroll through
    - selected_index: int - Currently selected item index
    - scroll_offset: int - First visible item index
    - _last_rendered_range: tuple[int, int] - (first, last) rendered item indices

    The render() method must set _last_rendered_range after rendering.
    """

    flat_items: list[Any]
    selected_index: int
    scroll_offset: int
    _last_rendered_range: tuple[int, int]

    def move_up(self) -> None:
        """Move selection up, adjusting scroll if needed."""
        self.selected_index = max(0, self.selected_index - 1)
        # Scroll up if selection moved above visible area
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index

    def move_down(self) -> None:
        """Move selection down, adjusting scroll if needed."""
        if not self.flat_items:
            return
        self.selected_index = min(len(self.flat_items) - 1, self.selected_index + 1)
        # Ensure selected item is visible - scroll if beyond rendered range
        if hasattr(self, "_last_rendered_range"):
            _, last_rendered = self._last_rendered_range
            if self.selected_index > last_rendered:
                # Scroll down to bring selected item into view
                self.scroll_offset += self.selected_index - last_rendered
