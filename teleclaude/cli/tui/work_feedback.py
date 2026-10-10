"""Present explicitly declared work feedback once in a running TUI."""

from collections.abc import Callable


class WorkFeedbackPresenter:
    """Render owner-declared messages and deduplicate durable operation outcomes."""

    def __init__(self, notify_text: Callable[[str], None]) -> None:
        self._notify_text = notify_text
        self._presented_operation_ids: set[str] = set()

    def present(self, message: str | None, operation_id: str | None = None) -> None:
        """Show a declared message, at most once for each operation identity."""
        if message is None:
            return
        if operation_id is not None and operation_id in self._presented_operation_ids:
            return
        self._notify_text(message)
        if operation_id is not None:
            self._presented_operation_ids.add(operation_id)
