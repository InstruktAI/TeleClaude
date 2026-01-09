"""Main TUI application with view switching."""

import asyncio
import curses
import time
from dataclasses import dataclass, field

import nest_asyncio
from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.theme import init_colors
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.banner import BANNER_HEIGHT, render_banner
from teleclaude.cli.tui.widgets.footer import Footer
from teleclaude.cli.tui.widgets.tab_bar import TabBar

# Allow nested event loops (required for async calls inside curses sync loop)
nest_asyncio.apply()

logger = get_logger(__name__)


# Notification durations in seconds
NOTIFICATION_DURATION_INFO = 3.0
NOTIFICATION_DURATION_ERROR = 5.0


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

    async def initialize(self) -> None:
        """Load initial data and create views."""
        await self.api.connect()  # type: ignore[attr-defined]
        self._loop = asyncio.get_running_loop()

        # Create views BEFORE refresh so they can receive data
        # Pass shared focus context to each view
        self.views[1] = SessionsView(self.api, self.agent_availability, self.focus)
        self.views[2] = PreparationView(self.api, self.agent_availability, self.focus)

        # Now refresh to populate views with data
        await self.refresh_data()

    async def refresh_data(self) -> None:
        """Refresh all data from API."""
        try:
            computers, projects, sessions, availability = await asyncio.gather(
                self.api.list_computers(),  # type: ignore[attr-defined]
                self.api.list_projects(),  # type: ignore[attr-defined]
                self.api.list_sessions(),  # type: ignore[attr-defined]
                self.api.get_agent_availability(),  # type: ignore[attr-defined]
            )

            self.agent_availability = availability  # type: ignore[assignment]

            # Refresh ALL views with data (not just current)
            for view in self.views.values():
                await view.refresh(computers, projects, sessions)  # type: ignore[arg-type]

            # Update footer with new availability
            self.footer = Footer(self.agent_availability)
        except Exception as e:
            logger.error("Failed to refresh data: %s", e)
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

    def run(self, stdscr: object) -> None:
        """Main event loop.

        No auto-refresh to allow text selection. User presses 'r' to refresh.
        Screen updates only on user input.

        Args:
            stdscr: Curses screen object
        """
        curses.curs_set(0)
        init_colors()

        # Block indefinitely waiting for input (no timeout = no auto-refresh)
        stdscr.timeout(-1)  # type: ignore[attr-defined]

        # Initial render
        self._render(stdscr)

        while self.running:
            key = stdscr.getch()  # type: ignore[attr-defined]

            if key != -1:
                self._handle_key(key, stdscr)
                self._render(stdscr)

    def _handle_key(self, key: int, stdscr: object) -> None:
        """Handle key press.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        if key == ord("q"):
            self.running = False

        # Escape - always go back in focus stack
        elif key == 27:  # Escape
            if self.focus.pop():
                view = self.views.get(self.current_view)
                if view:
                    view.rebuild_for_focus()

        # Left Arrow - collapse session or go back in focus stack
        elif key == curses.KEY_LEFT:
            view = self.views.get(self.current_view)
            # Try to collapse session first (SessionsView only)
            if view and hasattr(view, "collapse_selected") and view.collapse_selected():
                pass  # Session collapsed
            elif self.focus.pop():
                # Go back in focus stack
                if view:
                    view.rebuild_for_focus()

        # Right Arrow - drill down into selected item
        elif key == curses.KEY_RIGHT:
            view = self.views.get(self.current_view)
            if view:
                view.drill_down()

        # View switching with number keys
        elif key == ord("1"):
            self._switch_view(1)
        elif key == ord("2"):
            self._switch_view(2)

        # Navigation - delegate to current view
        elif key == curses.KEY_UP:
            view = self.views.get(self.current_view)
            if view:
                view.move_up()
        elif key == curses.KEY_DOWN:
            view = self.views.get(self.current_view)
            if view:
                view.move_down()

        # Common actions
        elif key in (curses.KEY_ENTER, 10, 13):
            view = self.views.get(self.current_view)
            if view:
                view.handle_enter(stdscr)
        elif key == ord("r"):
            asyncio.get_event_loop().run_until_complete(self.refresh_data())

        # View-specific actions
        else:
            view = self.views.get(self.current_view)
            if view:
                view.handle_key(key, stdscr)

    def _switch_view(self, view_num: int) -> None:
        """Switch to a different view.

        Args:
            view_num: View number (1 or 2)
        """
        if view_num in self.views:
            self.current_view = view_num
            self.tab_bar.set_active(view_num)
            # Rebuild the new view with current focus
            view = self.views.get(view_num)
            if view:
                view.rebuild_for_focus()

    def _render(self, stdscr: object) -> None:
        """Render current view with banner, tab bar, and footer.

        Args:
            stdscr: Curses screen object
        """
        stdscr.erase()  # type: ignore[attr-defined]  # erase() doesn't affect scroll buffer
        height, width = stdscr.getmaxyx()  # type: ignore[attr-defined]

        # Rows 0-5: ASCII banner (6 lines)
        render_banner(stdscr, 0, width)

        # Row after banner: Tab bar
        tab_row = BANNER_HEIGHT
        self.tab_bar.render(stdscr, tab_row, width)

        # Row after tab bar: Breadcrumb (if focused)
        content_start = tab_row + 1
        if self.focus.stack:
            self._render_breadcrumb(stdscr, content_start, width)
            content_start += 1

        # Content area: after breadcrumb to before footer section
        content_height = height - content_start - 4  # Reserve 4 rows for separator + action bar + global bar + footer
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
