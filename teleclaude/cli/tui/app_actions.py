"""TelecAppActionsMixin — user-initiated action handlers, tab switching, pane theming."""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger
from textual import work
from textual.widgets import TabbedContent

from teleclaude.cli.tui.messages import (
    CreateSessionRequest,
    KillSessionRequest,
    PreviewChanged,
    RestartSessionRequest,
    RestartSessionsRequest,
    ReviveSessionRequest,
    SettingsChanged,
    StateChanged,
    StickyChanged,
)
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge
from teleclaude.cli.tui.theme import get_pane_theming_mode_level
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar
from teleclaude.cli.tui.widgets.telec_footer import TelecFooter

logger = get_logger(__name__)


class TelecAppActionsMixin:
    """User-initiated action handlers, tab switching, and pane theming."""

    def action_clear_layout(self) -> None:
        """Global ESC: tear down all preview, sticky, and doc panes."""
        sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)  # type: ignore[attr-defined]
        had_preview = sessions_view.preview_session_id is not None
        had_sticky = bool(sessions_view._sticky_session_ids)
        had_doc = pane_bridge._active_doc_preview is not None
        if not had_preview and not had_sticky and not had_doc:
            return
        if had_preview:
            sessions_view.preview_session_id = None
            self.post_message(PreviewChanged(None, request_focus=False))  # type: ignore[attr-defined]
        if had_sticky:
            from teleclaude.cli.tui.views.sessions import SessionRow

            sessions_view._sticky_session_ids.clear()
            for widget in sessions_view._nav_items:
                if isinstance(widget, SessionRow):
                    widget.is_sticky = False
            self.post_message(StickyChanged([]))  # type: ignore[attr-defined]
        if had_doc:
            pane_bridge._set_preview(focus=False)
        sessions_view._notify_state_changed()

    @work(exclusive=True, group="session-action")
    async def on_create_session_request(self, message: CreateSessionRequest) -> None:
        # Revive by TeleClaude session ID
        if message.revive_session_id:
            try:
                result = await self.api.revive_session(message.revive_session_id)  # type: ignore[attr-defined]
                if result.status == "success":
                    self.notify(f"Revived session {message.revive_session_id}...")  # type: ignore[attr-defined]
                else:
                    self.notify(result.error or "Revive failed", severity="error")  # type: ignore[attr-defined]
            except Exception as e:
                self.notify(f"Failed to revive session: {e}", severity="error")  # type: ignore[attr-defined]
            return

        if not message.agent:
            self.notify("CreateSessionRequest has no agent", severity="error")  # type: ignore[attr-defined]
            return

        # Resume by native session ID
        if message.native_session_id:
            auto_command = f"agent_resume {message.agent} {message.native_session_id}"
            try:
                await self.api.create_session(  # type: ignore[attr-defined]
                    computer=message.computer,
                    project_path=message.project_path,
                    agent=message.agent,
                    thinking_mode=message.thinking_mode or "slow",
                    auto_command=auto_command,
                )
                self.notify("Resuming session...")  # type: ignore[attr-defined]
            except Exception as e:
                self.notify(f"Failed to resume session: {e}", severity="error")  # type: ignore[attr-defined]
            return

        # Normal new session
        try:
            await self.api.create_session(  # type: ignore[attr-defined]
                computer=message.computer,
                project_path=message.project_path,
                agent=message.agent,
                thinking_mode=message.thinking_mode or "slow",
                title=message.title,
                message=message.message,
            )
        except Exception as e:
            self.notify(f"Failed to create session: {e}", severity="error")  # type: ignore[attr-defined]

    @work(exclusive=True, group="session-action")
    async def on_kill_session_request(self, message: KillSessionRequest) -> None:
        try:
            ended = await self.api.end_session(message.session_id, message.computer)  # type: ignore[attr-defined]
            if ended:
                sessions_view = self.query_one("#sessions-view", SessionsView)  # type: ignore[attr-defined]
                sessions_view.optimistically_hide_session(message.session_id)
        except Exception as e:
            self.notify(f"Failed to kill session: {e}", severity="error")  # type: ignore[attr-defined]

    @work(exclusive=True, group="session-action")
    async def on_revive_session_request(self, message: ReviveSessionRequest) -> None:
        """Revive a headless session by sending Enter key."""
        try:
            await self.api.send_keys(  # type: ignore[attr-defined]
                session_id=message.session_id,
                computer=message.computer,
                key="enter",
                count=1,
            )
            self.notify("Reviving headless session...")  # type: ignore[attr-defined]
            # Refresh after a delay to pick up the new tmux pane
            await asyncio.sleep(2)
            self._refresh_data()  # type: ignore[attr-defined]
        except Exception as e:
            self.notify(f"Failed to revive session: {e}", severity="error")  # type: ignore[attr-defined]

    @work(exclusive=True, group="session-action")
    async def on_restart_session_request(self, message: RestartSessionRequest) -> None:
        try:
            await self.api.agent_restart(message.session_id)  # type: ignore[attr-defined]
            self.notify("Restarting agent...")  # type: ignore[attr-defined]
        except Exception as e:
            self.notify(f"Failed to restart session: {e}", severity="error")  # type: ignore[attr-defined]

    @work(exclusive=True, group="session-action")
    async def on_restart_sessions_request(self, message: RestartSessionsRequest) -> None:
        failures = 0
        for session_id in message.session_ids:
            try:
                await self.api.agent_restart(session_id)  # type: ignore[attr-defined]
            except Exception:
                failures += 1
                logger.exception("Failed to restart session %s", session_id)

        if failures:
            self.notify(  # type: ignore[attr-defined]
                f"Restarted {len(message.session_ids) - failures}/{len(message.session_ids)} sessions",
                severity="warning",
            )
        else:
            self.notify(f"Restarted {len(message.session_ids)} sessions on {message.computer}")  # type: ignore[attr-defined]

    async def on_settings_changed(self, message: SettingsChanged) -> None:
        key = message.key
        if key == "pane_theming_mode":
            self.action_cycle_pane_theming()  # type: ignore[attr-defined]
        elif key == "tts_enabled":
            self._toggle_tts()  # type: ignore[attr-defined]
        elif key == "chiptunes_play_pause":
            self._chiptunes_play_pause()  # type: ignore[attr-defined]
        elif key == "chiptunes_next":
            self._chiptunes_next()  # type: ignore[attr-defined]
        elif key == "chiptunes_prev":
            self._chiptunes_prev()  # type: ignore[attr-defined]
        elif key == "chiptunes_favorite":
            self._chiptunes_favorite()  # type: ignore[attr-defined]
        elif key == "animation_mode":
            self._cycle_animation(str(message.value))  # type: ignore[attr-defined]
        elif key == "agent_status":
            # Handle agent pill clicks: cycle available → degraded → unavailable → available
            if isinstance(message.value, dict):
                agent = str(message.value.get("agent", ""))
                status_bar = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
                current_info = status_bar._agent_availability.get(agent)

                # Determine next status
                if current_info:
                    current_status = current_info.status or "available"
                    if current_status == "available":
                        next_status = "degraded"
                    elif current_status == "degraded":
                        next_status = "unavailable"
                    else:
                        next_status = "available"
                else:
                    next_status = "degraded"

                try:
                    updated_info = await self.api.set_agent_status(  # type: ignore[attr-defined]
                        agent, next_status, reason="manual", duration_minutes=60
                    )
                    status_bar._agent_availability[agent] = updated_info
                    status_bar.refresh()
                except Exception as e:
                    self.notify(f"Failed to set agent status: {e}", severity="error")  # type: ignore[attr-defined]
        elif key.startswith("run_job:"):
            job_name = key.split(":", 1)[1]
            try:
                await self.api.run_job(job_name)  # type: ignore[attr-defined]
                self.notify(f"Job '{job_name}' started")  # type: ignore[attr-defined]
            except Exception as e:
                self.notify(f"Failed to run job: {e}", severity="error")  # type: ignore[attr-defined]

    # --- Tab switching ---

    def action_switch_tab(self, tab_id: str) -> None:
        import time as _t

        _sw0 = _t.monotonic()
        logger.trace("[PERF] action_switch_tab(%s) START t=%.3f", tab_id, _sw0)
        tabs = self.query_one("#main-tabs", TabbedContent)  # type: ignore[attr-defined]
        old_tab = tabs.active
        tabs.active = tab_id
        box_tabs = self.query_one("#box-tab-bar", BoxTabBar)  # type: ignore[attr-defined]
        box_tabs.active_tab = tab_id
        self._focus_active_view(tab_id)
        if old_tab != tab_id:
            self.post_message(StateChanged())  # type: ignore[attr-defined]
        self.call_after_refresh(  # type: ignore[attr-defined]
            lambda: logger.trace("[PERF] action_switch_tab(%s) PAINTED dt=%.3f", tab_id, _t.monotonic() - _sw0)
        )

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        import time as _t

        tab_id = event.pane.id or "sessions"
        logger.trace("[PERF] tab_activated(%s) t=%.3f", tab_id, _t.monotonic())
        # Ignore stale activations (e.g. initial default-tab activation arriving
        # after we've already switched tabs).
        tabs = self.query_one("#main-tabs", TabbedContent)  # type: ignore[attr-defined]
        if tabs.active != tab_id:
            return
        try:
            box_tabs = self.query_one("#box-tab-bar", BoxTabBar)  # type: ignore[attr-defined]
        except Exception:
            # Late activation can arrive while the app is tearing down.
            return
        box_tabs.active_tab = tab_id
        self._focus_active_view(tab_id)
        self.post_message(StateChanged())  # type: ignore[attr-defined]

    def on_box_tab_bar_tab_clicked(self, message: BoxTabBar.TabClicked) -> None:
        """Handle click on custom tab bar."""
        self.action_switch_tab(message.tab_id)

    def _focus_active_view(self, tab_id: str) -> None:
        """Focus the view widget inside the active tab so key bindings work."""
        view_map = {
            "sessions": "#sessions-view",
            "preparation": "#preparation-view",
            "jobs": "#jobs-view",
            "config": "#config-view",
        }
        selector = view_map.get(tab_id)
        if selector:
            try:
                view = self.query_one(selector)  # type: ignore[attr-defined]
                view.focus()
            except Exception:
                pass

    def _apply_app_theme_for_mode(self, pane_theming_mode: str) -> None:
        from teleclaude.cli.tui import theme

        try:
            level = get_pane_theming_mode_level(pane_theming_mode)
        except ValueError:
            level = get_pane_theming_mode_level()
        is_agent = level in (1, 3, 4)
        is_dark = theme.is_dark_mode()
        if is_dark:
            self.theme = "teleclaude-dark-agent" if is_agent else "teleclaude-dark"  # type: ignore[attr-defined]
        else:
            self.theme = "teleclaude-light-agent" if is_agent else "teleclaude-light"  # type: ignore[attr-defined]

    # --- Pane theming ---

    def action_cycle_pane_theming(self) -> None:
        from teleclaude.cli.tui import theme
        from teleclaude.cli.tui.widgets.session_row import SessionRow
        from teleclaude.cli.tui.widgets.todo_row import TodoRow

        current_level = theme.get_pane_theming_mode_level()
        next_level = (current_level + 1) % 5
        mode = theme.get_pane_theming_mode_from_level(next_level)
        theme.set_pane_theming_mode(mode)

        # Switch app theme based on new level (Peaceful=0/2 -> Neutral, Agent=1/3/4 -> Warm)
        self._apply_app_theme_for_mode(mode)

        status_bar = self.query_one("#telec-footer", TelecFooter)  # type: ignore[attr-defined]
        status_bar.pane_theming_mode = mode
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)  # type: ignore[attr-defined]
        pane_bridge.reapply_colors()
        # Refresh theme-dependent widgets (agent vs peaceful colors)
        for widget in self.query(SessionRow):  # type: ignore[attr-defined]
            widget.refresh()
        for widget in self.query(TodoRow):  # type: ignore[attr-defined]
            widget.refresh()
