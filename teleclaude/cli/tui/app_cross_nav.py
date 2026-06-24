"""TelecAppCrossNavMixin — cross-view jumps and the shared per-human filter.

These handlers own the app-level half of the todo↔session cross-navigation and
the one shared human filter: a claimed todo's runner jump, a session slug's todo
jump, and the chip-driven filter that both views honor. Extracted into a mixin so
the same code is exercised by a lean two-view test harness, not a copy.
"""

from __future__ import annotations

from collections.abc import Mapping

from teleclaude.cli.tui.messages import ChipFilterToggle, JumpToSession, JumpToTodo
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView


class TelecAppCrossNavMixin:
    """App-level cross-view jump and shared-human-filter handlers."""

    _human_filter: str | None = None

    def on_jump_to_session(self, message: JumpToSession) -> None:
        """Cross-view jump from a claimed todo to its runner session."""
        self.action_switch_tab("sessions")  # type: ignore[attr-defined]
        self.query_one("#sessions-view", SessionsView).select_session(message.session_id)  # type: ignore[attr-defined]

    def on_jump_to_todo(self, message: JumpToTodo) -> None:
        """Cross-view jump from a session's work slug to its todo."""
        self.action_switch_tab("preparation")  # type: ignore[attr-defined]
        self.query_one("#preparation-view", PreparationView).select_todo(message.slug)  # type: ignore[attr-defined]

    def on_chip_filter_toggle(self, message: ChipFilterToggle) -> None:
        """Toggle the shared human filter on the clicked person."""
        current = self._human_filter
        self.set_human_filter(None if current == message.person_email else message.person_email)

    def set_human_filter(self, human_filter: str | None) -> None:
        """Set the one shared human filter and push it to both views."""
        self._human_filter = human_filter
        self.query_one("#sessions-view", SessionsView).set_human_filter(human_filter)  # type: ignore[attr-defined]
        self.query_one("#preparation-view", PreparationView).set_human_filter(human_filter)  # type: ignore[attr-defined]
        self._schedule_state_save()  # type: ignore[attr-defined]

    def collect_human_filter(self) -> str | None:
        """Return the shared filter for the persisted ``app`` namespace."""
        return self._human_filter

    def restore_human_filter(self, persisted_app_state: Mapping[str, object]) -> None:
        """Restore the shared filter from the persisted ``app`` namespace."""
        value = persisted_app_state.get("human_filter")
        self.set_human_filter(value if isinstance(value, str) else None)
