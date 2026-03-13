"""TelecAppWsMixin — WebSocket event handling and session message handlers."""

from __future__ import annotations

from instrukt_ai_logging import get_logger
from textual.widgets import TabbedContent

from teleclaude.cli.models import (
    AgentActivityEvent,
    ChiptunesStateEvent,
    ChiptunesTrackEvent,
    ErrorEvent,
    ProjectsInitialEvent,
    ProjectWithTodosInfo,
    SessionClosedEvent,
    SessionLifecycleStatusEvent,
    SessionsInitialEvent,
    SessionStartedEvent,
    SessionUpdatedEvent,
    WsEvent,
)
from teleclaude.cli.tui.messages import (
    AgentActivity,
    SessionClosed,
    SessionStarted,
    SessionUpdated,
)
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView

logger = get_logger(__name__)


class TelecAppWsMixin:
    """WebSocket event handling and session lifecycle message handlers."""

    def _on_ws_event(self, event: WsEvent) -> None:
        """Handle WebSocket event from background thread — safe handoff to Textual."""
        self.call_from_thread(self._handle_ws_event, event)  # type: ignore[attr-defined]

    def _on_ws_connected(self) -> None:
        """Handle websocket reconnect from the background thread."""
        self.call_from_thread(self._handle_ws_connected)  # type: ignore[attr-defined]

    def _handle_ws_connected(self) -> None:
        """Refresh authoritative state after websocket (re)connect."""
        self._refresh_data()  # type: ignore[attr-defined]

    def _handle_ws_event(self, event: WsEvent) -> None:
        """Process WebSocket event in the main thread."""
        if isinstance(event, SessionsInitialEvent):
            sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
            sessions_view.update_data(
                computers=sessions_view._computers,
                projects=sessions_view._projects,
                sessions=event.data.sessions,
            )

        elif isinstance(event, ProjectsInitialEvent):
            prep_view = self.query_one("#preparation-view", PreparationView)  # type: ignore[attr-defined]
            projects_with_todos = [
                ProjectWithTodosInfo(
                    computer=p.computer,
                    name=p.name,
                    path=p.path,
                    description=p.description,
                    todos=getattr(p, "todos", []),
                )
                for p in event.data.projects
            ]
            prep_view.update_data(projects_with_todos)

        elif isinstance(event, SessionStartedEvent):
            self.post_message(SessionStarted(event.data))  # type: ignore[attr-defined]

        elif isinstance(event, SessionUpdatedEvent):
            session = event.data
            self.post_message(SessionUpdated(session))  # type: ignore[attr-defined]

        elif isinstance(event, AgentActivityEvent):
            self.post_message(  # type: ignore[attr-defined]
                AgentActivity(
                    session_id=event.session_id,
                    activity_type=event.type,
                    canonical_type=event.canonical_type,
                    tool_name=event.tool_name,
                    tool_preview=event.tool_preview,
                    summary=event.summary,
                    timestamp=event.timestamp,
                )
            )

        elif isinstance(event, SessionClosedEvent):
            self.post_message(SessionClosed(event.data.session_id))  # type: ignore[attr-defined]

        elif isinstance(event, SessionLifecycleStatusEvent):
            # Surface stall and error transitions as TUI notifications.
            if event.status in ("stalled", "error"):
                if event.reason == "close_failed":
                    self.notify(f"Session {event.session_id} failed to close", severity="error")  # type: ignore[attr-defined]
                    self._refresh_data()  # type: ignore[attr-defined]
                else:
                    self.notify(f"Session {event.session_id}: {event.status}", severity="warning")  # type: ignore[attr-defined]

        elif isinstance(event, ErrorEvent):
            self.notify(event.data.message, severity="error")  # type: ignore[attr-defined]

        elif isinstance(event, ChiptunesTrackEvent):
            self._apply_chiptunes_footer_state(  # type: ignore[attr-defined]
                loaded=True,
                playback="playing",
                state_version=None,
                playing=True,
                track=event.track,
                sid_path=event.sid_path,
                pending_command_id="",
                pending_action="",
            )
            if event.track:
                self.notify(f"♪ Now Playing: {event.track}", timeout=4)  # type: ignore[attr-defined]

        elif isinstance(event, ChiptunesStateEvent):
            self._apply_chiptunes_footer_state(  # type: ignore[attr-defined]
                loaded=event.loaded,
                playback=event.playback,
                state_version=event.state_version,
                playing=event.playing,
                track=event.track,
                sid_path=event.sid_path,
                pending_command_id=event.pending_command_id,
                pending_action=event.pending_action,
            )

        else:
            if event.event == "computer_updated":
                self._reload_computers()  # type: ignore[attr-defined]
            self._refresh_data()  # type: ignore[attr-defined]

    # --- Message handlers for WS-generated messages ---

    def on_session_started(self, message: SessionStarted) -> None:
        session = message.session
        if session.active_agent:
            self._session_agents[session.session_id] = session.active_agent  # type: ignore[attr-defined]
        # Auto-select new user-initiated sessions only while Sessions tab is active.
        # Otherwise this steals focus from Preparation/other tabs.
        if not session.initiator_session_id:
            tabs = self.query_one("#main-tabs", TabbedContent)  # type: ignore[attr-defined]
            if tabs.active == "sessions":
                sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
                sessions_view.request_select_session(session.session_id)
        # Trigger full data refresh so tree rebuilds
        self._refresh_data()  # type: ignore[attr-defined]

    def on_session_updated(self, message: SessionUpdated) -> None:
        session = message.session
        if session.active_agent:
            self._session_agents[session.session_id] = session.active_agent  # type: ignore[attr-defined]
        sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
        sessions_view.update_session(session)
        # Session may now have a tmux pane — try pending auto-select
        sessions_view._apply_pending_selection()

    def on_session_closed(self, message: SessionClosed) -> None:
        self._session_agents.pop(message.session_id, None)  # type: ignore[attr-defined]
        sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
        sessions_view.confirm_session_closed(message.session_id)
        self._refresh_data()  # type: ignore[attr-defined]

    def on_agent_activity(self, message: AgentActivity) -> None:
        sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
        hook = message.activity_type
        logger.debug(
            "tui lane: on_agent_activity lane=tui hook=%s session=%s",
            hook,
            message.session_id if message.session_id else "",
            extra={"lane": "tui", "hook": hook, "session_id": message.session_id},
        )
        if message.canonical_type is None:
            logger.warning(
                "tui lane: AgentActivity missing canonical_type lane=tui hook_type=%s session=%s",
                hook,
                message.session_id if message.session_id else "",
                extra={"lane": "tui", "canonical_type": None, "session_id": message.session_id},
            )
            return

        sid = message.session_id

        if hook == "user_prompt_submit":
            sessions_view.update_activity(sid, "user_prompt_submit")
            sessions_view.set_input_highlight(sid)

        elif hook == "tool_use":
            tool_info = ""
            if message.tool_name:
                preview = message.tool_preview or ""
                if preview.startswith(message.tool_name):
                    preview = preview[len(message.tool_name) :].lstrip()
                tool_info = f"{message.tool_name}: {preview}" if preview else message.tool_name
            sessions_view.update_activity(sid, "tool_use", tool_info)

        elif hook == "tool_done":
            sessions_view.update_activity(sid, "tool_done")

        elif hook == "agent_stop":
            sessions_view.update_activity(sid, "agent_stop", message.summary or "")
            sessions_view.set_output_highlight(sid, message.summary or "")
            # Animation trigger
            if self._activity_trigger is not None:  # type: ignore[attr-defined]
                from teleclaude.cli.tui.animation_triggers import ActivityTrigger

                if isinstance(self._activity_trigger, ActivityTrigger):  # type: ignore[attr-defined]
                    agent = self._session_agents.get(sid)  # type: ignore[attr-defined]
                    if agent:
                        self._activity_trigger.on_agent_activity(agent, is_big=True)  # type: ignore[attr-defined]
                        self._activity_trigger.on_agent_activity(agent, is_big=False)  # type: ignore[attr-defined]

        else:
            logger.debug("tui lane: unhandled hook %r", hook)
