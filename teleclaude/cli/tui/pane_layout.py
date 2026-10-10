"""PaneLayoutMixin — layout calculation, rendering, and background refresh."""

# The mixin intentionally manipulates private layout state on the host class.

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui import theme
from teleclaude.cli.tui._pane_specs import LAYOUT_SPECS, LayoutCell, SessionPaneSpec
from teleclaude.cli.tui.artifact_panes import DOC_PANE_PREFIX, doc_pane_key
from teleclaude.cli.tui.layout_model import CellOp, desired, diff_cells, orphan_panes
from teleclaude.core.session_status import HostPaneViewerAdmission

if TYPE_CHECKING:
    from teleclaude.api_models import SessionDTO
    from teleclaude.cli.tui._pane_specs import LayoutSpec, PaneGeometry
    from teleclaude.cli.tui.types import DocPreviewState

logger = get_logger(__name__)
_PANE_ID_FORMAT = "#{pane_id}"
_PANE_PERCENT_SIZE = "{size}%"
_CELL_FINGERPRINT_SEPARATOR = "\x00"
_UNRESOLVED_ATTACHMENT_FINGERPRINT = "unresolved"


class _PaneCommand(StrEnum):
    BREAK = "break-pane"
    JOIN = "join-pane"
    KILL = "kill-pane"
    DISPLAY = "display-message"
    SELECT = "select-pane"
    LIST = "list-panes"


class _PaneFlag(StrEnum):
    SOURCE = "-s"
    TARGET = "-t"
    DETACHED = "-d"
    PRINT = "-p"
    SIZE = "-l"
    VERTICAL = "-v"
    FORMAT = "-F"
    ALL = "-a"


