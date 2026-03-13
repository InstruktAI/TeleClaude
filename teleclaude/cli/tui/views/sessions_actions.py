"""Action, check_action, watch_cursor_index, and on_focus mixin for SessionsView."""

from __future__ import annotations

import time

from textual.widgets import Footer

from teleclaude.cli.tui.messages import (
    CreateSessionRequest,
    KillSessionRequest,
    PreviewChanged,
    RestartSessionsRequest,
    StickyChanged,
)
from teleclaude.cli.tui.views.interaction import TreeInteractionAction
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.modals import ConfirmModal, StartSessionModal
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.session_row import SessionRow

# Double-press detection threshold (seconds)
DOUBLE_PRESS_THRESHOLD = 0.65
MAX_STICKY = 5


class SessionsViewActionsMixin:
    """Keyboard actions, check_action, watch_cursor_index, on_focus for SessionsView."""

    def action_cursor_up(self) -> None:
        if self._nav_items and self.cursor_index > 0:  # type: ignore[attr-defined]
            self.cursor_index -= 1  # type: ignore[attr-defined]
            self._update_cursor_highlight()  # type: ignore[attr-defined]
            self._scroll_to_cursor()

    def action_cursor_down(self) -> None:
        if self._nav_items and self.cursor_index < len(self._nav_items) - 1:  # type: ignore[attr-defined]
            self.cursor_index += 1  # type: ignore[attr-defined]
            self._update_cursor_highlight()  # type: ignore[attr-defined]
            self._scroll_to_cursor()

    def _scroll_to_cursor(self) -> None:
        """Scroll the current cursor item into view."""
        if self._nav_items and 0 <= self.cursor_index < len(self._nav_items):  # type: ignore[attr-defined]
            self._nav_items[self.cursor_index].scroll_visible()  # type: ignore[attr-defined]

    def action_toggle_preview(self) -> None:
        """Space: single press = preview (no focus), double press = toggle sticky.

        Uses TreeInteractionState for double-press detection with guard intervals.
        If session is headless, revive it first.
        """
        row = self._current_session_row()  # type: ignore[attr-defined]
        if not row:
            return

        # Headless sessions: revive instead of preview
        if self._is_headless(row):  # type: ignore[attr-defined]
            self._revive_headless(row)  # type: ignore[attr-defined]
            return

        now = time.monotonic()
        session_id = row.session_id
        is_sticky = session_id in self._sticky_session_ids  # type: ignore[attr-defined]

        decision = self._interaction.decide_preview_action(  # type: ignore[attr-defined]
            session_id,
            now,
            is_sticky=is_sticky,
            allow_sticky_toggle=True,
        )

        if decision.action == TreeInteractionAction.NONE:
            return

        if decision.action == TreeInteractionAction.PREVIEW:
            if session_id == self.preview_session_id:  # type: ignore[attr-defined]
                # Already previewed — toggle OFF
                self.preview_session_id = None  # type: ignore[attr-defined]
                self.post_message(PreviewChanged(None, request_focus=False))  # type: ignore[attr-defined]
            else:
                self.preview_session_id = session_id  # type: ignore[attr-defined]
                self._clear_session_highlights(session_id)  # type: ignore[attr-defined]
                self.post_message(PreviewChanged(session_id, request_focus=False))  # type: ignore[attr-defined]
            self._notify_state_changed()  # type: ignore[attr-defined]

        elif decision.action == TreeInteractionAction.TOGGLE_STICKY:
            self._toggle_sticky(session_id)
            if decision.clear_preview:
                # Double-space on sticky removes sticky and promotes it to preview.
                self.preview_session_id = session_id  # type: ignore[attr-defined]
                self.post_message(PreviewChanged(session_id, request_focus=False))  # type: ignore[attr-defined]
                self._notify_state_changed()  # type: ignore[attr-defined]
            self._interaction.mark_double_press_guard(session_id, now)  # type: ignore[attr-defined]

        elif decision.action == TreeInteractionAction.CLEAR_STICKY_PREVIEW:
            self.preview_session_id = None  # type: ignore[attr-defined]
            self._clear_session_highlights(session_id)  # type: ignore[attr-defined]
            self.post_message(PreviewChanged(None, request_focus=False))  # type: ignore[attr-defined]
            self._notify_state_changed()  # type: ignore[attr-defined]

    def _toggle_sticky(self, session_id: str) -> None:
        """Toggle sticky status for a session."""
        if session_id in self._sticky_session_ids:  # type: ignore[attr-defined]
            self._sticky_session_ids.remove(session_id)  # type: ignore[attr-defined]
        else:
            if len(self._sticky_session_ids) >= MAX_STICKY:  # type: ignore[attr-defined]
                return
            self._sticky_session_ids.append(session_id)  # type: ignore[attr-defined]

        # Update all session rows
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow):
                widget.is_sticky = widget.session_id in self._sticky_session_ids  # type: ignore[attr-defined]

        self.post_message(StickyChanged(self._sticky_session_ids.copy()))  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def action_focus_pane(self) -> None:
        """Enter: on a session — preview AND focus the tmux pane.

        On a project header — open new session modal.
        On a computer header — open new session modal in path-input mode.
        If session is headless, revive it first.
        """
        row = self._current_session_row()  # type: ignore[attr-defined]
        if not row:
            item = self._current_item()  # type: ignore[attr-defined]
            if isinstance(item, ComputerHeader):
                self.action_new_session(path_mode=True)
            else:
                self.action_new_session()
            return

        # Headless sessions: revive instead of focus
        if self._is_headless(row):  # type: ignore[attr-defined]
            self._revive_headless(row)  # type: ignore[attr-defined]
            return

        session_id = row.session_id

        # Set preview
        self.preview_session_id = session_id  # type: ignore[attr-defined]

        # Clear highlights
        self._clear_session_highlights(session_id)  # type: ignore[attr-defined]

        # Post with request_focus=True — pane shows AND cursor transfers to it
        self.post_message(PreviewChanged(session_id, request_focus=True))  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def action_collapse(self) -> None:
        """Left: collapse selected session row."""
        row = self._current_session_row()  # type: ignore[attr-defined]
        if row and not row.collapsed:
            row.collapsed = True
            self._collapsed_sessions.discard(row.session_id)  # type: ignore[attr-defined]
            self._notify_state_changed()  # type: ignore[attr-defined]

    def action_expand(self) -> None:
        """Right: expand selected session row."""
        row = self._current_session_row()  # type: ignore[attr-defined]
        if row and row.collapsed:
            row.collapsed = False
            self._collapsed_sessions.add(row.session_id)  # type: ignore[attr-defined]
            self._notify_state_changed()  # type: ignore[attr-defined]

    def action_expand_all(self) -> None:
        """+ : expand all session rows."""
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow):
                widget.collapsed = False
                self._collapsed_sessions.add(widget.session_id)  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def action_collapse_all(self) -> None:
        """- : collapse all session rows."""
        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow):
                widget.collapsed = True
        self._collapsed_sessions.clear()  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def _resolve_context_for_cursor(self) -> tuple[str, str] | None:
        """Resolve computer + project_path from the current cursor position.

        Walks from cursor upward through nav_items to find the nearest
        ProjectHeader and ComputerHeader.
        """
        if not self._nav_items or self.cursor_index >= len(self._nav_items):  # type: ignore[attr-defined]
            return None

        item = self._nav_items[self.cursor_index]  # type: ignore[attr-defined]

        # On a session row — use its session data
        if isinstance(item, SessionRow) and item.session:
            return (item.session.computer or "local", item.session.project_path or "")

        # On a project header — use its data, walk up for computer
        if isinstance(item, ProjectHeader):
            computer = "local"
            for i in range(self.cursor_index - 1, -1, -1):  # type: ignore[attr-defined]
                nav = self._nav_items[i]  # type: ignore[attr-defined]
                if isinstance(nav, ComputerHeader):
                    computer = nav.data.computer.name
                    break
            return (computer, item.project.path)

        # On a computer header — use first project under it
        if isinstance(item, ComputerHeader):
            computer = item.data.computer.name
            for i in range(self.cursor_index + 1, len(self._nav_items)):  # type: ignore[attr-defined]
                nav = self._nav_items[i]  # type: ignore[attr-defined]
                if isinstance(nav, ProjectHeader):
                    return (computer, nav.project.path)
                if isinstance(nav, ComputerHeader):
                    break
            # No project found under this computer — use first project
            if self._projects:  # type: ignore[attr-defined]
                return (computer, self._projects[0].path)  # type: ignore[attr-defined]

        return None

    def action_new_session(self, path_mode: bool = False) -> None:
        """n: open new session modal. path_mode=True adds a project path input."""
        context = self._resolve_context_for_cursor()
        if context:
            computer, project_path = context
        elif self._projects:  # type: ignore[attr-defined]
            computer = self._projects[0].computer or "local"  # type: ignore[attr-defined]
            project_path = self._projects[0].path  # type: ignore[attr-defined]
        else:
            return

        modal = StartSessionModal(
            computer=computer,
            project_path=project_path,
            agent_availability=self._availability,  # type: ignore[attr-defined]
            path_mode=path_mode,
        )
        self.app.push_screen(modal, self._on_create_session_result)  # type: ignore[attr-defined]

    def _on_create_session_result(self, result: CreateSessionRequest | None) -> None:
        """Handle result from StartSessionModal."""
        if result:
            self.post_message(result)  # type: ignore[attr-defined]

    def action_kill_session(self) -> None:
        """k: kill selected session (with confirmation)."""
        row = self._current_session_row()  # type: ignore[attr-defined]
        if not row:
            return

        session_id = row.session_id
        computer = row.session.computer or "local"
        title = row.session.title or "(untitled)"

        modal = ConfirmModal(
            title="Kill Session",
            message=f"Kill session '{title}'?",
        )

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.post_message(KillSessionRequest(session_id, computer))  # type: ignore[attr-defined]

        self.app.push_screen(modal, on_confirm)  # type: ignore[attr-defined]

    def action_restart_session(self) -> None:
        """R: restart selected session."""
        row = self._current_session_row()  # type: ignore[attr-defined]
        if not row:
            return
        from teleclaude.cli.tui.messages import RestartSessionRequest

        self.post_message(RestartSessionRequest(row.session_id, row.session.computer or "local"))  # type: ignore[attr-defined]

    def action_restart_project(self) -> None:
        """R on project header: restart all sessions for that project."""
        item = self._current_item()  # type: ignore[attr-defined]
        if not isinstance(item, ProjectHeader):
            return

        project_path = item.project.path
        session_ids = sorted({s.session_id for s in self._sessions if s.project_path == project_path})  # type: ignore[attr-defined]
        if not session_ids:
            self.app.notify(f"No sessions to restart in {item.project.name}", severity="warning")  # type: ignore[attr-defined]
            return

        modal = ConfirmModal(
            title="Restart Project Sessions",
            message=f"Restart {len(session_ids)} sessions in '{item.project.name}'?",
        )

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                computer = item.project.computer or "local"
                self.post_message(RestartSessionsRequest(computer=computer, session_ids=session_ids))  # type: ignore[attr-defined]

        self.app.push_screen(modal, on_confirm)  # type: ignore[attr-defined]

    def action_restart_all(self) -> None:
        """R on computer header: restart all sessions on that computer."""
        item = self._current_item()  # type: ignore[attr-defined]
        if not isinstance(item, ComputerHeader):
            return

        computer = item.data.computer.name
        session_ids = sorted({s.session_id for s in self._sessions if (s.computer or "local") == computer})  # type: ignore[attr-defined]
        if not session_ids:
            self.app.notify(f"No sessions to restart on {computer}", severity="warning")  # type: ignore[attr-defined]
            return

        modal = ConfirmModal(
            title="Restart All Sessions",
            message=f"Restart {len(session_ids)} sessions on '{computer}'?",
        )

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.post_message(RestartSessionsRequest(computer=computer, session_ids=session_ids))  # type: ignore[attr-defined]

        self.app.push_screen(modal, on_confirm)  # type: ignore[attr-defined]

    def action_new_project(self) -> None:
        """n on computer header: open New Project modal."""
        from teleclaude.cli.tui.widgets.modals import NewProjectModal, NewProjectResult

        item = self._current_item()  # type: ignore[attr-defined]
        if not isinstance(item, ComputerHeader):
            return

        computer = item.data.computer

        def on_result(result: NewProjectResult | None) -> None:
            if not result:
                return
            import subprocess

            yaml_patch = f"computer:\n  trusted_dirs:\n    - name: {result.name}\n      path: {result.path}\n"
            if result.description:
                yaml_patch += f"      description: {result.description}\n"
            try:
                subprocess.run(
                    ["telec", "config", "patch", "--yaml", yaml_patch],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as exc:
                self.app.notify(f"Failed to save project: {exc.stderr.decode()[:80]}", severity="error")  # type: ignore[attr-defined]
                return
            self.app.notify(f"Project '{result.name}' added")  # type: ignore[attr-defined]

        existing_names = {p.name for p in self._projects if (p.computer or "local") == computer.name}  # type: ignore[attr-defined]
        existing_paths = {p.path for p in self._projects if (p.computer or "local") == computer.name}  # type: ignore[attr-defined]
        self.app.push_screen(  # type: ignore[attr-defined]
            NewProjectModal(existing_names=existing_names, existing_paths=existing_paths),
            on_result,
        )

    def action_toggle_sticky_sessions(self) -> None:
        """a: batch-toggle sticky sessions scoped to project, computer, or globally."""
        item = self._current_item()  # type: ignore[attr-defined]

        if isinstance(item, ProjectHeader):
            scope_ids = {
                s.session_id
                for s in self._sessions  # type: ignore[attr-defined]
                if s.project_path == item.project.path and (s.computer or "local") == (item.project.computer or "local")
            }
        elif isinstance(item, ComputerHeader):
            computer = item.data.computer.name
            scope_ids = {s.session_id for s in self._sessions if (s.computer or "local") == computer}  # type: ignore[attr-defined]
        else:
            # Global: clear all stickies and preview
            if not self._sticky_session_ids and self.preview_session_id is None:  # type: ignore[attr-defined]
                return
            if self.preview_session_id is not None:  # type: ignore[attr-defined]
                self.preview_session_id = None  # type: ignore[attr-defined]
                self.post_message(PreviewChanged(None, request_focus=False))  # type: ignore[attr-defined]
            if not self._sticky_session_ids:  # type: ignore[attr-defined]
                return
            scope_ids = set(self._sticky_session_ids)  # type: ignore[attr-defined]

        sticky_in_scope = [sid for sid in self._sticky_session_ids if sid in scope_ids]  # type: ignore[attr-defined]

        if sticky_in_scope:
            # Toggle OFF: remove sticky for all sessions in scope.
            # Always clear preview — any active preview may belong to a pane that is
            # about to be torn down, and leaving it set causes ghost previews.
            if self.preview_session_id is not None:  # type: ignore[attr-defined]
                self.preview_session_id = None  # type: ignore[attr-defined]
                self.post_message(PreviewChanged(None, request_focus=False))  # type: ignore[attr-defined]
            for sid in sticky_in_scope:
                self._sticky_session_ids.remove(sid)  # type: ignore[attr-defined]
        else:
            # Toggle ON: make first available eligible sessions in scope sticky
            scope_sessions = [s for s in self._sessions if s.session_id in scope_ids and s.tmux_session_name]  # type: ignore[attr-defined]
            if not scope_sessions:
                self.app.notify("No attachable sessions found", severity="warning")  # type: ignore[attr-defined]
                return
            slots = MAX_STICKY - len(self._sticky_session_ids)  # type: ignore[attr-defined]
            if slots <= 0:
                self.app.notify(f"Maximum {MAX_STICKY} sticky sessions reached", severity="warning")  # type: ignore[attr-defined]
                return
            to_add = scope_sessions[:slots]
            if len(scope_sessions) > slots:
                self.app.notify(  # type: ignore[attr-defined]
                    f"Showing first {slots} of {len(scope_sessions)} sessions (max {MAX_STICKY} sticky panes)",
                    severity="warning",
                )
            for s in to_add:
                self._sticky_session_ids.append(s.session_id)  # type: ignore[attr-defined]

        for widget in self._nav_items:  # type: ignore[attr-defined]
            if isinstance(widget, SessionRow):
                widget.is_sticky = widget.session_id in self._sticky_session_ids  # type: ignore[attr-defined]

        self.post_message(StickyChanged(self._sticky_session_ids.copy()))  # type: ignore[attr-defined]
        self._notify_state_changed()  # type: ignore[attr-defined]

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Enable/hide actions based on current tree node type."""
        del parameters
        item = self._current_item()  # type: ignore[attr-defined]

        if action == "new_session":
            return isinstance(item, ProjectHeader)
        if action == "new_project":
            return isinstance(item, ComputerHeader)
        if action == "focus_pane":
            return isinstance(item, (ProjectHeader, ComputerHeader, SessionRow))
        if action in {"kill_session", "restart_session", "toggle_preview"}:
            return isinstance(item, SessionRow)
        if action == "restart_project":
            return isinstance(item, ProjectHeader)
        if action == "toggle_sticky_sessions":
            return True
        if action == "restart_all":
            return isinstance(item, ComputerHeader)
        return True

    def _default_footer_action(self) -> str | None:
        """Return the primary action for the selected node."""
        item = self._current_item()  # type: ignore[attr-defined]
        if isinstance(item, ComputerHeader):
            return "focus_pane"
        if isinstance(item, ProjectHeader):
            return "new_session"
        if isinstance(item, SessionRow):
            return "focus_pane"
        return None

    def _sync_default_footer_action(self) -> None:
        """Mark the active default action in Footer."""
        if not self.is_attached:  # type: ignore[attr-defined]
            return
        try:
            footer = self.app.query_one(Footer)  # type: ignore[attr-defined]
        except Exception:
            return
        default_action = self._default_footer_action()
        for key_widget in footer.query("FooterKey"):
            key_widget.set_class(getattr(key_widget, "action", None) == default_action, "default-action")

    def watch_cursor_index(self, _index: int) -> None:
        """Refresh key bindings and track highlighted session identity."""
        if self._nav_items and 0 <= _index < len(self._nav_items):  # type: ignore[attr-defined]
            item = self._nav_items[_index]  # type: ignore[attr-defined]
            self._highlighted_session_id = item.session_id if isinstance(item, SessionRow) else None  # type: ignore[attr-defined]
        if self.is_attached:  # type: ignore[attr-defined]
            self.app.refresh_bindings()  # type: ignore[attr-defined]
            self.call_after_refresh(self._sync_default_footer_action)  # type: ignore[attr-defined]

    def on_focus(self) -> None:
        """Sync default footer styling when the view receives focus."""
        self.app.refresh_bindings()  # type: ignore[attr-defined]
        self.call_after_refresh(self._sync_default_footer_action)  # type: ignore[attr-defined]
