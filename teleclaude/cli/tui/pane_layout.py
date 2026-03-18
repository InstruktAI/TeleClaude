"""PaneLayoutMixin — layout calculation, rendering, and background refresh."""

# The mixin intentionally manipulates private layout state on the host class.
# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui import theme
from teleclaude.cli.tui._pane_specs import LAYOUT_SPECS, SessionPaneSpec

if TYPE_CHECKING:
    from teleclaude.cli.tui._pane_specs import ComputerInfo, LayoutSpec
    from teleclaude.cli.tui.state import DocPreviewState

logger = get_logger(__name__)


@dataclass(frozen=True)
class LayoutRequest:
    """Resolved inputs for one pane-layout application."""

    active_session_id: str | None
    sticky_session_ids: list[str]
    get_computer_info: Callable[[str], ComputerInfo | None]
    active_doc_preview: DocPreviewState | None = None
    selected_session_id: str | None = None
    tree_node_has_focus: bool = False
    focus: bool = True


class PaneLayoutMixin:
    """Layout management methods for TmuxPaneManager."""

    def apply_layout(self, request: LayoutRequest | None = None, **legacy_kwargs: object) -> None:
        """Apply a deterministic layout from session ids."""
        if not self._in_tmux:  # type: ignore[attr-defined]
            return
        if request is None:
            request = LayoutRequest(**legacy_kwargs)

        self._reconcile()  # type: ignore[attr-defined]
        logger.debug(
            "apply_layout: active=%s sticky=%s doc_preview=%s focus=%s tui_pane=%s active_pane=%s",
            request.active_session_id if request.active_session_id else None,
            list(request.sticky_session_ids),
            request.active_doc_preview.doc_id if request.active_doc_preview else None,
            request.focus,
            self._tui_pane_id,  # type: ignore[attr-defined]
            self._active_pane_id,  # type: ignore[attr-defined]
        )

        self._selected_session_id = request.selected_session_id  # type: ignore[attr-defined]
        self._tree_node_has_focus = request.tree_node_has_focus  # type: ignore[attr-defined]

        active_spec = self._build_active_spec(request)
        self._sticky_specs = self._build_sticky_specs(  # type: ignore[attr-defined]
            request.sticky_session_ids,
            request.get_computer_info,
        )
        previous_active = self._active_spec  # type: ignore[attr-defined]
        prev_command = previous_active.command if previous_active else None
        self._active_spec = active_spec  # type: ignore[attr-defined]

        if self._layout_is_unchanged():
            logger.debug(
                "apply_layout: layout unchanged, active_spec=%s active_session=%s active_pane=%s",
                active_spec.session_id if active_spec else None,
                self.state.active_session_id if self.state.active_session_id else None,  # type: ignore[attr-defined]
                self._active_pane_id,  # type: ignore[attr-defined]
            )
            self._handle_unchanged_layout(active_spec, prev_command, request.focus)
            return

        logger.debug(
            "apply_layout: layout CHANGED, calling _render_layout (specs=%d)",
            len(self._build_session_specs()),
        )
        self._render_layout()
        self.invalidate_bg_cache()
        if request.focus and active_spec:
            self.focus_pane_for_session(active_spec.session_id)  # type: ignore[attr-defined]

    def _build_sticky_specs(
        self,
        sticky_session_ids: list[str],
        get_computer_info: Callable[[str], ComputerInfo | None],
    ) -> list[SessionPaneSpec]:
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
        return sticky_specs

    def _build_active_spec(self, request: LayoutRequest) -> SessionPaneSpec | None:
        if request.active_session_id:
            session = self._session_catalog.get(request.active_session_id)  # type: ignore[attr-defined]
            if session and session.tmux_session_name:
                return SessionPaneSpec(
                    session_id=session.session_id,
                    tmux_session_name=session.tmux_session_name,
                    computer_info=request.get_computer_info(session.computer or "local"),
                    is_sticky=False,
                    active_agent=session.active_agent or "",
                )
        elif request.active_doc_preview:
            return SessionPaneSpec(
                session_id=f"doc:{request.active_doc_preview.doc_id}",
                tmux_session_name=None,
                computer_info=None,
                is_sticky=False,
                active_agent="",
                command=request.active_doc_preview.command,
            )
        return None

    def _handle_unchanged_layout(
        self,
        active_spec: SessionPaneSpec | None,
        prev_command: str | None,
        focus: bool,
    ) -> None:
        if active_spec and self.state.active_session_id != active_spec.session_id:  # type: ignore[attr-defined]
            self._update_active_pane(active_spec)
        elif self._active_doc_command_changed(active_spec, prev_command):
            self._update_active_pane(active_spec)

        if focus and active_spec:
            self.focus_pane_for_session(active_spec.session_id)  # type: ignore[attr-defined]
        if not active_spec:
            self._clear_active_state_if_sticky()
        self._refresh_backgrounds_if_needed()

    def _active_doc_command_changed(
        self,
        active_spec: SessionPaneSpec | None,
        prev_command: str | None,
    ) -> bool:
        return bool(
            active_spec
            and active_spec.command
            and self.state.active_session_id == active_spec.session_id  # type: ignore[attr-defined]
            and active_spec.command != prev_command
        )

    def _refresh_backgrounds_if_needed(self) -> None:
        """Refresh pane backgrounds only when selection or agent state changed."""
        bg_signature = self._compute_bg_signature()
        if bg_signature == self._bg_signature:  # type: ignore[attr-defined]
            return
        self._bg_signature = bg_signature  # type: ignore[attr-defined]
        self._refresh_session_pane_backgrounds()
        self._set_tui_pane_background()  # type: ignore[attr-defined]

    def _build_session_specs(self) -> list[SessionPaneSpec]:
        session_specs: list[SessionPaneSpec] = list(self._sticky_specs)  # type: ignore[attr-defined]
        active_spec = self._active_spec  # type: ignore[attr-defined]
        if active_spec and not any(spec.session_id == active_spec.session_id for spec in session_specs):
            session_specs.append(active_spec)
        if len(session_specs) > 5:
            session_specs = session_specs[:5]
        return session_specs

    def _compute_layout_signature(self) -> tuple[object, ...] | None:
        session_specs = self._build_session_specs()
        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            return None
        structural_keys = tuple(spec.session_id if spec.is_sticky else "__active__" for spec in session_specs)
        return (
            layout.rows,
            layout.cols,
            tuple(tuple(row) for row in layout.grid),
            structural_keys,
        )

    def _compute_bg_signature(self) -> tuple[object, ...]:
        """Compute a signature for pane background state."""
        pane_agents = tuple(
            sorted(
                (pane_id, self._get_session_agent(session_id))
                for session_id, pane_id in self.state.session_to_pane.items()  # type: ignore[attr-defined]
            )
        )
        return (
            self._selected_session_id,  # type: ignore[attr-defined]
            self._tree_node_has_focus,  # type: ignore[attr-defined]
            theme.get_pane_theming_mode(),
            theme.get_current_mode(),
            pane_agents,
        )

    def _get_session_agent(self, session_id: str) -> str | None:
        session = self._session_catalog.get(session_id)  # type: ignore[attr-defined]
        return session.active_agent if session else None

    def invalidate_bg_cache(self) -> None:
        """Force background re-application on next apply_layout."""
        self._bg_signature = None  # type: ignore[attr-defined]

    def _clear_active_state_if_sticky(self) -> None:
        """Clear active_session_id when active has been promoted to sticky."""
        if not self.state.active_session_id:  # type: ignore[attr-defined]
            return
        active_session_id = self.state.active_session_id  # type: ignore[attr-defined]
        if any(
            spec.session_id == active_session_id for spec in self._sticky_specs
        ):  # type: ignore[attr-defined]
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
                "_update_active_pane: active_pane == tui_pane_id (%s), refusing to respawn TUI - rebuilding layout",
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

        stale_ids = [
            session_id
            for session_id, pane_id in self.state.session_to_pane.items()  # type: ignore[attr-defined]
            if pane_id == active_pane
        ]
        for session_id in stale_ids:
            self.state.session_to_pane.pop(session_id, None)  # type: ignore[attr-defined]
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
        if signature == self._layout_state.layout_signature:  # type: ignore[attr-defined]
            return True
        self._layout_state.layout_signature = signature  # type: ignore[attr-defined]
        return False

    def _render_layout(self) -> None:
        """Render panes deterministically from the layout matrix."""
        if not self._prepare_tui_pane():
            return

        session_specs = self._build_session_specs()
        logger.debug(
            "_render_layout: tui_pane=%s specs=%d sticky=%s active=%s",
            self._tui_pane_id,  # type: ignore[attr-defined]
            len(session_specs),
            [spec.session_id for spec in session_specs if spec.is_sticky],
            next((spec.session_id for spec in session_specs if not spec.is_sticky), None),
        )
        if len(session_specs) > 5:
            logger.warning("_render_layout: truncating session panes from %d to 5", len(session_specs))

        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            logger.warning("_render_layout: no layout for total=%d", total_panes)
            return

        self._cleanup_all_session_panes()  # type: ignore[attr-defined]
        col_top_panes = self._render_top_row(layout, session_specs, total_panes)
        self._normalize_layout_columns(layout)
        self._render_bottom_row(layout, session_specs, col_top_panes)
        self._finalize_layout_render()

    def _prepare_tui_pane(self) -> bool:
        if not self._in_tmux:  # type: ignore[attr-defined]
            return False
        if not self._tui_pane_id:  # type: ignore[attr-defined]
            self._tui_pane_id = self._get_current_pane_id()  # type: ignore[attr-defined]
        if self._tui_pane_id:  # type: ignore[attr-defined]
            return True
        logger.warning("_render_layout: missing TUI pane id")
        return False

    def _get_layout_spec(
        self,
        session_specs: list[SessionPaneSpec],
        index: int,
    ) -> SessionPaneSpec | None:
        if index <= 0 or index > len(session_specs):
            return None
        return session_specs[index - 1]

    def _render_top_row(
        self,
        layout: LayoutSpec,
        session_specs: list[SessionPaneSpec],
        total_panes: int,
    ) -> list[str | None]:
        col_top_panes: list[str | None] = [self._tui_pane_id] + [None] * (layout.cols - 1)  # type: ignore[attr-defined]
        for col in range(1, layout.cols):
            spec = self._get_layout_spec(session_specs, layout.grid[0][col])
            if not spec:
                continue
            split_target, split_args = self._top_row_split_request(layout, col, col_top_panes, total_panes)
            pane_id = self._split_top_row_pane(spec, split_target, split_args)
            if pane_id:
                col_top_panes[col] = pane_id
                self._track_session_pane(spec, pane_id)
        return col_top_panes

    def _top_row_split_request(
        self,
        layout: LayoutSpec,
        col: int,
        col_top_panes: list[str | None],
        total_panes: int,
    ) -> tuple[str, list[str]]:
        if col == 1:
            split_args = ["-h"]
            if layout.cols == 2 and total_panes <= 3:
                split_args.extend(["-p", "60"])
            split_args.append("-d")
            return self._tui_pane_id or "", split_args  # type: ignore[attr-defined]
        return col_top_panes[col - 1] or "", ["-h", "-d"]

    def _split_top_row_pane(
        self,
        spec: SessionPaneSpec,
        split_target: str,
        split_args: list[str],
    ) -> str | None:
        attach_cmd = self._build_pane_command(spec)
        return self._run_tmux(  # type: ignore[attr-defined]
            "split-window",
            "-t",
            split_target,
            *split_args,
            "-P",
            "-F",
            "#{pane_id}",
            attach_cmd,
        )

    def _normalize_layout_columns(self, layout: LayoutSpec) -> None:
        if layout.cols == 3:
            self._run_tmux("select-layout", "even-horizontal")  # type: ignore[attr-defined]

    def _render_bottom_row(
        self,
        layout: LayoutSpec,
        session_specs: list[SessionPaneSpec],
        col_top_panes: list[str | None],
    ) -> None:
        if layout.rows <= 1:
            return
        for col in range(layout.cols):
            spec = self._get_layout_spec(session_specs, layout.grid[1][col])
            target_pane = col_top_panes[col]
            if not spec or not target_pane:
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

    def _finalize_layout_render(self) -> None:
        active_spec = self._layout_state.active_spec  # type: ignore[attr-defined]
        if active_spec:
            self.state.active_session_id = active_spec.session_id  # type: ignore[attr-defined]
        logger.debug(
            "_render_layout: done. active_pane=%s active_session=%s tracked=%s",
            self._active_pane_id,  # type: ignore[attr-defined]
            self.state.active_session_id,  # type: ignore[attr-defined]
            dict(self.state.session_to_pane),  # type: ignore[attr-defined]
        )
        self._layout_state.layout_signature = self._compute_layout_signature()  # type: ignore[attr-defined]
        self._set_tui_pane_background()  # type: ignore[attr-defined]

    def _track_session_pane(self, spec: SessionPaneSpec, pane_id: str) -> None:
        """Track pane ids for lookup and cleanup."""
        logger.debug(
            "_track_session_pane: %s -> %s (sticky=%s, tmux=%s)",
            spec.session_id,
            pane_id,
            spec.is_sticky,
            spec.tmux_session_name,
        )
        self.state.session_to_pane[spec.session_id] = pane_id  # type: ignore[attr-defined]

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
            self._layout_state.tree_node_has_focus  # type: ignore[attr-defined]
            and self._layout_state.selected_session_id is not None  # type: ignore[attr-defined]
            and session_id == self._layout_state.selected_session_id  # type: ignore[attr-defined]
        )

    def _build_pane_command(self, spec: SessionPaneSpec) -> str:
        """Build the command used to populate a pane."""
        if spec.command:
            level = theme.get_pane_theming_mode_level()
            if level <= 1:
                return f"NO_COLOR=1 {spec.command}"
            return spec.command
        return self._build_attach_cmd(  # type: ignore[attr-defined]
            spec.tmux_session_name or "",
            spec.computer_info,
        )
