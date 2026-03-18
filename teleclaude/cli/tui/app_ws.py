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
from teleclaude.cli.tui.animation_triggers import ActivityTrigger
from teleclaude.cli.tui.messages import (
    AgentActivity,
    SessionClosed,
    SessionStarted,
    SessionUpdated,
)
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge
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
        if self._handle_initial_data_event(event):
            return
        if self._handle_session_event(event):
            return
        if self._handle_status_event(event):
            return
        if self._handle_chiptunes_event(event):
            return
        self._handle_fallback_event(event)

    def _handle_initial_data_event(self, event: WsEvent) -> bool:
        """Handle websocket events that update cached view data."""
        if isinstance(event, SessionsInitialEvent):
            sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
            computers, projects = self._get_sessions_view_data(sessions_view)
            sessions_view.update_data(
                computers=computers,
                projects=projects,
                sessions=event.data.sessions,
            )
            return True

        if isinstance(event, ProjectsInitialEvent):
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
            return True

        return False

    def _handle_session_event(self, event: WsEvent) -> bool:
        """Handle websocket events that become Textual session messages."""
        if isinstance(event, SessionStartedEvent):
            self.post_message(SessionStarted(event.data))  # type: ignore[attr-defined]
            return True

        if isinstance(event, SessionUpdatedEvent):
            session = event.data
            self.post_message(SessionUpdated(session))  # type: ignore[attr-defined]
            return True

        if isinstance(event, AgentActivityEvent):
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
            return True

        if isinstance(event, SessionClosedEvent):
            self.post_message(SessionClosed(event.data.session_id))  # type: ignore[attr-defined]
            return True

        return False

    def _handle_status_event(self, event: WsEvent) -> bool:
        """Handle websocket status and error notifications."""
        if isinstance(event, SessionLifecycleStatusEvent):
            self._notify_session_lifecycle_status(event)
            return True

        if isinstance(event, ErrorEvent):
            self.notify(event.data.message, severity="error")  # type: ignore[attr-defined]
            return True

        return False

    def _handle_chiptunes_event(self, event: WsEvent) -> bool:
        """Handle chiptunes status updates for the footer."""
        if isinstance(event, ChiptunesTrackEvent):
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
            return True

        if isinstance(event, ChiptunesStateEvent):
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
            return True

        return False

    def _handle_fallback_event(self, event: WsEvent) -> None:
        """Refresh app state for websocket events without explicit handlers."""
        if event.event == "computer_updated":
            self._reload_computers()  # type: ignore[attr-defined]
        self._refresh_data()  # type: ignore[attr-defined]

    def _notify_session_lifecycle_status(self, event: SessionLifecycleStatusEvent) -> None:
        """Surface session lifecycle failures as TUI notifications."""
        if event.status != "error":
            return
        if event.reason == "close_failed":
            self.notify(  # type: ignore[attr-defined]
                f"Session {event.session_id} failed to close",
                severity="error",
            )
            self._refresh_data()  # type: ignore[attr-defined]
            return
        self.notify(  # type: ignore[attr-defined]
            f"Session {event.session_id}: {event.status}",
            severity="warning",
        )

    @staticmethod
    def _get_sessions_view_data(sessions_view: SessionsView) -> tuple[object, object]:
        """Return cached computers and projects from the sessions view."""
        return (
            getattr(sessions_view, "_computers", []),
            getattr(sessions_view, "_projects", []),
        )

    @staticmethod
    def _apply_pending_session_selection(sessions_view: SessionsView) -> None:
        """Apply pending auto-selection when the view exposes the hook."""
        apply_selection = getattr(sessions_view, "_apply_pending_selection", None)
        if callable(apply_selection):
            apply_selection()

    # --- Message handlers for WS-generated messages ---

    def on_session_started(self, message: SessionStarted) -> None:
        """Handle a newly started session broadcast from the websocket."""
        session = message.session
        if session.active_agent:
            self._session_agents[session.session_id] = session.active_agent  # type: ignore[attr-defined]

        # Update pane bridge catalog so layout runs have current data
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)  # type: ignore[attr-defined]
        pane_bridge.update_single_session(session)

        # Apply optimistically — session carries full state from WebSocket
        sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
        sessions_view.update_session(session)

        # Auto-select new user-initiated sessions only while Sessions tab is active.
        if not session.initiator_session_id:
            tabs = self.query_one("#main-tabs", TabbedContent)  # type: ignore[attr-defined]
            if tabs.active == "sessions":
                sessions_view.request_select_session(session.session_id, request_focus=True)
                self._apply_pending_session_selection(sessions_view)

    def on_session_updated(self, message: SessionUpdated) -> None:
        """Handle session updates from the websocket."""
        session = message.session
        if session.active_agent:
            self._session_agents[session.session_id] = session.active_agent  # type: ignore[attr-defined]

        # Update pane bridge catalog so layout runs have current data
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)  # type: ignore[attr-defined]
        pane_bridge.update_single_session(session)

        sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
        sessions_view.update_session(session)
        # Session may now have a tmux pane — try pending auto-select
        self._apply_pending_session_selection(sessions_view)

    def on_session_closed(self, message: SessionClosed) -> None:
        """Handle session closure from the websocket."""
        self._session_agents.pop(message.session_id, None)  # type: ignore[attr-defined]

        # Update pane bridge catalog
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)  # type: ignore[attr-defined]
        pane_bridge.remove_session(message.session_id)

        sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
        sessions_view.confirm_session_closed(message.session_id)

    def on_agent_activity(self, message: AgentActivity) -> None:
        """Update activity indicators for a session."""
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
                if isinstance(self._activity_trigger, ActivityTrigger):  # type: ignore[attr-defined]
                    agent = self._session_agents.get(sid)  # type: ignore[attr-defined]
                    if agent:
                        self._activity_trigger.on_agent_activity(agent, is_big=True)  # type: ignore[attr-defined]
                        self._activity_trigger.on_agent_activity(agent, is_big=False)  # type: ignore[attr-defined]

        else:
            logger.debug("tui lane: unhandled hook %r", hook)
