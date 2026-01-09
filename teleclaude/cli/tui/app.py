"""Main TUI application with view switching."""

import asyncio
import curses

from teleclaude.cli.tui.theme import init_colors
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.footer import Footer
from teleclaude.cli.tui.widgets.tab_bar import TabBar


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

    async def initialize(self) -> None:
        """Load initial data and create views."""
        await self.api.connect()  # type: ignore[attr-defined]
        await self.refresh_data()

        # Create views
        self.views[1] = SessionsView(self.api, self.agent_availability)
        self.views[2] = PreparationView(self.api, self.agent_availability)

    async def refresh_data(self) -> None:
        """Refresh all data from API."""
        computers, projects, sessions, availability = await asyncio.gather(
            self.api.list_computers(),  # type: ignore[attr-defined]
            self.api.list_projects(),  # type: ignore[attr-defined]
            self.api.list_sessions(),  # type: ignore[attr-defined]
            self.api.get_agent_availability(),  # type: ignore[attr-defined]
        )

        self.agent_availability = availability  # type: ignore[assignment]
        self.footer = Footer(self.agent_availability)

        # Refresh current view
        current = self.views.get(self.current_view)
        if current:
            await current.refresh(computers, projects, sessions)  # type: ignore[arg-type]

    def run(self, stdscr: object) -> None:
        """Main event loop.

        Args:
            stdscr: Curses screen object
        """
        curses.curs_set(0)
        init_colors()

        while self.running:
            self._render(stdscr)
            key = stdscr.getch()  # type: ignore[attr-defined]
            self._handle_key(key, stdscr)

    def _handle_key(self, key: int, stdscr: object) -> None:
        """Handle key press.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        if key == ord("q"):
            self.running = False

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
            asyncio.get_event_loop().run_until_complete(self.refresh_data())

    def _render(self, stdscr: object) -> None:
        """Render current view with tab bar and footer.

        Args:
            stdscr: Curses screen object
        """
        stdscr.clear()  # type: ignore[attr-defined]
        height, width = stdscr.getmaxyx()  # type: ignore[attr-defined]

        # Row 0: Tab bar
        self.tab_bar.render(stdscr, 0, width)

        # Rows 1 to height-4: View content
        content_height = height - 5
        current = self.views.get(self.current_view)
        if current:
            current.render(stdscr, 1, content_height, width)

        # Row height-3: Separator
        stdscr.addstr(height - 3, 0, "─" * width)  # type: ignore[attr-defined]

        # Row height-2: Action bar (view-specific)
        action_bar = current.get_action_bar() if current else ""
        stdscr.addstr(height - 2, 0, action_bar[:width])  # type: ignore[attr-defined]

        # Row height-1: Footer
        if self.footer:
            self.footer.render(stdscr, height - 1, width)

        stdscr.refresh()  # type: ignore[attr-defined]
