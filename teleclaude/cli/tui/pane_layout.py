"""PaneLayoutMixin — layout calculation, rendering, and background refresh."""

# The mixin intentionally manipulates private layout state on the host class.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui import theme
from teleclaude.cli.tui._pane_specs import LAYOUT_SPECS, LayoutCell, SessionPaneSpec
from teleclaude.cli.tui.layout_model import CellOp, desired, diff_cells, orphan_panes

if TYPE_CHECKING:
    from teleclaude.cli.tui._pane_specs import ComputerInfo, LayoutSpec
    from teleclaude.cli.tui.types import DocPreviewState

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
        """Apply a deterministic layout from session ids.

        A relayout (split/kill panes) happens only when the tier (pane count)
        changes. Same-tier transitions swap the content of just the cells whose
        assigned session changed, leaving every stable pane untouched. Genuine
        orphans (live non-TUI panes absent from the layout) are reaped at entry.
        """
        if not self._in_tmux:  # type: ignore[attr-defined]
            return
        if request is None:
            request = LayoutRequest(**legacy_kwargs)

        self._reconcile()  # type: ignore[attr-defined]
        self._reap_orphans()
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
        self._active_spec = active_spec  # type: ignore[attr-defined]

        cell_specs = self._build_session_specs()
        new_tier = 1 + len(cell_specs)
        if new_tier not in LAYOUT_SPECS:
            logger.warning("apply_layout: no layout for tier=%d", new_tier)
            return

        prev_cells = self._layout_state.cell_specs  # type: ignore[attr-defined]
        same_tier = prev_cells is not None and len(prev_cells) == len(cell_specs)
        if same_tier and self._swap_changed_cells(prev_cells, cell_specs):
            self._layout_state.cell_specs = cell_specs  # type: ignore[attr-defined]
            self._layout_state.layout_signature = self._compute_layout_signature()  # type: ignore[attr-defined]
            self._refresh_backgrounds_if_needed()
            if request.focus and active_spec:
                self.focus_pane_for_session(active_spec.session_id)  # type: ignore[attr-defined]
            return

        logger.debug("apply_layout: tier changed -> minimal reflow (specs=%d)", len(cell_specs))
        self._reflow_layout(prev_cells, cell_specs)
        self._layout_state.cell_specs = cell_specs  # type: ignore[attr-defined]
        self.invalidate_bg_cache()
        if request.focus and active_spec:
            self.focus_pane_for_session(active_spec.session_id)  # type: ignore[attr-defined]

    def _reap_orphans(self) -> None:
        """Kill live non-TUI panes that no tracked session maps to.

        A relayout or a crashed process can leave a live pane that nothing
        tracks; ``select-layout`` and grid splits would otherwise count it as an
        extra column. Stable, tracked panes are never touched here.
        """
        if not self._tui_pane_id:  # type: ignore[attr-defined]
            return
        output = self._run_tmux("list-panes", "-F", "#{pane_id}")  # type: ignore[attr-defined]
        live = {pane.strip() for pane in output.split("\n") if pane.strip()}
        tracked = set(self.state.session_to_pane.values())  # type: ignore[attr-defined]
        for pane in orphan_panes(live, self._tui_pane_id, tracked):  # type: ignore[attr-defined]
            self._run_tmux("kill-pane", "-t", pane)  # type: ignore[attr-defined]
            logger.debug("_reap_orphans: killed untracked pane %s", pane)

    def _cell_fingerprint(self, spec: SessionPaneSpec) -> str:
        """Identity of a cell's content: session plus any doc command."""
        return f"{spec.session_id}\x00{spec.command or ''}"

    def _swap_changed_cells(
        self,
        prev_cells: list[SessionPaneSpec],
        new_cells: list[SessionPaneSpec],
    ) -> bool:
        """Respawn only the cells whose content changed (same-tier transition).

        Returns ``False`` to request a full reflow when a target pane is missing
        or dead, so the caller falls back to ``_render_layout``.
        """
        diff = diff_cells(
            [self._cell_fingerprint(spec) for spec in prev_cells],
            [self._cell_fingerprint(spec) for spec in new_cells],
        )
        if diff.tier_changed:
            return False
        for cell in diff.cells:
            prev_spec = prev_cells[cell.index - 1]
            pane = self._existing_cell_pane(prev_spec)
            if pane is None:
                return False
            if cell.op is CellOp.KEEP:
                continue
            new_spec = new_cells[cell.index - 1]
            self._respawn_cell(pane, prev_spec, new_spec)
        self.state.active_session_id = next(  # type: ignore[attr-defined]
            (spec.session_id for spec in new_cells if not spec.is_sticky), None
        )
        return True

    def _existing_cell_pane(self, spec: SessionPaneSpec) -> str | None:
        """Return the live pane for an existing cell, or request a reflow."""
        pane = self.state.session_to_pane.get(spec.session_id)  # type: ignore[attr-defined]
        if pane and pane != self._tui_pane_id and self._get_pane_exists(pane):  # type: ignore[attr-defined]
            return pane
        logger.debug(
            "_swap_changed_cells: missing live pane for %s (pane=%s); reflowing",
            spec.session_id,
            pane,
        )
        return None

    def _respawn_cell(
        self,
        pane: str,
        prev_spec: SessionPaneSpec,
        new_spec: SessionPaneSpec,
    ) -> None:
        """Swap one pane's content in place without rebuilding the grid."""
        attach_cmd = self._build_pane_command(new_spec)
        self._run_tmux("respawn-pane", "-k", "-t", pane, attach_cmd)  # type: ignore[attr-defined]
        self.state.session_to_pane.pop(prev_spec.session_id, None)  # type: ignore[attr-defined]
        self.state.session_to_pane[new_spec.session_id] = pane  # type: ignore[attr-defined]
        if new_spec.tmux_session_name:
            self._set_pane_background(  # type: ignore[attr-defined]
                pane,
                new_spec.tmux_session_name,
                new_spec.active_agent,
                is_tree_selected=self._is_tree_selected_session(new_spec.session_id),
            )
        else:
            self._set_doc_pane_background(pane, agent=new_spec.active_agent)  # type: ignore[attr-defined]

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

    def _refresh_backgrounds_if_needed(self) -> None:
        """Refresh pane backgrounds only when selection or agent state changed."""
        bg_signature = self._compute_bg_signature()
        if bg_signature == self._bg_signature:  # type: ignore[attr-defined]
            return
        self._bg_signature = bg_signature  # type: ignore[attr-defined]
        self._refresh_session_pane_backgrounds()
        self._set_tui_pane_background()  # type: ignore[attr-defined]

    def _build_session_specs(self) -> list[SessionPaneSpec]:
        """Ordered cell specs derived from ``desired()`` (incl. the borrow rule).

        ``desired()`` already bounds the result to ``MAX_STICKY`` sessions, so no
        truncation is needed here. Sticky specs win on id collision so a preview
        that equals a sticky never displaces the sticky cell.
        """
        sticky_specs = list(self._sticky_specs)  # type: ignore[attr-defined]
        active_spec = self._active_spec  # type: ignore[attr-defined]
        by_id: dict[str, SessionPaneSpec] = {}
        if active_spec is not None:
            by_id[active_spec.session_id] = active_spec
        for spec in sticky_specs:
            by_id[spec.session_id] = spec
        ordered = desired(
            [spec.session_id for spec in sticky_specs],
            active_spec.session_id if active_spec else None,
        )
        return [by_id[session_id] for session_id in ordered if session_id in by_id]

    def _compute_layout_signature(self) -> tuple[object, ...] | None:
        session_specs = self._build_session_specs()
        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            return None
        structural_keys = tuple((spec.session_id, spec.command) for spec in session_specs)
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

        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            logger.warning("_render_layout: no layout for total=%d", total_panes)
            return

        self._cleanup_all_session_panes()  # type: ignore[attr-defined]
        col_top_panes = self._render_top_row(layout, session_specs, total_panes)
        self._render_bottom_row(layout, session_specs, col_top_panes)
        self._finalize_layout_render()

    def _reflow_layout(
        self,
        prev_cells: list[SessionPaneSpec] | None,
        session_specs: list[SessionPaneSpec],
    ) -> None:
        """Apply a tier-change delta while preserving surviving session panes."""
        if prev_cells is None:
            self._render_layout()
            return
        if not self._prepare_tui_pane():
            return

        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            logger.warning("_reflow_layout: no layout for total=%d", total_panes)
            return

        prev_total = 1 + len(prev_cells)
        if self._can_transition_four_to_five(prev_cells, session_specs):
            self._transition_four_to_five(prev_cells, session_specs)
        elif self._can_transition_five_to_four(prev_cells, session_specs):
            self._transition_five_to_four(prev_cells, session_specs)
        else:
            self._kill_removed_cells(prev_cells, session_specs)
            self._render_existing_aware_layout(layout, session_specs, total_panes)

        logger.debug(
            "_reflow_layout: done. previous_total=%d total=%d tracked=%s",
            prev_total,
            total_panes,
            dict(self.state.session_to_pane),  # type: ignore[attr-defined]
        )
        self._finalize_layout_render()

    def _can_transition_four_to_five(
        self,
        prev_cells: list[SessionPaneSpec],
        session_specs: list[SessionPaneSpec],
    ) -> bool:
        prev_ids = [spec.session_id for spec in prev_cells]
        new_ids = [spec.session_id for spec in session_specs]
        return len(prev_ids) == 3 and len(new_ids) == 4 and prev_ids == new_ids[:3]

    def _can_transition_five_to_four(
        self,
        prev_cells: list[SessionPaneSpec],
        session_specs: list[SessionPaneSpec],
    ) -> bool:
        prev_ids = [spec.session_id for spec in prev_cells]
        new_ids = [spec.session_id for spec in session_specs]
        return len(prev_ids) == 4 and len(new_ids) == 3 and prev_ids[:3] == new_ids

    def _transition_four_to_five(
        self,
        prev_cells: list[SessionPaneSpec],
        session_specs: list[SessionPaneSpec],
    ) -> None:
        panes = self._require_transition_panes(prev_cells)
        if panes is None:
            self._kill_removed_cells(prev_cells, session_specs)
            self._render_existing_aware_layout(LAYOUT_SPECS[5], session_specs, 5)
            return

        first, second, third = panes
        temp = self._run_tmux(  # type: ignore[attr-defined]
            "split-window",
            "-t",
            first,
            "-h",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
        )
        self._run_tmux("swap-pane", "-s", second, "-t", temp)  # type: ignore[attr-defined]
        self._run_tmux("swap-pane", "-s", third, "-t", temp)  # type: ignore[attr-defined]
        self._run_tmux("kill-pane", "-t", temp)  # type: ignore[attr-defined]

        added_spec = session_specs[3]
        attach_cmd = self._build_pane_command(added_spec)
        added_pane = self._run_tmux(  # type: ignore[attr-defined]
            "split-window",
            "-t",
            third,
            "-h",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
            attach_cmd,
        )
        self._run_tmux("swap-pane", "-s", third, "-t", added_pane)  # type: ignore[attr-defined]
        self._track_session_pane(added_spec, added_pane)
        self._sync_surviving_cell_content(prev_cells, session_specs)

    def _transition_five_to_four(
        self,
        prev_cells: list[SessionPaneSpec],
        session_specs: list[SessionPaneSpec],
    ) -> None:
        panes = self._require_transition_panes(prev_cells[:3])
        if panes is None:
            self._kill_removed_cells(prev_cells, session_specs)
            self._render_existing_aware_layout(LAYOUT_SPECS[4], session_specs, 4)
            return

        first, second, third = panes
        removed_id = prev_cells[3].session_id
        removed_pane = self.state.session_to_pane.pop(removed_id, None)  # type: ignore[attr-defined]
        if removed_pane and self._get_pane_exists(removed_pane):  # type: ignore[attr-defined]
            self._run_tmux("kill-pane", "-t", removed_pane)  # type: ignore[attr-defined]

        temp = self._run_tmux(  # type: ignore[attr-defined]
            "split-window",
            "-t",
            self._tui_pane_id,  # type: ignore[attr-defined]
            "-v",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
        )
        self._run_tmux("swap-pane", "-s", third, "-t", temp)  # type: ignore[attr-defined]
        self._run_tmux("kill-pane", "-t", temp)  # type: ignore[attr-defined]
        self._run_tmux("join-pane", "-s", second, "-t", first, "-v", "-d")  # type: ignore[attr-defined]
        self._sync_surviving_cell_content(prev_cells, session_specs)

    def _require_transition_panes(self, specs: list[SessionPaneSpec]) -> tuple[str, str, str] | None:
        panes = [self._existing_cell_pane(spec) for spec in specs]
        first, second, third = panes
        if first is None or second is None or third is None:
            return None
        return first, second, third

    def _kill_removed_cells(
        self,
        prev_cells: list[SessionPaneSpec],
        session_specs: list[SessionPaneSpec],
    ) -> None:
        desired_ids = {spec.session_id for spec in session_specs}
        for spec in prev_cells:
            if spec.session_id in desired_ids:
                continue
            pane = self.state.session_to_pane.pop(spec.session_id, None)  # type: ignore[attr-defined]
            if pane and self._get_pane_exists(pane):  # type: ignore[attr-defined]
                self._run_tmux("kill-pane", "-t", pane)  # type: ignore[attr-defined]

    def _render_existing_aware_layout(
        self,
        layout: LayoutSpec,
        session_specs: list[SessionPaneSpec],
        total_panes: int,
    ) -> None:
        col_top_panes = self._render_existing_aware_top_row(layout, session_specs, total_panes)
        self._render_existing_aware_bottom_row(layout, session_specs, col_top_panes)
        self._sync_surviving_cell_content(self._layout_state.cell_specs or [], session_specs)  # type: ignore[attr-defined]

    def _render_existing_aware_top_row(
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
            existing = self._existing_cell_pane(spec)
            if existing:
                col_top_panes[col] = existing
                continue
            split_target, split_args = self._top_row_split_request(layout, col, col_top_panes, total_panes)
            pane_id = self._split_top_row_pane(spec, split_target, split_args)
            if pane_id:
                col_top_panes[col] = pane_id
                self._track_session_pane(spec, pane_id)
        return col_top_panes

    def _render_existing_aware_bottom_row(
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
            if self._existing_cell_pane(spec):
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

    def _sync_surviving_cell_content(
        self,
        prev_cells: list[SessionPaneSpec],
        session_specs: list[SessionPaneSpec],
    ) -> None:
        prev_by_id = {spec.session_id: spec for spec in prev_cells}
        for spec in session_specs:
            prev_spec = prev_by_id.get(spec.session_id)
            if not prev_spec or self._cell_fingerprint(prev_spec) == self._cell_fingerprint(spec):
                continue
            pane = self._existing_cell_pane(prev_spec)
            if pane:
                self._respawn_cell(pane, prev_spec, spec)

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
        index: LayoutCell,
    ) -> SessionPaneSpec | None:
        if not isinstance(index, int) or index <= 0 or index > len(session_specs):
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
            elif layout.cols == 3:
                # Give the two right-hand session columns ~66% so explicit widths
                # bound the column count, instead of select-layout which would
                # count any stray live pane as an extra column.
                split_args.extend(["-p", "66"])
            split_args.append("-d")
            return self._tui_pane_id or "", split_args  # type: ignore[attr-defined]
        extra = ["-p", "50"] if layout.cols == 3 else []
        return col_top_panes[col - 1] or "", ["-h", *extra, "-d"]

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
