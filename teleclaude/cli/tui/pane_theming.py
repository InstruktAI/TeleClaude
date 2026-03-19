"""PaneThemingMixin — pane background and color management for TmuxPaneManager."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui import theme
from teleclaude.cli.tui._pane_specs import SessionPaneSpec
from teleclaude.cli.tui.color_utils import hex_to_nearest_xterm256

logger = get_logger(__name__)


class PaneThemingMixin:
    """Theming and background management methods for TmuxPaneManager."""

    def _set_pane_option(self, pane_id: str, option: str, value: str, *, scope: str = "-p") -> None:
        """Set a tmux pane option using the provided scope."""
        self._run_tmux("set", scope, "-t", pane_id, option, value)  # type: ignore[attr-defined]

    def _unset_pane_option(self, pane_id: str, option: str, *, scope: str = "-p") -> None:
        """Reset a tmux pane option to its inherited value."""
        unset_scope = f"{scope}u"
        self._run_tmux("set", unset_scope, "-t", pane_id, option)  # type: ignore[attr-defined]

    def _set_session_option(self, target: str, option: str, value: str) -> None:
        """Set a tmux session option."""
        self._run_tmux("set", "-t", target, option, value)  # type: ignore[attr-defined]

    def _apply_no_color_policy(self, tmux_session_name: str) -> None:
        """Apply NO_COLOR policy for a tmux session based on theme level."""
        level = theme.get_pane_theming_mode_level()
        if level <= 1:
            self._run_tmux("set-environment", "-t", tmux_session_name, "NO_COLOR", "1")  # type: ignore[attr-defined]
        else:
            self._run_tmux("set-environment", "-t", tmux_session_name, "-u", "NO_COLOR")  # type: ignore[attr-defined]

    def _clear_session_pane_style(self, pane_id: str, tmux_session_name: str) -> None:
        """Reset pane style to native defaults while keeping embedded status hidden."""
        self._unset_pane_option(pane_id, "window-style")
        self._unset_pane_option(pane_id, "window-active-style")
        self._set_session_option(tmux_session_name, "status", "off")
        self._apply_no_color_policy(tmux_session_name)

    def _apply_agent_pane_style(self, pane_id: str, agent: str, *, is_tree_selected: bool) -> None:
        """Apply paint-mode colors for a session pane."""
        bg_color = (
            theme.get_agent_pane_selected_background(agent)
            if is_tree_selected
            else theme.get_agent_pane_inactive_background(agent)
        )
        fg = f"colour{hex_to_nearest_xterm256(theme.get_agent_normal_color(agent))}"
        active_bg = theme.get_agent_pane_active_background(agent)
        self._set_pane_option(pane_id, "window-style", f"fg={fg},bg={bg_color}")
        self._set_pane_option(pane_id, "window-active-style", f"fg={fg},bg={active_bg}")

    def _set_pane_background(
        self,
        pane_id: str,
        tmux_session_name: str,
        agent: str,
        *,
        is_tree_selected: bool = False,
    ) -> None:
        """Set per-pane colors and keep embedded tmux status bar hidden.

        Args:
            pane_id: Tmux pane ID
            tmux_session_name: Tmux session name
            agent: Agent name for color calculation
            is_tree_selected: Use lighter haze when the tree focus selected row matches.
        """
        if not agent:
            logger.debug(
                "_set_pane_background: missing agent for pane %s (tmux=%s); clearing stale style",
                pane_id,
                tmux_session_name,
            )
            self._clear_session_pane_style(pane_id, tmux_session_name)
            return
        if theme.should_apply_paint_pane_theming():
            self._apply_agent_pane_style(
                pane_id,
                agent,
                is_tree_selected=is_tree_selected,
            )
        else:
            self._unset_pane_option(pane_id, "window-style")
            self._unset_pane_option(pane_id, "window-active-style")

        # Embedded session panes should not render tmux status bars.
        self._set_session_option(tmux_session_name, "status", "off")

        # Enforce NO_COLOR for peaceful levels (0, 1) to suppress CLI colors;
        # unset for richer levels (2+) so CLIs can emit full color output.
        self._apply_no_color_policy(tmux_session_name)

        # Override color 236 (message box backgrounds) for specific agents
        # if agent == "codex" and theme.get_current_mode():  # dark mode
        #     # Use color 237 (slightly lighter gray) for Codex message boxes
        #     self._run_tmux("set", "-p", "-t", pane_id, "pane-colours[236]", "#3a3a3a")

    def _set_tui_pane_background(self) -> None:
        """Apply subtle inactive haze styling to the TUI pane only."""
        if not self._tui_pane_id or not self._get_pane_exists(self._tui_pane_id):  # type: ignore[attr-defined]
            return

        if theme.should_apply_session_theming():
            inactive_bg = theme.get_tui_inactive_background()
            terminal_bg = theme.get_terminal_background()
            self._set_pane_option(
                self._tui_pane_id,  # type: ignore[attr-defined]
                "window-style",
                f"bg={inactive_bg}",
            )
            self._set_pane_option(
                self._tui_pane_id,  # type: ignore[attr-defined]
                "window-active-style",
                f"bg={terminal_bg}",
            )
            border_style = f"fg={inactive_bg},bg={inactive_bg}"
            self._set_pane_option(
                self._tui_pane_id,  # type: ignore[attr-defined]
                "pane-border-style",
                border_style,
                scope="-w",
            )
            self._set_pane_option(
                self._tui_pane_id,  # type: ignore[attr-defined]
                "pane-active-border-style",
                border_style,
                scope="-w",
            )
        else:
            self._unset_pane_option(self._tui_pane_id, "window-style")  # type: ignore[attr-defined]
            self._unset_pane_option(self._tui_pane_id, "window-active-style")  # type: ignore[attr-defined]
            self._unset_pane_option(self._tui_pane_id, "pane-border-style", scope="-w")  # type: ignore[attr-defined]
            self._unset_pane_option(
                self._tui_pane_id,  # type: ignore[attr-defined]
                "pane-active-border-style",
                scope="-w",
            )

        # Force tmux to re-evaluate styles based on current focus state.
        self._run_tmux("refresh-client")  # type: ignore[attr-defined]

    def refresh_tui_pane_background(self) -> None:
        """Re-apply styling for the local TUI pane."""
        self._set_tui_pane_background()

    def _set_doc_pane_background(self, pane_id: str, *, agent: str = "") -> None:
        """Apply styling for doc preview panes (glow/less).

        Follows the 5-state paradigm:
        - Levels 0, 1: unstyled (NO_COLOR handled via command prefix)
        - Level 2: unstyled (natural CLI colors)
        - Level 3: agent haze background + agent foreground
        - Level 4: unstyled (natural CLI colors)
        """
        if theme.should_apply_paint_pane_theming():
            inactive_bg = theme.get_tui_inactive_background()
            terminal_bg = theme.get_terminal_background()
            if agent:
                fg = f"colour{hex_to_nearest_xterm256(theme.get_agent_normal_color(agent))}"
                self._set_pane_option(pane_id, "window-style", f"fg={fg},bg={inactive_bg}")
                self._set_pane_option(
                    pane_id,
                    "window-active-style",
                    f"fg={fg},bg={terminal_bg}",
                )
            else:
                self._set_pane_option(pane_id, "window-style", f"bg={inactive_bg}")
                self._set_pane_option(pane_id, "window-active-style", f"bg={terminal_bg}")
        else:
            self._unset_pane_option(pane_id, "window-style")
            self._unset_pane_option(pane_id, "window-active-style")

    def _reapply_spec_pane(self, spec: SessionPaneSpec, reapplied_panes: set[str]) -> None:
        """Re-apply colors for a sticky or active session spec."""
        pane_id = self.state.session_to_pane.get(spec.session_id)  # type: ignore[attr-defined]
        if not pane_id or not self._get_pane_exists(pane_id):  # type: ignore[attr-defined]
            return

        if spec.tmux_session_name:
            self._set_pane_background(
                pane_id,
                spec.tmux_session_name,
                spec.active_agent,
                is_tree_selected=self._is_tree_selected_session(spec.session_id),  # type: ignore[attr-defined]
            )
        else:
            self._set_doc_pane_background(pane_id, agent=spec.active_agent)
        reapplied_panes.add(pane_id)

    def _reapply_catalog_pane(self, session_id: str, pane_id: str, reapplied_panes: set[str]) -> None:
        """Re-apply colors for any pane tracked in the session catalog."""
        if pane_id in reapplied_panes or not self._get_pane_exists(pane_id):  # type: ignore[attr-defined]
            return
        if session_id.startswith("doc:"):
            self._set_doc_pane_background(pane_id)
            return

        session = self._session_catalog.get(session_id)  # type: ignore[attr-defined]
        if not session or not session.tmux_session_name:
            return
        self._set_pane_background(
            pane_id,
            session.tmux_session_name,
            session.active_agent or "",
            is_tree_selected=self._is_tree_selected_session(session_id),  # type: ignore[attr-defined]
        )

    def reapply_agent_colors(self) -> None:
        """Re-apply agent-colored backgrounds and status bars to all session panes.

        Called when appearance theme changes (SIGUSR1) to restore agent colors
        after global theme reload.
        """
        if not self._in_tmux:  # type: ignore[attr-defined]
            return
        self.invalidate_bg_cache()  # type: ignore[attr-defined]

        self.refresh_tui_pane_background()
        reapplied_panes: set[str] = set()

        # Re-apply colors to sticky session panes
        for spec in self._sticky_specs:  # type: ignore[attr-defined]
            self._reapply_spec_pane(spec, reapplied_panes)

        # Re-apply colors to active session pane
        if self._active_spec:  # type: ignore[attr-defined]
            self._reapply_spec_pane(self._active_spec, reapplied_panes)  # type: ignore[attr-defined]

        # Remaining: style any tracked panes not covered by sticky/active specs.
        for session_id, pane_id in self.state.session_to_pane.items():  # type: ignore[attr-defined]
            self._reapply_catalog_pane(session_id, pane_id, reapplied_panes)
