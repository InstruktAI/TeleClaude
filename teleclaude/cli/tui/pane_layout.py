"""PaneLayoutMixin — layout calculation, rendering, and background refresh."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui import theme
from teleclaude.cli.tui._pane_specs import LAYOUT_SPECS, SessionPaneSpec

if TYPE_CHECKING:
    from teleclaude.cli.tui._pane_specs import ComputerInfo
    from teleclaude.cli.tui.state import DocPreviewState

logger = get_logger(__name__)


class PaneLayoutMixin:
    """Layout management methods for TmuxPaneManager."""

    def apply_layout(
        self,
        *,
        active_session_id: str | None,
        sticky_session_ids: list[str],
        get_computer_info: Callable[[str], ComputerInfo | None],
        active_doc_preview: DocPreviewState | None = None,
        selected_session_id: str | None = None,
        tree_node_has_focus: bool = False,
        focus: bool = True,
    ) -> None:
        """Apply a deterministic layout from session ids."""
        if not self._in_tmux:  # type: ignore[attr-defined]
            return

        self._reconcile()  # type: ignore[attr-defined]

        logger.debug(
            "apply_layout: active=%s sticky=%s doc_preview=%s focus=%s tui_pane=%s active_pane=%s",
            active_session_id if active_session_id else None,
            list(sticky_session_ids),
            active_doc_preview.doc_id if active_doc_preview else None,
            focus,
            self._tui_pane_id,  # type: ignore[attr-defined]
            self._active_pane_id,  # type: ignore[attr-defined]
        )

        self._selected_session_id = selected_session_id  # type: ignore[attr-defined]
        self._tree_node_has_focus = tree_node_has_focus  # type: ignore[attr-defined]

        sticky_specs: list[SessionPaneSpec] = []
        for session_id in sticky_session_ids:
            session = self._session_catalog.get(session_id)  # type: ignore[attr-defined]
            if not session:
                continue
            tmux_session = session.tmux_session_name or ""
            if not tmux_session:
                continue
            sticky_specs.append(
                SessionPaneSpec(
                    session_id=session.session_id,
                    tmux_session_name=tmux_session,
                    computer_info=get_computer_info(session.computer or "local"),
                    is_sticky=True,
                    active_agent=session.active_agent or "",
                )
            )
        active_spec: SessionPaneSpec | None = None
        if active_session_id:
            session = self._session_catalog.get(active_session_id)  # type: ignore[attr-defined]
            if session and session.tmux_session_name:
                active_spec = SessionPaneSpec(
                    session_id=session.session_id,
                    tmux_session_name=session.tmux_session_name,
                    computer_info=get_computer_info(session.computer or "local"),
                    is_sticky=False,
                    active_agent=session.active_agent or "",
                )
        elif active_doc_preview:
            active_spec = SessionPaneSpec(
                session_id=f"doc:{active_doc_preview.doc_id}",
                tmux_session_name=None,
                computer_info=None,
                is_sticky=False,
                active_agent="",
                command=active_doc_preview.command,
            )

        self._sticky_specs = sticky_specs  # type: ignore[attr-defined]
        prev_command = self._active_spec.command if self._active_spec else None  # type: ignore[attr-defined]
        self._active_spec = active_spec  # type: ignore[attr-defined]

        if self._layout_is_unchanged():
            logger.debug(
                "apply_layout: layout unchanged, active_spec=%s active_session=%s active_pane=%s",
                active_spec.session_id if active_spec else None,
                self.state.active_session_id if self.state.active_session_id else None,  # type: ignore[attr-defined]
                self._active_pane_id,  # type: ignore[attr-defined]
            )
            if active_spec and self.state.active_session_id != active_spec.session_id:  # type: ignore[attr-defined]
                self._update_active_pane(active_spec)
            elif (
                active_spec
                and active_spec.command
                and self.state.active_session_id == active_spec.session_id  # type: ignore[attr-defined]
                and active_spec.command != prev_command
            ):
                # Same doc_id but command changed (e.g. view → edit mode)
                self._update_active_pane(active_spec)
            if focus and active_spec:
                self.focus_pane_for_session(active_spec.session_id)  # type: ignore[attr-defined]
            if not active_spec:
                self._clear_active_state_if_sticky()
            # Only re-apply pane backgrounds when the selection or agent
            # actually changed.  Each call spawns ~5 tmux subprocesses per
            # pane which dominates the per-click latency.
            bg_sig = self._compute_bg_signature()
            if bg_sig != self._bg_signature:  # type: ignore[attr-defined]
                self._bg_signature = bg_sig  # type: ignore[attr-defined]
                self._refresh_session_pane_backgrounds()
                self._set_tui_pane_background()  # type: ignore[attr-defined]
            return

        logger.debug(
            "apply_layout: layout CHANGED, calling _render_layout (specs=%d)",
            len(self._build_session_specs()),
        )
        self._render_layout()
        self.invalidate_bg_cache()
        if focus and active_spec:
            self.focus_pane_for_session(active_spec.session_id)  # type: ignore[attr-defined]

    def _build_session_specs(self) -> list[SessionPaneSpec]:
        session_specs: list[SessionPaneSpec] = list(self._sticky_specs)  # type: ignore[attr-defined]
        if self._active_spec and not any(  # type: ignore[attr-defined]
            spec.session_id == self._active_spec.session_id
            for spec in session_specs  # type: ignore[attr-defined]
        ):
            session_specs.append(self._active_spec)  # type: ignore[attr-defined]
        if len(session_specs) > 5:
            session_specs = session_specs[:5]
        return session_specs

    def _compute_layout_signature(self) -> tuple[object, ...] | None:
        session_specs = self._build_session_specs()
        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            return None
        # Track structural layout only — sticky IDs + whether an active slot
        # exists.  The active session_id is intentionally excluded so that
        # switching the preview between non-sticky sessions takes the
        # lightweight _update_active_pane path (respawn-pane) instead of
        # tearing down and recreating all tmux panes (_render_layout).
        structural_keys = tuple(spec.session_id if spec.is_sticky else "__active__" for spec in session_specs)
        return (
            layout.rows,
            layout.cols,
            tuple(tuple(row) for row in layout.grid),
            structural_keys,
        )

    def _compute_bg_signature(self) -> tuple[object, ...]:
        """Compute a signature for pane background state.

        Captures the inputs that determine _refresh_session_pane_backgrounds
        and _set_tui_pane_background output: selected session, agents, and
        theming mode.

        Keyed on (pane_id, agent) — NOT session_id — so that switching
        the active preview between sessions with the same agent doesn't
        trigger a redundant full background refresh.
        """
        pane_agents = tuple(
            sorted(
                (pid, (self._session_catalog.get(sid) or None) and self._session_catalog[sid].active_agent)  # type: ignore[attr-defined]
                for sid, pid in self.state.session_to_pane.items()  # type: ignore[attr-defined]
            )
        )
        return (
            self._selected_session_id,  # type: ignore[attr-defined]
            self._tree_node_has_focus,  # type: ignore[attr-defined]
            theme.get_pane_theming_mode(),
            theme.get_current_mode(),
            pane_agents,
        )

    def invalidate_bg_cache(self) -> None:
        """Force background re-application on next apply_layout (e.g. after theme change)."""
        self._bg_signature = None  # type: ignore[attr-defined]

    def _clear_active_state_if_sticky(self) -> None:
        """Clear active_session_id when active has been promoted to sticky."""
        if not self.state.active_session_id:  # type: ignore[attr-defined]
            return
        if any(spec.session_id == self.state.active_session_id for spec in self._sticky_specs):  # type: ignore[attr-defined]
            self.state.active_session_id = None  # type: ignore[attr-defined]

    def _refresh_session_pane_backgrounds(self) -> None:
        """Refresh pane backgrounds for all tracked session panes."""
        if not self._in_tmux:  # type: ignore[attr-defined]
            return

        for session_id, pane_id in self.state.session_to_pane.items():  # type: ignore[attr-defined]
            if not self._get_pane_exists(pane_id):  # type: ignore[attr-defined]
                continue
            if session_id.startswith("doc:"):
                self._set_doc_pane_background(pane_id)  # type: ignore[attr-defined]
                continue

            session = self._session_catalog.get(session_id)  # type: ignore[attr-defined]
            if not session or not session.tmux_session_name:
                continue

            self._set_pane_background(  # type: ignore[attr-defined]
                pane_id,
                session.tmux_session_name,
                session.active_agent or "",
                is_tree_selected=self._is_tree_selected_session(session_id),
            )

    def _update_active_pane(self, active_spec: SessionPaneSpec) -> None:
        """Swap the active pane content without rebuilding layout."""
        if not self._in_tmux:  # type: ignore[attr-defined]
            return
        active_pane = self._active_pane_id  # type: ignore[attr-defined]
        if not active_pane or not self._get_pane_exists(active_pane):  # type: ignore[attr-defined]
            logger.debug(
                "_update_active_pane: active pane missing or dead (%s), falling back to _render_layout",
                active_pane,
            )
            self._render_layout()
            return
        if active_pane == self._tui_pane_id:  # type: ignore[attr-defined]
            logger.error(
                "_update_active_pane: active_pane == tui_pane_id (%s), refusing to respawn TUI — rebuilding layout",
                self._tui_pane_id,  # type: ignore[attr-defined]
            )
            self.state.active_session_id = None  # type: ignore[attr-defined]
            self._render_layout()
            return

        logger.debug(
            "_update_active_pane: respawning pane %s with session %s (tmux=%s)",
            active_pane,
            active_spec.session_id,
            active_spec.tmux_session_name,
        )
        attach_cmd = self._build_pane_command(active_spec)
        self._run_tmux("respawn-pane", "-k", "-t", active_pane, attach_cmd)  # type: ignore[attr-defined]

        stale_ids = [sid for sid, pid in self.state.session_to_pane.items() if pid == active_pane]  # type: ignore[attr-defined]
        for sid in stale_ids:
            self.state.session_to_pane.pop(sid, None)  # type: ignore[attr-defined]
        self.state.session_to_pane[active_spec.session_id] = active_pane  # type: ignore[attr-defined]
        self.state.active_session_id = active_spec.session_id  # type: ignore[attr-defined]

        if active_spec.tmux_session_name:
            self._set_pane_background(  # type: ignore[attr-defined]
                active_pane,
                active_spec.tmux_session_name,
                active_spec.active_agent,
                is_tree_selected=self._is_tree_selected_session(active_spec.session_id),
            )
        else:
            self._set_doc_pane_background(active_pane, agent=active_spec.active_agent)  # type: ignore[attr-defined]

    def _layout_is_unchanged(self) -> bool:
        signature = self._compute_layout_signature()
        if signature is None:
            return False
        if signature == self._layout_signature:  # type: ignore[attr-defined]
            return True
        self._layout_signature = signature  # type: ignore[attr-defined]
        return False

    def _render_layout(self) -> None:
        """Render panes deterministically from the layout matrix."""
        if not self._in_tmux:  # type: ignore[attr-defined]
            return
        if not self._tui_pane_id:  # type: ignore[attr-defined]
            self._tui_pane_id = self._get_current_pane_id()  # type: ignore[attr-defined]
        if not self._tui_pane_id:  # type: ignore[attr-defined]
            logger.warning("_render_layout: missing TUI pane id")
            return

        session_specs = self._build_session_specs()
        logger.debug(
            "_render_layout: tui_pane=%s specs=%d sticky=%s active=%s",
            self._tui_pane_id,  # type: ignore[attr-defined]
            len(session_specs),
            [s.session_id for s in session_specs if s.is_sticky],
            next((s.session_id for s in session_specs if not s.is_sticky), None),
        )
        if len(session_specs) > 5:
            logger.warning("_render_layout: truncating session panes from %d to 5", len(session_specs))

        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            logger.warning("_render_layout: no layout for total=%d", total_panes)
            return

        self._cleanup_all_session_panes()  # type: ignore[attr-defined]

        def get_spec(index: int) -> SessionPaneSpec | None:
            if index <= 0 or index > len(session_specs):
                return None
            return session_specs[index - 1]

        col_top_panes: list[str | None] = [self._tui_pane_id] + [None] * (layout.cols - 1)  # type: ignore[attr-defined]

        for col in range(1, layout.cols):
            cell = layout.grid[0][col]
            if not isinstance(cell, int):
                continue
            spec = get_spec(cell)
            if not spec:
                continue
            attach_cmd = self._build_pane_command(spec)
            if col == 1:
                split_args = ["-t", self._tui_pane_id, "-h"]  # type: ignore[attr-defined]
                if layout.cols == 2 and total_panes <= 3:
                    split_args.extend(["-p", "60"])
                split_args.append("-d")
                pane_id = self._run_tmux(  # type: ignore[attr-defined]
                    "split-window",
                    *split_args,
                    "-P",
                    "-F",
                    "#{pane_id}",
                    attach_cmd,
                )
            else:
                pane_id = self._run_tmux(  # type: ignore[attr-defined]
                    "split-window",
                    "-t",
                    col_top_panes[col - 1] or "",
                    "-h",
                    "-d",
                    "-P",
                    "-F",
                    "#{pane_id}",
                    attach_cmd,
                )
            if pane_id:
                col_top_panes[col] = pane_id
                self._track_session_pane(spec, pane_id)

        if layout.cols == 3:
            self._run_tmux("select-layout", "even-horizontal")  # type: ignore[attr-defined]

        if layout.rows > 1:
            for col in range(layout.cols):
                cell = layout.grid[1][col]
                if not isinstance(cell, int):
                    continue
                spec = get_spec(cell)
                if not spec:
                    continue
                target_pane = col_top_panes[col]
                if not target_pane:
                    continue
                attach_cmd = self._build_pane_command(spec)
                pane_id = self._run_tmux(  # type: ignore[attr-defined]
                    "split-window",
                    "-t",
                    target_pane,
                    "-v",
                    "-d",
                    "-P",
                    "-F",
                    "#{pane_id}",
                    attach_cmd,
                )
                if pane_id:
                    self._track_session_pane(spec, pane_id)

        if self._active_spec:  # type: ignore[attr-defined]
            self.state.active_session_id = self._active_spec.session_id  # type: ignore[attr-defined]

        logger.debug(
            "_render_layout: done. active_pane=%s active_session=%s tracked=%s",
            self._active_pane_id,  # type: ignore[attr-defined]
            self.state.active_session_id,  # type: ignore[attr-defined]
            dict(self.state.session_to_pane),  # type: ignore[attr-defined]
        )
        self._layout_signature = self._compute_layout_signature()  # type: ignore[attr-defined]
        self._set_tui_pane_background()  # type: ignore[attr-defined]

    def _track_session_pane(self, spec: SessionPaneSpec, pane_id: str) -> None:
        """Track pane ids for lookup and cleanup."""
        logger.debug(
            "_track_session_pane: %s → %s (sticky=%s, tmux=%s)",
            spec.session_id,
            pane_id,
            spec.is_sticky,
            spec.tmux_session_name,
        )
        self.state.session_to_pane[spec.session_id] = pane_id  # type: ignore[attr-defined]

        # Apply explicit pane styling so panes never inherit stale colors.
        if spec.tmux_session_name:
            self._set_pane_background(  # type: ignore[attr-defined]
                pane_id,
                spec.tmux_session_name,
                spec.active_agent,
                is_tree_selected=self._is_tree_selected_session(spec.session_id),
            )
        else:
            self._set_doc_pane_background(pane_id, agent=spec.active_agent)  # type: ignore[attr-defined]

    def _is_tree_selected_session(self, session_id: str) -> bool:
        """Return True if this session row should get the lighter tree-selected haze."""
        return (
            self._tree_node_has_focus  # type: ignore[attr-defined]
            and self._selected_session_id is not None  # type: ignore[attr-defined]
            and session_id == self._selected_session_id  # type: ignore[attr-defined]
        )

    def _build_pane_command(self, spec: SessionPaneSpec) -> str:
        """Build the command used to populate a pane.

        Doc pane commands (glow/less) get NO_COLOR=1 prefix at peaceful
        levels (0, 1) to suppress CLI color output.
        """
        if spec.command:
            level = theme.get_pane_theming_mode_level()
            if level <= 1:
                return f"NO_COLOR=1 {spec.command}"
            return spec.command
        return self._build_attach_cmd(spec.tmux_session_name or "", spec.computer_info)  # type: ignore[attr-defined]
