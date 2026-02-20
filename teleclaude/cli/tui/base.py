"""Base mixin for TeleClaude TUI widgets."""


class TelecMixin:
    """Mixin for widgets that render controlled content.

    Suppresses Textual's default link processing and interaction artifacts.
    Widgets that handle user-authored rich text (markdown editor, etc.)
    should not use this mixin.
    """

    auto_links = False
