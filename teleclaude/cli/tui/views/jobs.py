"""Jobs view - list and manage scheduled jobs."""

from __future__ import annotations

import asyncio
import curses
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import JobInfo, SessionInfo
from teleclaude.cli.tui.types import CursesWindow, NotificationLevel
from teleclaude.cli.tui.views.base import BaseView, ScrollableViewMixin
from teleclaude.cli.tui.widgets.modal import ConfirmModal

if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient

logger = get_logger(__name__)


class JobsView(ScrollableViewMixin[JobInfo], BaseView):
    """View 3: Jobs - list and control scheduled tasks."""

    def __init__(
        self,
        api: "TelecAPIClient",
        notify: Callable[[str, NotificationLevel], None] | None = None,
    ):
        """Initialize jobs view.

        Args:
            api: API client instance
            notify: Notification callback
        """
        self.api = api
        self.notify = notify
        self.flat_items: list[JobInfo] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self._row_to_item: dict[int, int] = {}
        self.needs_refresh: bool = False
        self._visible_height: int = 20
        self._last_rendered_range: tuple[int, int] = (0, 0)

        # Column widths
        self._col_widths = {
            "name": 30,
            "type": 8,
            "schedule": 15,
            "last_run": 20,
            "status": 10,
        }

    async def refresh(self, jobs: list[JobInfo], sessions: list[SessionInfo] | None = None) -> None:
        """Refresh view data.

        Args:
            jobs: List of jobs
            sessions: Optional list of sessions (used to show active job runs)
        """
        items: list[JobInfo | SessionInfo | str] = []

        # Show active job runs first
        if sessions:
            active_runs = [s for s in sessions if s.session_metadata and s.session_metadata.get("job_name")]
            if active_runs:
                items.append("Active Runs")
                items.extend(active_runs)
                items.append("")  # spacer

        # Then show job catalog
        if jobs:
            items.append("Job Catalog")
            items.extend(jobs)

        self.flat_items = items  # type: ignore[assignment]
        # Auto-select the first non-header/spacer item
        selected = 0
        for i, item in enumerate(self.flat_items):
            if not isinstance(item, str):
                selected = i
                break
        self.selected_index = selected

    def render(self, stdscr: CursesWindow, row_start: int, height: int, width: int) -> None:
        """Render the jobs list.

        Args:
            stdscr: Curses screen object
            row_start: Starting row
            height: Available height
            width: Screen width
        """
        self._visible_height = height
        if not self.flat_items:
            try:
                stdscr.addstr(row_start, 2, "(no jobs found)", curses.A_DIM)
            except curses.error:
                pass
            return

        # Render header
        header = (
            f"{'Job Name':<{self._col_widths['name']}} "
            f"{'Type':<{self._col_widths['type']}} "
            f"{'Schedule':<{self._col_widths['schedule']}} "
            f"{'Last Run':<{self._col_widths['last_run']}} "
            f"{'Status':<{self._col_widths['status']}}"
        )
        try:
            stdscr.addstr(row_start, 2, header[: width - 2], curses.A_BOLD | curses.A_UNDERLINE)
        except curses.error:
            pass

        # Render list
        max_scroll = max(0, len(self.flat_items) - (height - 1))  # -1 for header
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        self._row_to_item.clear()
        start_idx = self.scroll_offset
        end_idx = min(start_idx + height - 1, len(self.flat_items))
        self._last_rendered_range = (start_idx, end_idx - 1)

        for i in range(start_idx, end_idx):
            item = self.flat_items[i]
            row = row_start + 1 + (i - start_idx)
            is_selected = i == self.selected_index

            # Headers and spacers
            if isinstance(item, str):
                try:
                    if item:  # Non-empty string = section header
                        stdscr.addstr(row, 2, item, curses.A_BOLD | curses.A_DIM)
                except curses.error:
                    pass
                continue

            self._row_to_item[row] = i
            attr = curses.A_REVERSE if is_selected else curses.A_NORMAL

            # Color status
            status_attr = attr
            if hasattr(item, "status"):
                if item.status == "success":
                    status_attr |= curses.color_pair(2)  # Green
                elif item.status == "failed":
                    status_attr |= curses.color_pair(1)  # Red

            if isinstance(item, JobInfo):
                line = (
                    f"{item.name:<{self._col_widths['name']}} "
                    f"{item.type:<{self._col_widths['type']}} "
                    f"{str(item.schedule or '-'):<{self._col_widths['schedule']}} "
                    f"{str(item.last_run or 'never'):<{self._col_widths['last_run']}} "
                )
                status_text = f"{item.status:<{self._col_widths['status']}}"
            else:
                # SessionInfo (active job run)
                title = getattr(item, "title", "") or ""
                agent = getattr(item, "agent", "") or ""
                line = f"  {agent:<8} {title:<{self._col_widths['name']}}"
                status_text = getattr(item, "status", "") or ""

            try:
                stdscr.addstr(row, 2, line[: width - 4], attr)
                stdscr.addstr(f" {status_text}", status_attr)
            except curses.error:
                pass

    def get_action_bar(self) -> str:
        """Return action bar string."""
        if not self.flat_items:
            return ""
        return "[Enter/r] Run Job"

    def handle_key(self, key: int, stdscr: CursesWindow) -> None:
        """Handle key press."""
        if not self.flat_items:
            return

        if key in (curses.KEY_ENTER, 10, 13, ord("r")):
            self._run_selected_job(stdscr)

    def move_up(self) -> None:
        """Move selection up, skipping headers and spacers."""
        if not self.flat_items:
            return
        new_index = self.selected_index - 1
        while new_index >= 0:
            if not isinstance(self.flat_items[new_index], str):
                self.selected_index = new_index
                if self.selected_index < self.scroll_offset:
                    self.scroll_offset = self.selected_index
                return
            new_index -= 1

    def move_down(self) -> None:
        """Move selection down, skipping headers and spacers."""
        if not self.flat_items:
            return
        new_index = self.selected_index + 1
        while new_index < len(self.flat_items):
            if not isinstance(self.flat_items[new_index], str):
                self.selected_index = new_index
                if hasattr(self, "_last_rendered_range"):
                    _, last_rendered = self._last_rendered_range
                    if self.selected_index > last_rendered:
                        self.scroll_offset += self.selected_index - last_rendered
                return
            new_index += 1

    def handle_click(self, screen_row: int, is_double_click: bool = False) -> bool:
        """Handle mouse click."""
        item_idx = self._row_to_item.get(screen_row)
        if item_idx is not None:
            self.selected_index = item_idx
            return True
        return False

    def handle_enter(self, stdscr: CursesWindow) -> None:
        """Handle enter key (alias to run)."""
        self._run_selected_job(stdscr)

    def _run_selected_job(self, stdscr: CursesWindow) -> None:
        """Run the selected job immediately."""
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return

        job = self.flat_items[self.selected_index]
        if not isinstance(job, JobInfo):
            return

        modal = ConfirmModal(
            title="Run Job",
            message=f"Run job '{job.name}' immediately?",
            details=[
                f"Type: {job.type}",
                f"Schedule: {job.schedule or '-'}",
            ],
        )

        if modal.run(stdscr):
            if self.notify:
                self.notify(f"Triggering job '{job.name}'...", NotificationLevel.INFO)

            try:
                # Async call in synchronous context requires a loop
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(self.api.run_job(job.name))
                if result and self.notify:
                    self.notify(f"Job '{job.name}' finished successfully", NotificationLevel.SUCCESS)
                elif not result and self.notify:
                    self.notify(f"Job '{job.name}' failed", NotificationLevel.ERROR)
                self.needs_refresh = True
            except Exception as e:
                logger.error("Failed to run job %s: %s", job.name, e)
                if self.notify:
                    self.notify(f"Failed to trigger job: {e}", NotificationLevel.ERROR)

    def rebuild_for_focus(self) -> None:
        """Rebuild view based on focus (no-op for flat list)."""
        pass
