"""Shared footer-binding helpers for TUI views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from textual.css.query import NoMatches, WrongType
from textual.widgets import Footer


class FooterBindingView(Protocol):  # pylint: disable=too-few-public-methods
    """Minimal view protocol for footer binding helpers."""

    app: Any
    is_attached: bool

    def call_after_refresh(self, callback: Callable[[], None]) -> None:
        """Schedule a callback after the next refresh."""


def refresh_footer_bindings(view: FooterBindingView, callback: Callable[[], None]) -> None:
    """Refresh app bindings and schedule footer syncing after render."""
    view.app.refresh_bindings()
    view.call_after_refresh(callback)


def sync_default_footer_action(view: FooterBindingView, default_action: str | None) -> None:
    """Apply the active default-action marker to the footer keys."""
    if not view.is_attached:
        return
    try:
        footer = view.app.query_one(Footer)
    except (NoMatches, WrongType):
        return
    for key_widget in footer.query("FooterKey"):
        key_widget.set_class(
            getattr(key_widget, "action", None) == default_action,
            "default-action",
        )
