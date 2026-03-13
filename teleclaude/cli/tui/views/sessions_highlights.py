"""Highlight management, update_session, and state-export mixin for SessionsView."""

from __future__ import annotations

import time

from teleclaude.cli.models import SessionInfo
from teleclaude.cli.tui.widgets.session_row import SessionRow

# Auto-clear highlights on preview session after this many seconds
PREVIEW_HIGHLIGHT_DURATION = 3.0
HIDDEN_SESSION_STATUSES = frozenset({"closing", "closed"})


class SessionsViewHighlightsMixin:
    """Highlight management, reactive watchers, and state-export for SessionsView."""

    def watch_preview_session_id(self, old_session_id: str | None, new_session_id: str | None) -> None:
        """When preview changes, update row visual highlights.

        Cancels any pending auto-clear timer for the old preview session
        (its highlights should persist as a non-preview session).

        Does NOT post PreviewChanged — that's done explicitly by action
        handlers with the correct request_focus flag.
        """
        if old_session_id:
            self._cancel_highlight_timer(old_session_id)  # type: ignore[attr-defined]
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow):
                widget.is_preview = widget.session_id == new_session_id

    def set_input_highlight(self, session_id: str) -> None:
        """Mark session as having new input.

        Preview sessions: show highlight briefly then auto-clear.
        Other sessions: highlight persists until user interaction.
        """
        self._input_highlights.add(session_id)  # type: ignore[attr-defined]
        self._output_highlights.discard(session_id)  # type: ignore[attr-defined]
        self._update_row_highlight(session_id, "input")
        if session_id == self.preview_session_id:  # type: ignore[attr-defined]
            self._schedule_highlight_clear(session_id)  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def set_output_highlight(self, session_id: str, summary: str = "") -> None:
        """Mark session as having new output.

        Preview sessions: show highlight briefly then auto-clear.
        Other sessions: highlight persists until user interaction.
        """
        self._output_highlights.add(session_id)  # type: ignore[attr-defined]
        self._input_highlights.discard(session_id)  # type: ignore[attr-defined]
        if summary:
            self._last_output_summary[session_id] = {  # type: ignore[attr-defined]
                "text": summary,
                "ts": time.monotonic(),
            }
            for widget in self._nav_items:  # type: ignore[attr-defined]
                if isinstance(widget, SessionRow) and widget.session_id == session_id:
                    widget.last_output_summary = summary
                    break
        self._update_row_highlight(session_id, "output")
        if session_id == self.preview_session_id:  # type: ignore[attr-defined]
            self._schedule_highlight_clear(session_id)  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def clear_highlight(self, session_id: str) -> None:
        """Clear highlight for a session."""
        self._input_highlights.discard(session_id)  # type: ignore[attr-defined]
        self._output_highlights.discard(session_id)  # type: ignore[attr-defined]
        self._update_row_highlight(session_id, "")
        self._notify_state_changed()  # type: ignore[attr-defined]

    def _update_row_highlight(self, session_id: str, highlight_type: str) -> None:
        """Update highlight type on a session row."""
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.highlight_type = highlight_type
                break

    def optimistically_hide_session(self, session_id: str) -> None:
        """Hide a session immediately after close intent succeeds locally."""
        self._optimistically_hidden_session_ids.add(session_id)  # type: ignore[attr-defined]
        if all(session.session_id != session_id for session in self._sessions):  # type: ignore[attr-defined]
            return
        remaining = [session for session in self._sessions if session.session_id != session_id]  # type: ignore[attr-defined]
        self.update_data(  # type: ignore[attr-defined]
            computers=self._computers,  # type: ignore[attr-defined]
            projects=self._projects,  # type: ignore[attr-defined]
            sessions=remaining,
            availability=self._availability,  # type: ignore[attr-defined]
        )

    def confirm_session_closed(self, session_id: str) -> None:
        """Finalize optimistic hide once closure is confirmed."""
        self._optimistically_hidden_session_ids.discard(session_id)  # type: ignore[attr-defined]
        if all(session.session_id != session_id for session in self._sessions):  # type: ignore[attr-defined]
            return
        remaining = [session for session in self._sessions if session.session_id != session_id]  # type: ignore[attr-defined]
        self.update_data(  # type: ignore[attr-defined]
            computers=self._computers,  # type: ignore[attr-defined]
            projects=self._projects,  # type: ignore[attr-defined]
            sessions=remaining,
            availability=self._availability,  # type: ignore[attr-defined]
        )

    def update_session(self, session: SessionInfo) -> None:
        """Update a single session row with new data."""
        if session.status in HIDDEN_SESSION_STATUSES:
            remaining = [item for item in self._sessions if item.session_id != session.session_id]  # type: ignore[attr-defined]
            if len(remaining) != len(self._sessions):  # type: ignore[attr-defined]
                self.update_data(  # type: ignore[attr-defined]
                    computers=self._computers,  # type: ignore[attr-defined]
                    projects=self._projects,  # type: ignore[attr-defined]
                    sessions=remaining,
                    availability=self._availability,  # type: ignore[attr-defined]
                )
            return

        updated = False
        next_sessions: list[SessionInfo] = []
        for existing in self._sessions:  # type: ignore[attr-defined]
            if existing.session_id == session.session_id:
                next_sessions.append(session)
                updated = True
            else:
                next_sessions.append(existing)

        if session.session_id in self._optimistically_hidden_session_ids:  # type: ignore[attr-defined]
            self._optimistically_hidden_session_ids.discard(session.session_id)  # type: ignore[attr-defined]
            if not updated:
                next_sessions.append(session)
            self.update_data(  # type: ignore[attr-defined]
                computers=self._computers,  # type: ignore[attr-defined]
                projects=self._projects,  # type: ignore[attr-defined]
                sessions=next_sessions,
                availability=self._availability,  # type: ignore[attr-defined]
            )
            return

        if not updated:
            next_sessions.append(session)
            self.update_data(  # type: ignore[attr-defined]
                computers=self._computers,  # type: ignore[attr-defined]
                projects=self._projects,  # type: ignore[attr-defined]
                sessions=next_sessions,
                availability=self._availability,  # type: ignore[attr-defined]
            )
            return

        self._sessions = next_sessions  # type: ignore[attr-defined]
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow) and widget.session_id == session.session_id:
                widget.update_session(session)
                break

    def update_activity(self, session_id: str, hook_type: str, text: str = "") -> None:
        """Update activity state on a session row.

        Replaces the old set_active_tool/clear_active_tool pair.
        Passes the hook event type through to the widget for direct matching.
        """
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.activity_event = hook_type
                widget.activity_text = text
                break
        if session_id == self.preview_session_id:  # type: ignore[attr-defined]
            self._schedule_highlight_clear(session_id)  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def get_persisted_state(self) -> dict[str, object]:  # guard: loose-dict
        """Export state for persistence."""
        return {
            "sticky_sessions": [{"session_id": sid} for sid in self._sticky_session_ids],  # type: ignore[attr-defined]
            "input_highlights": sorted(self._input_highlights),  # type: ignore[attr-defined]
            "output_highlights": sorted(self._output_highlights),  # type: ignore[attr-defined]
            "last_output_summary": {
                k: {"text": str(v.get("text", "")), "ts": float(v.get("ts", 0))}
                for k, v in sorted(self._last_output_summary.items())  # type: ignore[attr-defined]
                if v.get("text")
            },
            "collapsed_sessions": sorted(self._collapsed_sessions),  # type: ignore[attr-defined]
            "preview": {"session_id": self.preview_session_id} if self.preview_session_id else None,  # type: ignore[attr-defined]
            "highlighted_session_id": self._highlighted_session_id,  # type: ignore[attr-defined]
        }
