"""Main TUI application with view switching."""

import asyncio
import curses
import time
from dataclasses import dataclass, field

import nest_asyncio
from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.pane_manager import TmuxPaneManager
from teleclaude.cli.tui.theme import init_colors
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.banner import BANNER_HEIGHT, render_banner
from teleclaude.cli.tui.widgets.footer import Footer
from teleclaude.cli.tui.widgets.tab_bar import TabBar

# Allow nested event loops (required for async calls inside curses sync loop)
nest_asyncio.apply()

logger = get_logger(__name__)

# Key name mapping for debug logging
KEY_NAMES = {
    curses.KEY_UP: "KEY_UP",
    curses.KEY_DOWN: "KEY_DOWN",
    curses.KEY_LEFT: "KEY_LEFT",
    curses.KEY_RIGHT: "KEY_RIGHT",
    curses.KEY_ENTER: "KEY_ENTER",
    curses.KEY_MOUSE: "KEY_MOUSE",
    10: "ENTER(10)",
    13: "ENTER(13)",
    27: "ESCAPE",
}


# Notification durations in seconds
NOTIFICATION_DURATION_INFO = 3.0
NOTIFICATION_DURATION_ERROR = 5.0


def _key_name(key: int) -> str:
    """Get human-readable key name for logging."""
    if key in KEY_NAMES:
        return KEY_NAMES[key]
    if 32 <= key < 127:
        return f"'{chr(key)}'({key})"
    return f"KEY({key})"


@dataclass
class FocusLevel:
    """A single level in the focus stack."""

    type: str  # "computer" or "project"
    name: str  # Computer name or project path


@dataclass
class FocusContext:
    """Shared focus context across views."""

    stack: list[FocusLevel] = field(default_factory=list)

    def push(self, level_type: str, name: str) -> None:
        """Push a new focus level."""
        self.stack.append(FocusLevel(type=level_type, name=name))

    def pop(self) -> bool:
        """Pop the last focus level. Returns True if popped, False if empty."""
        if self.stack:
            self.stack.pop()
            return True
        return False

    def clear(self) -> None:
        """Clear the focus stack."""
        self.stack.clear()

    @property
    def computer(self) -> str | None:
        """Get focused computer name, if any."""
        for level in self.stack:
            if level.type == "computer":
                return level.name
        return None

    @property
    def project(self) -> str | None:
        """Get focused project path, if any."""
        for level in self.stack:
            if level.type == "project":
                return level.name
        return None

    def get_breadcrumb(self) -> str:
        """Get breadcrumb string."""
        if not self.stack:
            return ""
        parts: list[str] = []
        for level in self.stack:
            if level.type == "computer":
                parts.append(level.name)
            elif level.type == "project":
                # Show just the last directory name
                parts.append(level.name.split("/")[-1] or level.name)
        return " > ".join(parts)


@dataclass
class Notification:
    """A temporary notification message."""

    message: str
    level: str  # "info", "error", "success"
    expires_at: float  # timestamp when it should disappear


