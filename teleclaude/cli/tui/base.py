"""Base mixin for TeleClaude TUI widgets."""


class TelecMixin:
    """Mixin for widgets that render controlled content.

    Suppresses Textual's default link processing and interaction artifacts.
    Widgets that handle user-authored rich text (markdown editor, etc.)
    should not use this mixin.
    """

    auto_links = False

    @classmethod
    def allows_auto_links(cls) -> bool:
        """Return whether Textual auto-link handling stays enabled."""
        return cls.auto_links

    def should_suppress_links(self) -> bool:
        """Return whether link interaction artifacts should be suppressed."""
        return not self.auto_links
