"""Highlight management, update_session, and state-export mixin for SessionsView."""

from __future__ import annotations

import time

from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui.messages import PreviewChanged, StickyChanged
from teleclaude.cli.tui.widgets.session_row import SessionRow
from teleclaude.core.session_status import SessionLifecycleStatus

# Auto-clear highlights on preview session after this many seconds
PREVIEW_HIGHLIGHT_DURATION = 3.0
HIDDEN_SESSION_STATUSES = frozenset({SessionLifecycleStatus.CLOSING, SessionLifecycleStatus.CLOSED})


class SessionsViewHighlightsMixin:
    """Highlight management, reactive watchers, and state-export for SessionsView."""

    preview_session_id: str | None

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
        self._update_row_highlights(session_id)
        if session_id == self.preview_session_id:  # type: ignore[attr-defined]
            self._schedule_highlight_clear(session_id)  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def set_output_highlight(self, session_id: str, summary: str = "") -> None:
        """Mark session as having new output.

        Preview sessions: show highlight briefly then auto-clear.
        Other sessions: highlight persists until user interaction.
        """
        self._output_highlights.add(session_id)  # type: ignore[attr-defined]
        if summary:
            self._last_output_summary[session_id] = {  # type: ignore[attr-defined]
                "text": summary,
                "ts": time.monotonic(),
            }
            for widget in self._nav_items:  # type: ignore[attr-defined]
                if isinstance(widget, SessionRow) and widget.session_id == session_id:
                    widget.last_output_summary = summary
                    break
        self._update_row_highlights(session_id)
        if session_id == self.preview_session_id:  # type: ignore[attr-defined]
            self._schedule_highlight_clear(session_id)  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def clear_highlight(self, session_id: str) -> None:
        """Clear highlight for a session."""
        self._input_highlights.discard(session_id)  # type: ignore[attr-defined]
        self._output_highlights.discard(session_id)  # type: ignore[attr-defined]
        self._update_row_highlights(session_id)
        self._notify_state_changed()  # type: ignore[attr-defined]

    def _update_row_highlights(self, session_id: str) -> None:
        """Update directional highlight state on a session row."""
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.input_highlight = session_id in self._input_highlights  # type: ignore[attr-defined]
                widget.output_highlight = session_id in self._output_highlights  # type: ignore[attr-defined]
                break

    def optimistically_hide_session(self, session_id: str) -> None:
        """Hide a session immediately after close intent succeeds locally."""
        self._optimistically_hidden_session_ids.add(session_id)  # type: ignore[attr-defined]
        if all(session.session_id != session_id for session in self._sessions):  # type: ignore[attr-defined]
            return
        remaining = [  # type: ignore[attr-defined]
            session for session in self._sessions if session.session_id != session_id
        ]
        self.update_data(  # type: ignore[attr-defined]
            computers=self._computers,  # type: ignore[attr-defined]
            projects=self._projects,  # type: ignore[attr-defined]
            sessions=remaining,
        )

    def confirm_session_closed(self, session_id: str) -> None:
        """Finalize optimistic hide once closure is confirmed."""
        self.drop_session_state(session_id)  # type: ignore[attr-defined]
        self._release_layout_claims(session_id)
        self._optimistically_hidden_session_ids.discard(session_id)  # type: ignore[attr-defined]
        if all(session.session_id != session_id for session in self._sessions):  # type: ignore[attr-defined]
            return
        remaining = [  # type: ignore[attr-defined]
            session for session in self._sessions if session.session_id != session_id
        ]
        self.update_data(  # type: ignore[attr-defined]
            computers=self._computers,  # type: ignore[attr-defined]
            projects=self._projects,  # type: ignore[attr-defined]
            sessions=remaining,
        )

    def _release_layout_claims(self, session_id: str) -> None:
        """Withdraw a closed session's sticky and preview claims.

        A closed session's row cannot render, but its id in the sticky list or
        the preview slot would keep being mirrored to the pane bridge on every
        refresh and would persist across restarts. The withdrawal speaks the
        same message protocol the interaction path uses, so the layout reflows
        now rather than at the next reconcile.
        """
        self._cancel_highlight_timer(session_id)  # type: ignore[attr-defined]
        if session_id in self._sticky_session_ids:  # type: ignore[attr-defined]
            self._sticky_session_ids.remove(session_id)  # type: ignore[attr-defined]
            self.post_message(StickyChanged(list(self._sticky_session_ids)))  # type: ignore[attr-defined]
        if self.preview_session_id == session_id:  # type: ignore[attr-defined]
            self.preview_session_id = None  # type: ignore[attr-defined]
            self.post_message(PreviewChanged(None, request_focus=False))  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def update_session(self, session: SessionDTO) -> None:
        """Update a single session row with new data."""
        if session.status in HIDDEN_SESSION_STATUSES:
            # Only a terminal status releases state: "closing" is in flight and
            # a failed close restores the session, so releasing there would
            # strip a live session's layout claims. The row is hidden either
            # way; the release for the ordinary path rides the confirmed
            # SessionClosed signal through confirm_session_closed.
            if session.status == SessionLifecycleStatus.CLOSED:
                self.drop_session_state(session.session_id)  # type: ignore[attr-defined]
                self._release_layout_claims(session.session_id)
            remaining = [  # type: ignore[attr-defined]
                item for item in self._sessions if item.session_id != session.session_id
            ]
            if len(remaining) != len(self._sessions):  # type: ignore[attr-defined]
                self.update_data(  # type: ignore[attr-defined]
                    computers=self._computers,  # type: ignore[attr-defined]
                    projects=self._projects,  # type: ignore[attr-defined]
                    sessions=remaining,
                )
            return

        updated = False
        next_sessions: list[SessionDTO] = []
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
            )
            return

        if not updated:
            next_sessions.append(session)
            self.update_data(  # type: ignore[attr-defined]
                computers=self._computers,  # type: ignore[attr-defined]
                projects=self._projects,  # type: ignore[attr-defined]
                sessions=next_sessions,
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
        # Out-bearing events carry the rendered out-line text. Retaining each
        # non-empty value in memory — on the widget reactive (survives the
        # user_prompt_submit clear within a live widget) and in _retained_out
        # (survives tree rebuilds) — keeps the render fallback supplied so the
        # out line never drops once a value has appeared. user_prompt_submit and
        # empty-text events are not out-bearing and must not overwrite it.
        out_bearing = hook_type in ("pre_tool_use", "thinking", "agent_stop") and bool(text)
        self._retained_activity[session_id] = (hook_type, text)  # type: ignore[attr-defined]
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.activity_event = hook_type
                widget.activity_text = text
                if out_bearing:
                    widget.last_output_summary = text
                break
        if out_bearing:
            self._retained_out[session_id] = text  # type: ignore[attr-defined]
        # Persist only the agent_stop summary to disk so output survives a
        # restart. Live pre_tool_use/thinking values are retained in memory
        # (_retained_out) only — per-event disk writes are too heavy.
        if hook_type == "agent_stop" and text:
            self._last_output_summary[session_id] = {  # type: ignore[attr-defined]
                "text": text,
                "ts": time.monotonic(),
            }
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
            "collapsed_computers": sorted(self._collapsed_computers),  # type: ignore[attr-defined]
            "collapsed_projects": [list(key) for key in sorted(self._collapsed_projects)],  # type: ignore[attr-defined]
            "preview": (  # type: ignore[attr-defined]
                {"session_id": self.preview_session_id} if self.preview_session_id else None
            ),
            "highlighted_session_id": self._highlighted_session_id,  # type: ignore[attr-defined]
        }
