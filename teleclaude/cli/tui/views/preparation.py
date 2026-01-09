"""Preparation view - shows planned work from todos/roadmap.md."""

import asyncio
import curses
import os
import subprocess

from teleclaude.cli.tui.todos import parse_roadmap


class PreparationView:
    """View 2: Preparation - todo-centric tree showing roadmap items."""

    STATUS_MARKERS: dict[str, str] = {
        "pending": "[ ]",
        "ready": "[.]",
        "in_progress": "[>]",
    }

    def __init__(self, api: object, agent_availability: dict[str, dict[str, object]]):
        """Initialize preparation view.

        Args:
            api: API client instance
            agent_availability: Agent availability status
        """
        self.api = api
        self.agent_availability = agent_availability
        self.flat_items: list[dict[str, object]] = []
        self.selected_index = 0
        self.scroll_offset = 0

    async def refresh(
        self,
        computers: list[dict[str, object]],
        projects: list[dict[str, object]],
        sessions: list[dict[str, object]],  # noqa: ARG002 - needed for API consistency
    ) -> None:
        """Refresh view data - parse todos for each project.

        Args:
            computers: List of computers
            projects: List of projects
            sessions: List of sessions (unused but kept for consistency)
        """
        self.flat_items = []

        for computer in computers:
            self.flat_items.append(
                {
                    "type": "computer",
                    "name": computer.get("name", ""),
                    "depth": 0,
                }
            )

            comp_name = computer.get("name", "")
            comp_projects = [p for p in projects if p.get("computer") == comp_name]

            for project in comp_projects:
                self.flat_items.append(
                    {
                        "type": "project",
                        "path": project.get("path", ""),
                        "computer": comp_name,
                        "depth": 1,
                    }
                )

                # Parse todos from this project's roadmap.md
                project_path = str(project.get("path", ""))
                todos = parse_roadmap(project_path)
                for todo in todos:
                    self.flat_items.append(
                        {
                            "type": "todo",
                            "slug": todo.slug,
                            "status": todo.status,
                            "description": todo.description,
                            "has_requirements": todo.has_requirements,
                            "has_impl_plan": todo.has_impl_plan,
                            "project_path": project_path,
                            "computer": comp_name,
                            "depth": 2,
                        }
                    )

    def get_action_bar(self) -> str:
        """Return action bar string for this view.

        Returns:
            Action bar text
        """
        return "[s] Start Work  [p] Prepare  [v/V] View  [e/E] Edit  [r] Refresh"

    def move_up(self) -> None:
        """Move selection up."""
        self.selected_index = max(0, self.selected_index - 1)

    def move_down(self) -> None:
        """Move selection down."""
        self.selected_index = min(len(self.flat_items) - 1, self.selected_index + 1)

    def handle_enter(self, stdscr: object) -> None:  # noqa: ARG002 - stdscr needed for future features
        """Handle Enter - same as Start Work for ready items.

        Args:
            stdscr: Curses screen object
        """
        item = self._get_selected()
        if item and item["type"] == "todo" and item["status"] == "ready":
            self._start_work(item)

    def _get_selected(self) -> dict[str, object] | None:
        """Get currently selected item.

        Returns:
            Selected item or None
        """
        if 0 <= self.selected_index < len(self.flat_items):
            return self.flat_items[self.selected_index]
        return None

    def _start_work(self, item: dict[str, object]) -> None:
        """Start work on a ready todo via /prime-orchestrator.

        Args:
            item: Todo item
        """
        # Suspend TUI temporarily
        curses.endwin()
        slug = str(item.get("slug", ""))
        asyncio.get_event_loop().run_until_complete(
            self.api.create_session(  # type: ignore[attr-defined]
                computer=item.get("computer"),
                project_dir=item.get("project_path"),
                agent="claude",
                thinking_mode="slow",
                message=f"/prime-orchestrator {slug}",
            )
        )
        curses.doupdate()

    def _prepare(self, item: dict[str, object]) -> None:
        """Prepare a todo via /next-prepare.

        Args:
            item: Todo item
        """
        curses.endwin()
        slug = str(item.get("slug", ""))
        asyncio.get_event_loop().run_until_complete(
            self.api.create_session(  # type: ignore[attr-defined]
                computer=item.get("computer"),
                project_dir=item.get("project_path"),
                agent="claude",
                thinking_mode="slow",
                message=f"/next-prepare {slug}",
            )
        )
        curses.doupdate()

    def _view_file(self, item: dict[str, object], filename: str) -> None:
        """View a file in glow.

        Args:
            item: Todo item
            filename: File to view (requirements.md or implementation-plan.md)
        """
        curses.endwin()
        filepath = os.path.join(str(item.get("project_path", "")), "todos", str(item.get("slug", "")), filename)
        subprocess.run(["glow", filepath], check=False)
        curses.doupdate()

    def _edit_file(self, item: dict[str, object], filename: str) -> None:
        """Edit a file in $EDITOR.

        Args:
            item: Todo item
            filename: File to edit (requirements.md or implementation-plan.md)
        """
        curses.endwin()
        filepath = os.path.join(str(item.get("project_path", "")), "todos", str(item.get("slug", "")), filename)
        editor = os.environ.get("EDITOR", "vim")
        subprocess.run([editor, filepath], check=False)
        curses.doupdate()

    def handle_key(self, key: int, stdscr: object) -> None:  # noqa: ARG002 - stdscr needed for future features
        """Handle view-specific keys.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        item = self._get_selected()
        if not item or item["type"] != "todo":
            return

        if key == ord("s") and item["status"] == "ready":
            self._start_work(item)
        elif key == ord("p"):
            self._prepare(item)
        elif key == ord("v") and item.get("has_requirements"):
            self._view_file(item, "requirements.md")
        elif key == ord("V") and item.get("has_impl_plan"):
            self._view_file(item, "implementation-plan.md")
        elif key == ord("e"):
            self._edit_file(item, "requirements.md")
        elif key == ord("E"):
            self._edit_file(item, "implementation-plan.md")

    def render(self, stdscr: object, start_row: int, height: int, width: int) -> None:
        """Render view content.

        Args:
            stdscr: Curses screen object
            start_row: Starting row
            height: Available height
            width: Screen width
        """
        visible_start = self.scroll_offset
        visible_end = min(len(self.flat_items), visible_start + height)

        row = start_row
        for i in range(visible_start, visible_end):
            item = self.flat_items[i]
            is_selected = i == self.selected_index
            lines = self._render_item(stdscr, row, item, width, is_selected)
            row += lines

    def _render_item(self, stdscr: object, row: int, item: dict[str, object], width: int, selected: bool) -> int:
        """Render a single item.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Item data
            width: Screen width
            selected: Whether this item is selected

        Returns:
            Number of lines used
        """
        indent = "  " * int(item.get("depth", 0))
        attr = curses.A_REVERSE if selected else 0

        if item["type"] == "computer":
            line = f"{indent}{item.get('name', ''):<50} online"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1

        if item["type"] == "project":
            line = f"{indent}{item.get('path', '')}"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1

        if item["type"] == "todo":
            return self._render_todo(stdscr, row, item, width, selected)

        return 1

    def _render_todo(self, stdscr: object, row: int, item: dict[str, object], width: int, selected: bool) -> int:
        """Render a todo item (3 lines).

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Todo item
            width: Screen width
            selected: Whether this item is selected

        Returns:
            Number of lines used (3)
        """
        indent = "  " * int(item.get("depth", 0))
        attr = curses.A_REVERSE if selected else 0

        # Line 1: Status marker and slug
        marker = self.STATUS_MARKERS.get(str(item.get("status", "pending")), "[ ]")
        status_label = str(item.get("status", "pending"))
        slug = str(item.get("slug", ""))
        line1 = f"{indent}{marker} {slug:<40} {status_label}"
        stdscr.addstr(row, 0, line1[:width], attr if selected else 0)  # type: ignore[attr-defined]

        # Line 2: Description
        description = item.get("description")
        if description:
            desc = str(description)[:75]
            line2 = f"{indent}     {desc}"
            stdscr.addstr(row + 1, 0, line2[:width])  # type: ignore[attr-defined]

        # Line 3: File status
        req_status = "✓" if item.get("has_requirements") else "✗"
        impl_status = "✓" if item.get("has_impl_plan") else "✗"
        line3 = f"{indent}     requirements: {req_status}  impl-plan: {impl_status}"
        stdscr.addstr(row + 2, 0, line3[:width])  # type: ignore[attr-defined]

        return 3  # Uses 3 lines