class TelecApp:
    """Main TUI application with view switching (1=Sessions, 2=Preparation)."""

    def __init__(self, api: object):
        """Initialize TUI app.

        Args:
            api: API client instance
        """
        self.api = api
        self.current_view = 1  # 1=Sessions, 2=Preparation
        self.views: dict[int, SessionsView | PreparationView] = {}
        self.tab_bar = TabBar()
        self.footer: Footer | None = None
        self.running = True
        self.agent_availability: dict[str, dict[str, object]] = {}  # guard: loose-dict
        self._loop: asyncio.AbstractEventLoop | None = None
        self.focus = FocusContext()  # Shared focus across views
        self.notification: Notification | None = None
        self.pane_manager = TmuxPaneManager()
        # Content area bounds for mouse click handling
        self._content_start: int = 0
        self._content_height: int = 0

    async def initialize(self) -> None:
        """Load initial data and create views."""
        await self.api.connect()  # type: ignore[attr-defined]
        self._loop = asyncio.get_running_loop()

        # Create views BEFORE refresh so they can receive data
        # Pass shared focus context to each view
        self.views[1] = SessionsView(self.api, self.agent_availability, self.focus, self.pane_manager)
        self.views[2] = PreparationView(self.api, self.agent_availability, self.focus)

        # Now refresh to populate views with data
        await self.refresh_data()

    async def refresh_data(self) -> None:
        """Refresh all data from API."""
        logger.debug("Refreshing data from API...")
        try:
            computers, projects, sessions, availability = await asyncio.gather(
                self.api.list_computers(),  # type: ignore[attr-defined]
                self.api.list_projects(),  # type: ignore[attr-defined]
                self.api.list_sessions(),  # type: ignore[attr-defined]
                self.api.get_agent_availability(),  # type: ignore[attr-defined]
            )

            logger.debug(
                "API returned: %d computers, %d projects, %d sessions",
                len(computers),
                len(projects),
                len(sessions),
            )

            self.agent_availability = availability  # type: ignore[assignment]

            # Refresh ALL views with data (not just current)
            for view_num, view in self.views.items():
                await view.refresh(computers, projects, sessions)  # type: ignore[arg-type]
                logger.debug(
                    "View %d refreshed: flat_items=%d",
                    view_num,
                    len(view.flat_items),
                )

            # Update footer with new availability
            self.footer = Footer(self.agent_availability)
            logger.debug("Data refresh complete")
        except Exception as e:
            logger.error("Failed to refresh data: %s", e, exc_info=True)
            self.notify(f"Refresh failed: {e}", "error")

    def notify(self, message: str, level: str = "info") -> None:
        """Show a temporary notification.

        Args:
            message: Message to display
            level: Notification level ("info", "error", "success")
        """
        duration = NOTIFICATION_DURATION_ERROR if level == "error" else NOTIFICATION_DURATION_INFO
        self.notification = Notification(
            message=message,
            level=level,
            expires_at=time.time() + duration,
        )

    def update_session_panes(self) -> None:
        """Hide session panes when leaving Sessions view.

        Called when view is switched. Pane toggling within Sessions view
        is handled by SessionsView.handle_enter().
        """
        if not self.pane_manager.is_available:
            return

        # Hide panes when not in Sessions view
        if self.current_view != 1:
            self.pane_manager.hide_sessions()

    def cleanup(self) -> None:
        """Clean up resources before exit."""
        self.pane_manager.cleanup()

    def run(self, stdscr: object) -> None:
        """Main event loop.

        No auto-refresh to allow text selection. User presses 'r' to refresh.
        Screen updates only on user input.

        Args:
            stdscr: Curses screen object
        """
        curses.curs_set(0)
        init_colors()

        # Enable mouse support for click and double-click only
        # (don't capture drag events - allow terminal text selection)
        curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED)

        # Block indefinitely waiting for input (no timeout = no auto-refresh)
        stdscr.timeout(-1)  # type: ignore[attr-defined]

        # Initial render
        self._render(stdscr)

        while self.running:
            key = stdscr.getch()  # type: ignore[attr-defined]

            if key != -1:
                self._handle_key(key, stdscr)
                # Check if view needs data refresh
                view = self.views.get(self.current_view)
                if view and getattr(view, "needs_refresh", False):
                    asyncio.get_event_loop().run_until_complete(self.refresh_data())
                    view.needs_refresh = False
                self._render(stdscr)

    def _handle_key(self, key: int, stdscr: object) -> None:
        """Handle key press.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        key_str = _key_name(key)
        logger.debug("Key pressed: %s, current_view=%d", key_str, self.current_view)

        if key == ord("q"):
            logger.debug("Quit requested")
            self.cleanup()
            self.running = False

        # Mouse click - handle tab clicks and content item selection
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                # Double-click: select item and execute default action
                if bstate & curses.BUTTON1_DOUBLE_CLICKED:
                    if self._content_start <= my < self._content_start + self._content_height:
                        view = self.views.get(self.current_view)
                        if view and hasattr(view, "handle_click"):
                            if view.handle_click(my):
                                # Item selected, now execute default action
                                view.handle_enter(stdscr)
                # Single click: select item or switch tab
                elif bstate & curses.BUTTON1_CLICKED:
                    # First check if a tab was clicked
                    clicked_tab = self.tab_bar.handle_click(my, mx)
                    if clicked_tab is not None:
                        self._switch_view(clicked_tab)
                    # Otherwise check if click is in content area
                    elif self._content_start <= my < self._content_start + self._content_height:
                        view = self.views.get(self.current_view)
                        if view and hasattr(view, "handle_click"):
                            view.handle_click(my)
            except curses.error:
                pass  # Mouse event couldn't be retrieved

        # Escape - always go back in focus stack
        elif key == 27:  # Escape
            logger.debug("Escape: popping focus stack")
            if self.focus.pop():
                view = self.views.get(self.current_view)
                if view:
                    view.rebuild_for_focus()
                    logger.debug("Focus popped, view rebuilt")

        # Left Arrow - collapse session or go back in focus stack
        elif key == curses.KEY_LEFT:
            view = self.views.get(self.current_view)
            logger.debug("Left arrow: view=%s", type(view).__name__ if view else None)
            # Try to collapse session first (SessionsView only)
            if view and hasattr(view, "collapse_selected"):
                collapsed = view.collapse_selected()
                logger.debug("collapse_selected() returned %s", collapsed)
                if collapsed:
                    pass  # Session collapsed
                elif self.focus.pop():
                    # Go back in focus stack
                    view.rebuild_for_focus()
                    logger.debug("Focus popped after collapse_selected returned False")
            elif self.focus.pop():
                if view:
                    view.rebuild_for_focus()

        # Right Arrow - drill down into selected item
        elif key == curses.KEY_RIGHT:
            view = self.views.get(self.current_view)
            logger.debug("Right arrow: view=%s", type(view).__name__ if view else None)
            if view:
                result = view.drill_down()
                logger.debug("drill_down() returned %s", result)

        # View switching with number keys
        elif key == ord("1"):
            logger.debug("Switching to view 1 (Sessions)")
            self._switch_view(1)
        elif key == ord("2"):
            logger.debug("Switching to view 2 (Preparation)")
            self._switch_view(2)

        # Navigation - delegate to current view
        elif key == curses.KEY_UP:
            view = self.views.get(self.current_view)
            if view:
                view.move_up()
                logger.debug("move_up: selected_index=%d", view.selected_index)
        elif key == curses.KEY_DOWN:
            view = self.views.get(self.current_view)
            if view:
                view.move_down()
                logger.debug("move_down: selected_index=%d", view.selected_index)

        # Common actions
        elif key in (curses.KEY_ENTER, 10, 13):
            view = self.views.get(self.current_view)
            logger.debug("Enter: view=%s", type(view).__name__ if view else None)
            if view:
                view.handle_enter(stdscr)
        elif key == ord("r"):
            logger.debug("Refresh requested")
            asyncio.get_event_loop().run_until_complete(self.refresh_data())

        # View-specific actions
        else:
            view = self.views.get(self.current_view)
            logger.debug(
                "Delegating key %s to view.handle_key(), view=%s",
                key_str,
                type(view).__name__ if view else None,
            )
            if view:
                view.handle_key(key, stdscr)
            else:
                logger.warning("No view found for current_view=%d", self.current_view)

    def _switch_view(self, view_num: int) -> None:
        """Switch to a different view.

        Args:
            view_num: View number (1 or 2)
        """
        if view_num in self.views:
            logger.debug("Switching from view %d to view %d", self.current_view, view_num)
            self.current_view = view_num
            self.tab_bar.set_active(view_num)
            # Rebuild the new view with current focus
            view = self.views.get(view_num)
            if view:
                view.rebuild_for_focus()
                logger.debug(
                    "View %d rebuilt: flat_items=%d, selected_index=%d",
                    view_num,
                    len(view.flat_items),
                    view.selected_index,
                )
            # Update panes (shows sessions in view 1, hides in view 2)
            self.update_session_panes()
        else:
            logger.warning("Attempted to switch to non-existent view %d", view_num)

    def _render(self, stdscr: object) -> None:
        """Render current view with banner, tab bar, and footer.

        Args:
            stdscr: Curses screen object
        """
        stdscr.erase()  # type: ignore[attr-defined]  # erase() doesn't affect scroll buffer
        height, width = stdscr.getmaxyx()  # type: ignore[attr-defined]

        # Rows 0-5: ASCII banner (6 lines)
        render_banner(stdscr, 0, width)

        # Row after banner: Tab bar (3 rows for browser-style tabs)
        tab_row = BANNER_HEIGHT
        self.tab_bar.render(stdscr, tab_row, width)

        # Row after tab bar: empty row for spacing, then breadcrumb (if focused)
        content_start = tab_row + TabBar.HEIGHT + 1  # +HEIGHT for tab bar + 1 for spacing
        if self.focus.stack:
            self._render_breadcrumb(stdscr, content_start, width)
            content_start += 1

        # Content area: after breadcrumb to before footer section
        content_height = height - content_start - 4  # Reserve 4 rows for separator + action bar + global bar + footer

        # Store bounds for mouse click handling
        self._content_start = content_start
        self._content_height = content_height

        current = self.views.get(self.current_view)
        if current and content_height > 0:
            current.render(stdscr, content_start, content_height, width)

        # Render notification (toast) if active
        self._render_notification(stdscr, width)

        # Row height-4: Separator
        stdscr.addstr(height - 4, 0, "─" * width)  # type: ignore[attr-defined]

        # Row height-3: Action bar (view-specific)
        action_bar = current.get_action_bar() if current else ""
        stdscr.addstr(height - 3, 0, action_bar[:width])  # type: ignore[attr-defined]

        # Row height-2: Global shortcuts bar
        global_bar = "[+/-] Expand/Collapse All  [r] Refresh  [q] Quit"
        stdscr.addstr(height - 2, 0, global_bar[:width], curses.A_DIM)  # type: ignore[attr-defined]

        # Row height-1: Footer
        if self.footer:
            self.footer.render(stdscr, height - 1, width)

        stdscr.refresh()  # type: ignore[attr-defined]

    def _render_breadcrumb(self, stdscr: object, row: int, width: int) -> None:
        """Render breadcrumb with last part bold.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            width: Screen width
        """
        if not self.focus.stack:
            return

        prefix = "  📍 "
        parts: list[str] = []
        for level in self.focus.stack:
            if level.type == "computer":
                parts.append(level.name)
            elif level.type == "project":
                parts.append(level.name.split("/")[-1] or level.name)

        try:
            col = 0
            # Render prefix
            stdscr.addstr(row, col, prefix)  # type: ignore[attr-defined]
            col += len(prefix)

            # Render all parts except last (normal)
            for part in parts[:-1]:
                stdscr.addstr(row, col, part)  # type: ignore[attr-defined]
                col += len(part)
                stdscr.addstr(row, col, " > ")  # type: ignore[attr-defined]
                col += 3

            # Render last part (bold)
            if parts:
                stdscr.addstr(row, col, parts[-1], curses.A_BOLD)  # type: ignore[attr-defined]
        except curses.error:
            pass  # Screen too small

    def _render_notification(self, stdscr: object, width: int) -> None:
        """Render notification toast if active.

        Args:
            stdscr: Curses screen object
            width: Screen width
        """
        if not self.notification:
            return

        # Check if expired
        if time.time() > self.notification.expires_at:
            self.notification = None
            return

        # Position: top center, just below tab bar
        row = BANNER_HEIGHT + 1
        msg = self.notification.message
        msg_len = len(msg) + 4  # Add padding
        start_col = max(0, (width - msg_len) // 2)

        # Color based on level
        if self.notification.level == "error":
            attr = curses.color_pair(1) | curses.A_BOLD  # Red
        elif self.notification.level == "success":
            attr = curses.color_pair(2) | curses.A_BOLD  # Green
        else:
            attr = curses.A_REVERSE  # Info - inverted

        # Render notification box
        display_msg = f"  {msg}  "
        try:
            stdscr.addstr(row, start_col, display_msg[: width - start_col], attr)  # type: ignore[attr-defined]
        except curses.error:
            pass  # Ignore if can't render (screen too small)