@dataclass(frozen=True)
class LayoutRequest:
    """Resolved inputs for one pane-layout application."""

    active_session_id: str | None
    sticky_session_ids: list[str]
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
        )
        self._active_spec = active_spec  # type: ignore[attr-defined]

        cell_specs = self._build_session_specs()
        new_tier = 1 + len(cell_specs)
        if new_tier not in LAYOUT_SPECS:
            logger.warning("apply_layout: no layout for tier=%d", new_tier)
            return

        recovered = self._recover_rendered_cells(cell_specs)
        prev_cells = self._layout_state.cell_specs  # type: ignore[attr-defined]
        if not recovered and prev_cells is not None and len(prev_cells) == len(cell_specs):
            swapped = self._swap_changed_cells(prev_cells, cell_specs)
            if swapped is not None:
                # Commit structural state before cosmetic theming: a theming
                # failure must never leave session_to_pane inconsistent with
                # cell_specs (the split-brain that duplicates the preview pane).
                self._layout_state.cell_specs = cell_specs  # type: ignore[attr-defined]
                self._layout_state.layout_signature = self._compute_layout_signature()  # type: ignore[attr-defined]
                self._restore_layout_geometry(cell_specs)
                for pane, new_spec in swapped:
                    self._theme_swapped_pane(pane, new_spec)
                self._refresh_backgrounds_if_needed()
                if request.focus and active_spec:
                    self.focus_pane_for_session(active_spec.session_id)  # type: ignore[attr-defined]
                return

        logger.debug("apply_layout: tier changed -> minimal reflow (specs=%d)", len(cell_specs))
        self._reflow_layout(prev_cells, cell_specs)
        self._layout_state.cell_specs = cell_specs  # type: ignore[attr-defined]
        self._restore_layout_geometry(cell_specs)
        self.invalidate_bg_cache()
        if request.focus and active_spec:
            self.focus_pane_for_session(active_spec.session_id)  # type: ignore[attr-defined]

    def _recover_rendered_cells(self, desired_specs: list[SessionPaneSpec]) -> bool:
        """Reconcile resolved survivors absent from the observed cell assignment."""
        previous = list(self._layout_state.cell_specs or [])  # type: ignore[attr-defined]
        previous_ids = {spec.session_id for spec in previous}
        previous_by_id = {spec.session_id: spec for spec in previous}
        desired_by_id = {spec.session_id: spec for spec in desired_specs}
        recovered = False
        geometry_changed = False
        for session_id, pane in list(self.state.session_to_pane.items()):  # type: ignore[attr-defined]
            if session_id in previous_ids:
                continue
            spec = desired_by_id.get(session_id)
            if spec is not None:
                previous_by_id[session_id] = self._layout_state.observed_specs.get(session_id, spec)  # type: ignore[attr-defined]
                recovered = True
            else:
                self._run_tmux(_PaneCommand.KILL, _PaneFlag.TARGET, pane)  # type: ignore[attr-defined]
                self.state.session_to_pane.pop(session_id)  # type: ignore[attr-defined]
                self._layout_state.observed_specs.pop(session_id, None)  # type: ignore[attr-defined]
                self._layout_state.observed_geometry.pop(pane, None)  # type: ignore[attr-defined]
                self._layout_state.detached_panes.discard(pane)  # type: ignore[attr-defined]
                recovered = True
                geometry_changed = True
        if recovered:
            self._layout_state.cell_specs = [  # type: ignore[attr-defined]
                previous_by_id[spec.session_id]
                for spec in desired_specs
                if spec.session_id in previous_by_id and spec.session_id in self.state.session_to_pane  # type: ignore[attr-defined]
            ]
        if self._layout_state.reload_observation_pending:  # type: ignore[attr-defined]
            if geometry_changed:
                self._layout_state.observed_geometry = self._capture_pane_geometries()  # type: ignore[attr-defined]
            geometry_matches = self._observed_grid_matches(desired_specs)
            self._layout_state.geometry_dirty = geometry_matches is False  # type: ignore[attr-defined]
            self._layout_state.reload_observation_pending = False  # type: ignore[attr-defined]
        elif recovered:
            self._layout_state.geometry_dirty = True  # type: ignore[attr-defined]
        return recovered

    def _observed_grid_matches(self, specs: list[SessionPaneSpec]) -> bool | None:
        """Compare mapped pane positions with the declared cell topology."""
        layout = LAYOUT_SPECS.get(1 + len(specs))
        if layout is None:
            return False
        geometry_by_pane = self._layout_state.observed_geometry  # type: ignore[attr-defined]
        tui_pane = self._tui_pane_id  # type: ignore[attr-defined]
        tui_geometry = geometry_by_pane.get(tui_pane) if tui_pane is not None else None
        if tui_geometry is None:
            return False

        observed_cells: list[tuple[int, int, PaneGeometry]] = [(0, 0, tui_geometry)]
        missing = False
        for row_index, row in enumerate(layout.grid):
            for column_index, cell in enumerate(row):
                if not isinstance(cell, int):
                    continue
                spec = specs[cell - 1]
                pane_id = self.state.session_to_pane.get(spec.session_id)  # type: ignore[attr-defined]
                if pane_id is None:
                    missing = True
                    continue
                geometry = geometry_by_pane.get(pane_id)
                if geometry is None:
                    return False
                observed_cells.append((row_index, column_index, geometry))

        left_positions = sorted({geometry.left for geometry in geometry_by_pane.values()})
        top_positions = sorted({geometry.top for geometry in geometry_by_pane.values()})
        for row_index, column_index, geometry in observed_cells:
            if left_positions.index(geometry.left) != column_index or top_positions.index(geometry.top) != row_index:
                return False

        repeated_tui = sum(cell == "T" for row in layout.grid for cell in row) > 1
        dimension_cells = observed_cells[1:] if repeated_tui else observed_cells
        for row_index in range(layout.rows):
            row_cells = [geometry for row, _column, geometry in dimension_cells if row == row_index]
            if row_cells and any(geometry.height != row_cells[0].height for geometry in row_cells[1:]):
                return False
        for column_index in range(layout.cols):
            column_cells = [geometry for _row, column, geometry in dimension_cells if column == column_index]
            if column_cells and any(geometry.width != column_cells[0].width for geometry in column_cells[1:]):
                return False
        return None if missing else True

    def _restore_layout_geometry(self, specs: list[SessionPaneSpec]) -> None:
        """Place known surviving viewers in the declared grid without respawning."""
        if not self._layout_state.geometry_dirty or self._protected_panes:  # type: ignore[attr-defined]
            return
        panes = {spec.session_id: self.state.session_to_pane.get(spec.session_id) for spec in specs}  # type: ignore[attr-defined]
        if any(pane is None or not self._get_pane_exists(pane) for pane in panes.values()):  # type: ignore[attr-defined]
            return
        if self._layout_state.recovery_focus is None:  # type: ignore[attr-defined]
            self._layout_state.recovery_focus = self._run_tmux(  # type: ignore[attr-defined]
                _PaneCommand.DISPLAY, _PaneFlag.PRINT, _PANE_ID_FORMAT
            )
        focused = self._layout_state.recovery_focus  # type: ignore[attr-defined]
        for pane in panes.values():
            if pane is not None and pane not in self._layout_state.detached_panes:  # type: ignore[attr-defined]
                self._run_tmux(_PaneCommand.BREAK, _PaneFlag.SOURCE, pane, _PaneFlag.DETACHED)  # type: ignore[attr-defined]
                self._layout_state.detached_panes.add(pane)  # type: ignore[attr-defined]
        layout = LAYOUT_SPECS[1 + len(specs)]
        tops: list[str | None] = [self._tui_pane_id] + [None] * (layout.cols - 1)  # type: ignore[attr-defined]
        for col in range(1, layout.cols):
            spec = self._get_layout_spec(specs, layout.grid[0][col])
            if spec is None:
                continue
            pane = panes[spec.session_id]
            if pane is not None:
                target, args = self._top_row_split_request(layout, col, tops, 1 + len(specs))
                self._join_existing_pane(pane, target, args)
                tops[col] = pane
        if layout.rows > 1:
            for col, target in enumerate(tops):
                spec = self._get_layout_spec(specs, layout.grid[1][col])
                if spec is not None and target is not None:
                    pane = panes[spec.session_id]
                    if pane is not None:
                        self._join_existing_pane(pane, target, [_PaneFlag.VERTICAL, _PaneFlag.DETACHED])
        self._layout_state.geometry_dirty = False  # type: ignore[attr-defined]
        if focused == self._tui_pane_id or focused in panes.values():  # type: ignore[attr-defined]
            self._run_tmux(_PaneCommand.SELECT, _PaneFlag.TARGET, focused)  # type: ignore[attr-defined]
        self._layout_state.recovery_focus = None  # type: ignore[attr-defined]

    def _join_existing_pane(self, pane: str, target: str, split_args: list[str]) -> None:
        """Move a surviving pane using the grid's split dimensions."""
        args = list(split_args)
        if _PaneFlag.PRINT in args:
            index = args.index(_PaneFlag.PRINT)
            args[index : index + 2] = [_PaneFlag.SIZE, _PANE_PERCENT_SIZE.format(size=args[index + 1])]
        self._run_tmux(_PaneCommand.JOIN, _PaneFlag.SOURCE, pane, _PaneFlag.TARGET, target, *args)  # type: ignore[attr-defined]
        self._layout_state.detached_panes.discard(pane)  # type: ignore[attr-defined]

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
        # A protected pane survived a reload without resolving to an owner. It
        # is not an orphan — it is a pane whose owner is not known yet — so it
        # is kept until it resolves or the process ends.
        tracked = set(self.state.session_to_pane.values()) | self._protected_panes  # type: ignore[attr-defined]
        for pane in orphan_panes(live, self._tui_pane_id, tracked):  # type: ignore[attr-defined]
            self._run_tmux("kill-pane", "-t", pane)  # type: ignore[attr-defined]
            logger.debug("_reap_orphans: killed untracked pane %s", pane)

    def _cell_fingerprint(self, spec: SessionPaneSpec) -> str:
        """Identity of a cell's content: owner, command, and observed target."""
        destination = (
            spec.attachment_destination.model_dump_json(exclude_none=True)
            if spec.attachment_destination is not None
            else _UNRESOLVED_ATTACHMENT_FINGERPRINT
        )
        return _CELL_FINGERPRINT_SEPARATOR.join((spec.session_id, spec.command or "", destination))

    def _swap_changed_cells(
        self,
        prev_cells: list[SessionPaneSpec],
        new_cells: list[SessionPaneSpec],
    ) -> list[tuple[str, SessionPaneSpec]] | None:
        """Respawn only the cells whose content changed (same-tier transition).

        Returns ``None`` to request a full reflow when a target pane is missing
        or dead, so the caller falls back to ``_render_layout``. Otherwise
        returns the ``(pane, new_spec)`` pairs that were respawned so the caller
        applies pane theming only after the structural swap has been committed.
        """
        diff = diff_cells(
            [self._cell_fingerprint(spec) for spec in prev_cells],
            [self._cell_fingerprint(spec) for spec in new_cells],
        )
        if diff.tier_changed:
            return None
        swapped: list[tuple[str, SessionPaneSpec]] = []
        for cell in diff.cells:
            prev_spec = prev_cells[cell.index - 1]
            pane = self._existing_cell_pane(prev_spec)
            if pane is None:
                return None
            if cell.op is CellOp.KEEP:
                continue
            new_spec = new_cells[cell.index - 1]
            self._respawn_cell(pane, prev_spec, new_spec)
            swapped.append((pane, new_spec))
        self.state.active_session_id = next(  # type: ignore[attr-defined]
            (spec.session_id for spec in new_cells if not spec.is_sticky), None
        )
        return swapped

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
        """Swap one pane's content in place without rebuilding the grid.

        Performs only the structural swap — the ``respawn-pane`` and the
        ``session_to_pane`` remap. Cosmetic pane theming is applied by the
        caller after the structural state (``session_to_pane`` and
        ``cell_specs``) is committed, so a theming failure cannot unwind a
        half-committed pane map.
        """
        attach_cmd = self._build_pane_command(new_spec)
        self._run_tmux("respawn-pane", "-k", "-t", pane, attach_cmd)  # type: ignore[attr-defined]
        self.state.session_to_pane.pop(prev_spec.session_id, None)  # type: ignore[attr-defined]
        self._layout_state.observed_specs.pop(prev_spec.session_id, None)  # type: ignore[attr-defined]
        self.state.session_to_pane[new_spec.session_id] = pane  # type: ignore[attr-defined]
        self._layout_state.observed_specs[new_spec.session_id] = new_spec  # type: ignore[attr-defined]

    def _theme_swapped_pane(self, pane: str, new_spec: SessionPaneSpec) -> None:
        """Apply pane theming for a cell swapped in place, after the commit."""
        if new_spec.tmux_session_name:
            self._set_pane_background(  # type: ignore[attr-defined]
                pane,
                new_spec.tmux_session_name,
                new_spec.active_agent,
                is_tree_selected=self._is_tree_selected_session(new_spec.session_id),
                is_remote=self._spec_is_remote(new_spec),  # type: ignore[attr-defined]
            )
        else:
            self._set_doc_pane_background(pane, agent=new_spec.active_agent)  # type: ignore[attr-defined]

    def _build_sticky_specs(
        self,
        sticky_session_ids: list[str],
    ) -> list[SessionPaneSpec]:
        sticky_specs: list[SessionPaneSpec] = []
        for session_id in sticky_session_ids:
            session = self._session_catalog.get(session_id)  # type: ignore[attr-defined]
            if not session:
                continue
            spec = self._session_pane_spec(session, is_sticky=True)
            if spec is not None:
                sticky_specs.append(spec)
        return sticky_specs

    def _build_active_spec(self, request: LayoutRequest) -> SessionPaneSpec | None:
        if request.active_session_id:
            session = self._session_catalog.get(request.active_session_id)  # type: ignore[attr-defined]
            if session:
                return self._session_pane_spec(session, is_sticky=False)
        elif request.active_doc_preview:
            return SessionPaneSpec(
                session_id=doc_pane_key(request.active_doc_preview.doc_id),
                tmux_session_name=None,
                attachment_destination=None,
                is_sticky=False,
                active_agent="",
                command=request.active_doc_preview.command,
            )
        return None

    def _session_pane_spec(self, session: SessionDTO, *, is_sticky: bool) -> SessionPaneSpec | None:
        """Materialize an admitted attachment or retain its observed target."""
        observed = self._observed_session_spec(session.session_id)
        if (
            session.host_viewer_admission != HostPaneViewerAdmission.ADMITTED
            or session.attachment_destination is None
            or not session.tmux_session_name
        ):
            if observed is None:
                return None
            return replace(observed, is_sticky=is_sticky, active_agent=session.active_agent or "")

        return SessionPaneSpec(
            session_id=session.session_id,
            tmux_session_name=session.tmux_session_name,
            attachment_destination=session.attachment_destination,
            is_sticky=is_sticky,
            active_agent=session.active_agent or "",
        )

    def _observed_session_spec(self, session_id: str) -> SessionPaneSpec | None:
        """Return the prior target only while the pane map still owns a viewer."""
        if session_id not in self.state.session_to_pane:  # type: ignore[attr-defined]
            return None
        observed = self._layout_state.observed_specs.get(session_id)  # type: ignore[attr-defined]
        if observed is not None:
            return observed
        candidates = list(self._layout_state.cell_specs or [])  # type: ignore[attr-defined]
        if self._layout_state.active_spec is not None:  # type: ignore[attr-defined]
            candidates.append(self._layout_state.active_spec)  # type: ignore[attr-defined]
        candidates.extend(self._layout_state.sticky_specs)  # type: ignore[attr-defined]
        return next((spec for spec in candidates if spec.session_id == session_id), None)

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
        structural_keys = tuple(self._cell_fingerprint(spec) for spec in session_specs)
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
            if session_id.startswith(DOC_PANE_PREFIX):
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
                is_remote=self._session_is_remote(session.session_id),  # type: ignore[attr-defined]
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
            self._layout_state.observed_specs.pop(spec.session_id, None)  # type: ignore[attr-defined]
            if pane is not None:
                self._layout_state.observed_geometry.pop(pane, None)  # type: ignore[attr-defined]
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
        self._layout_state.observed_specs[spec.session_id] = spec  # type: ignore[attr-defined]

        if spec.tmux_session_name:
            self._set_pane_background(  # type: ignore[attr-defined]
                pane_id,
                spec.tmux_session_name,
                spec.active_agent,
                is_tree_selected=self._is_tree_selected_session(spec.session_id),
                is_remote=self._spec_is_remote(spec),  # type: ignore[attr-defined]
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
            spec.attachment_destination,
        )
