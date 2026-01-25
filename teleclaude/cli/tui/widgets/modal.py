"""Modal dialog widgets."""

import asyncio
import curses
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import AgentAvailabilityInfo, CreateSessionResult
from teleclaude.cli.tui.theme import (
    get_input_border_attr,
    get_layer_attr,
    get_modal_border_attr,
    get_selection_attr,
)
from teleclaude.cli.tui.types import CursesWindow, NotificationLevel
from teleclaude.constants import ResultStatus

logger = get_logger(__name__)


def _apply_dim_overlay(stdscr: CursesWindow) -> None:
    """Apply dim attribute to entire screen without changing content.

    Uses chgat() to modify attributes of existing characters,
    creating a true overlay effect like tmux inactive panes.

    Args:
        stdscr: Curses screen object
    """
    height, width = stdscr.getmaxyx()

    for y in range(height):
        try:
            stdscr.chgat(y, 0, width, curses.A_DIM)
        except curses.error:
            pass


if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient


class StartSessionModal:
    """Modal for starting a new session with agent/mode selection."""

    AGENTS = ["claude", "gemini", "codex"]
    MODES = ["fast", "slow", "med"]

    def __init__(
        self,
        computer: str,
        project_path: str,
        api: "TelecAPIClient",
        agent_availability: dict[str, AgentAvailabilityInfo],
        default_prompt: str = "",
        notify: Callable[[str, str], None] | None = None,
    ):
        """Initialize modal.

        Args:
            computer: Computer name
            project_path: Project directory path
            api: API client instance
            agent_availability: Agent availability status
            default_prompt: Pre-filled prompt text
        """
        self.computer = computer
        self.project_path = project_path
        self.api = api
        self.agent_availability = agent_availability
        self.notify = notify
        self.start_requested = False

        # Find first available agent
        self.selected_agent = 0
        for i, agent in enumerate(self.AGENTS):
            if self._is_agent_available(agent):
                self.selected_agent = i
                break

        self.selected_mode = 1  # default: slow
        self.prompt = default_prompt
        self.native_session_id = ""
        self.current_field = 0  # 0=agent, 1=mode, 2=prompt, 3=session_id, 4=actions
        self.selected_action = 0  # 0=Start, 1=Cancel

    def _is_agent_available(self, agent: str) -> bool:
        """Check if agent is available.

        Args:
            agent: Agent name

        Returns:
            True if available
        """
        info = self.agent_availability.get(agent)
        if not info:
            return False
        return info.available is True

    def _get_available_agents(self) -> list[int]:
        """Get indices of available agents.

        Returns:
            List of available agent indices
        """
        return [i for i, a in enumerate(self.AGENTS) if self._is_agent_available(a)]

    def _ensure_selected_agent_available(self) -> None:
        """Ensure selected agent is available or fall back to first available."""
        if self._is_agent_available(self.AGENTS[self.selected_agent]):
            return
        available = self._get_available_agents()
        if available:
            self.selected_agent = available[0]
            return
        # No available agents - move focus off agent field
        if self.current_field == 0:
            self.current_field = 1

    def run(self, stdscr: CursesWindow) -> CreateSessionResult | None:
        """Run modal event loop.

        Args:
            stdscr: Curses screen object

        Returns:
            Session info or None if cancelled
        """
        while True:
            self._render(stdscr)
            key = stdscr.getch()

            if key == 27:  # Escape
                return None
            if key in (curses.KEY_ENTER, 10, 13):
                return self._start_session(stdscr)
            elif key == ord("\t"):
                self.current_field = (self.current_field + 1) % 5
                if self.current_field == 0 and not self._get_available_agents():
                    self.current_field = 1
            elif key == curses.KEY_UP:
                self.current_field = max(0, self.current_field - 1)
                if self.current_field == 0 and not self._get_available_agents():
                    self.current_field = 1
            elif key == curses.KEY_DOWN:
                self.current_field = min(4, self.current_field + 1)
                if self.current_field == 0 and not self._get_available_agents():
                    self.current_field = 1
            elif key == curses.KEY_LEFT:
                if self.current_field != 0 or self._get_available_agents():
                    self._select_prev()
            elif key == curses.KEY_RIGHT:
                if self.current_field != 0 or self._get_available_agents():
                    self._select_next()
            elif self.current_field == 2:
                self._handle_prompt_key(key)
            elif self.current_field == 3:
                self._handle_session_id_key(key)

    def _select_prev(self) -> None:
        """Select previous option, skipping unavailable agents."""
        if self.current_field == 0:
            available = self._get_available_agents()
            if not available:
                return
            try:
                current_pos = available.index(self.selected_agent)
                new_pos = (current_pos - 1) % len(available)
                self.selected_agent = available[new_pos]
            except ValueError:
                self.selected_agent = available[0]
        elif self.current_field == 1:
            self.selected_mode = (self.selected_mode - 1) % len(self.MODES)
        elif self.current_field == 4:
            self.selected_action = (self.selected_action - 1) % 2

    def _select_next(self) -> None:
        """Select next option, skipping unavailable agents."""
        if self.current_field == 0:
            available = self._get_available_agents()
            if not available:
                return
            try:
                current_pos = available.index(self.selected_agent)
                new_pos = (current_pos + 1) % len(available)
                self.selected_agent = available[new_pos]
            except ValueError:
                self.selected_agent = available[0]
        elif self.current_field == 1:
            self.selected_mode = (self.selected_mode + 1) % len(self.MODES)
        elif self.current_field == 4:
            self.selected_action = (self.selected_action + 1) % 2

    def _handle_prompt_key(self, key: int) -> None:
        """Handle key input in prompt field.

        Args:
            key: Key code
        """
        if key in (curses.KEY_BACKSPACE, 127):
            self.prompt = self.prompt[:-1]
        elif 32 <= key <= 126:
            self.prompt += chr(key)

    def _handle_session_id_key(self, key: int) -> None:
        """Handle key input in session ID field.

        Args:
            key: Key code
        """
        if key in (curses.KEY_BACKSPACE, 127):
            self.native_session_id = self.native_session_id[:-1]
        elif 32 <= key <= 126:
            self.native_session_id += chr(key)

    def _start_session(self, stdscr: CursesWindow) -> CreateSessionResult | None:
        """Start the session via API.

        Returns:
            Session creation result
        """
        self._ensure_selected_agent_available()
        if not self._is_agent_available(self.AGENTS[self.selected_agent]):
            if self.notify:
                self.notify("No agents available to start a session", NotificationLevel.ERROR)
            return None

        agent = self.AGENTS[self.selected_agent]
        mode = self.MODES[self.selected_mode]
        native_session_id = self.native_session_id.strip()
        auto_command = f"agent_resume {agent} {native_session_id}" if native_session_id else None
        message = None if native_session_id else self.prompt

        if self.notify:
            self.notify("Starting session...", NotificationLevel.INFO)
        self.start_requested = True

        try:
            result = asyncio.get_event_loop().run_until_complete(
                self.api.create_session(
                    computer=self.computer,
                    project_path=self.project_path,
                    agent=agent,
                    thinking_mode=mode,
                    message=message,
                    auto_command=auto_command,
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Failed to start session: %s", exc, exc_info=True)
            if self.notify:
                self.notify(f"Start failed: {exc}", NotificationLevel.ERROR)
            return None

        if result.status != ResultStatus.SUCCESS.value:
            error_msg = result.error or "Unknown error"
            logger.error("Session start failed: %s", error_msg)
            if self.notify:
                self.notify(f"Start failed: {error_msg}", NotificationLevel.ERROR)
            return None

        return result

    def _render(self, stdscr: CursesWindow) -> None:
        """Render the modal.

        Args:
            stdscr: Curses screen object
        """
        self._ensure_selected_agent_available()
        height, width = stdscr.getmaxyx()

        # Modal dimensions (including borders and input field boxes)
        modal_h, modal_w = 24, 60
        start_y = (height - modal_h) // 2
        start_x = (width - modal_w) // 2

        # Modal background (z=2 layer - terminal default)
        modal_bg = get_layer_attr(2)
        selection_bg = get_selection_attr(2)
        border_attr = get_modal_border_attr()

        # Apply dim to existing screen content (true overlay, no redraw)
        _apply_dim_overlay(stdscr)

        # Draw modal background (terminal default - clears shadow underneath)
        for i in range(modal_h):
            stdscr.addstr(start_y + i, start_x, " " * modal_w, modal_bg)

        # Draw outer border
        # Top border
        stdscr.addstr(start_y, start_x, "┏" + "━" * (modal_w - 2) + "┓", border_attr)
        # Bottom border
        stdscr.addstr(start_y + modal_h - 1, start_x, "┗" + "━" * (modal_w - 2) + "┛", border_attr)
        # Side borders
        for i in range(1, modal_h - 1):
            stdscr.addstr(start_y + i, start_x, "┃", border_attr)
            stdscr.addstr(start_y + i, start_x + modal_w - 1, "┃", border_attr)

        # Inner inset line (thin border inside)
        inner_y = start_y + 1
        inner_x = start_x + 1
        inner_w = modal_w - 2
        inner_h = modal_h - 2
        stdscr.addstr(inner_y, inner_x, "┌" + "─" * (inner_w - 2) + "┐", modal_bg)
        stdscr.addstr(inner_y + inner_h - 1, inner_x, "└" + "─" * (inner_w - 2) + "┘", modal_bg)
        for i in range(1, inner_h - 1):
            stdscr.addstr(inner_y + i, inner_x, "│", modal_bg)
            stdscr.addstr(inner_y + i, inner_x + inner_w - 1, "│", modal_bg)

        # Title (centered in top inset line)
        title = " Start Session "
        title_x = start_x + (modal_w - len(title)) // 2
        stdscr.addstr(inner_y, title_x, title, modal_bg | curses.A_BOLD)

        # Content area starts inside both borders (outer + inner)
        content_x = start_x + 3
        content_y = start_y + 3
        input_border = get_input_border_attr()

        # Computer/Project (read-only)
        stdscr.addstr(content_y, content_x, f"Computer: {self.computer}", modal_bg)
        stdscr.addstr(content_y + 1, content_x, f"Project:  {self.project_path[:45]}", modal_bg)

        # Agent selection (with border box)
        agent_y = content_y + 4  # Extra line after Project
        agent_box_w = 50
        stdscr.addstr(agent_y - 1, content_x, "┌" + "─" * (agent_box_w - 2) + "┐", input_border)
        stdscr.addstr(agent_y, content_x, "│", input_border)
        stdscr.addstr(agent_y, content_x + agent_box_w - 1, "│", input_border)
        stdscr.addstr(agent_y + 1, content_x, "└" + "─" * (agent_box_w - 2) + "┘", input_border)
        # Agent label
        stdscr.addstr(agent_y - 1, content_x + 2, " Agent ", modal_bg | curses.A_BOLD)
        for i, agent in enumerate(self.AGENTS):
            x = content_x + 2 + i * 15
            available = self._is_agent_available(agent)

            if i == self.selected_agent and available:
                marker = "●"
                attr = selection_bg | curses.A_BOLD if self.current_field == 0 else modal_bg
            elif available:
                marker = "○"
                attr = modal_bg
            else:
                # Unavailable - show grayed, non-selectable
                marker = "░"
                attr = modal_bg | curses.A_DIM
                stdscr.addstr(agent_y, x, f"{marker} {agent}", attr)
                continue

            stdscr.addstr(agent_y, x, f"{marker} {agent}", attr)

        # Mode selection (with border box)
        mode_y = agent_y + 3
        mode_box_w = 42
        stdscr.addstr(mode_y - 1, content_x, "┌" + "─" * (mode_box_w - 2) + "┐", input_border)
        stdscr.addstr(mode_y, content_x, "│", input_border)
        stdscr.addstr(mode_y, content_x + mode_box_w - 1, "│", input_border)
        stdscr.addstr(mode_y + 1, content_x, "└" + "─" * (mode_box_w - 2) + "┘", input_border)
        # Mode label
        stdscr.addstr(mode_y - 1, content_x + 2, " Mode ", modal_bg | curses.A_BOLD)
        for i, mode in enumerate(self.MODES):
            x = content_x + 2 + i * 12
            if i == self.selected_mode:
                marker = "●"
                attr = selection_bg | curses.A_BOLD if self.current_field == 1 else modal_bg
            else:
                marker = "○"
                attr = modal_bg
            stdscr.addstr(mode_y, x, f"{marker} {mode}", attr)

        # Prompt input (with border box)
        prompt_y = mode_y + 3
        prompt_box_w = 52
        stdscr.addstr(prompt_y - 1, content_x, "┌" + "─" * (prompt_box_w - 2) + "┐", input_border)
        stdscr.addstr(prompt_y, content_x, "│", input_border)
        stdscr.addstr(prompt_y, content_x + prompt_box_w - 1, "│", input_border)
        stdscr.addstr(prompt_y + 1, content_x, "└" + "─" * (prompt_box_w - 2) + "┘", input_border)
        # Prompt label
        stdscr.addstr(prompt_y - 1, content_x + 2, " Prompt ", modal_bg | curses.A_BOLD)
        prompt_attr = selection_bg if self.current_field == 2 else modal_bg
        prompt_text = self.prompt[:48] if self.prompt else ""
        cursor = "_" if self.current_field == 2 else ""
        stdscr.addstr(prompt_y, content_x + 2, prompt_text + cursor + " " * (48 - len(prompt_text)), prompt_attr)

        # Session ID input (with border box)
        session_y = prompt_y + 3
        session_box_w = 52
        stdscr.addstr(session_y - 1, content_x, "┌" + "─" * (session_box_w - 2) + "┐", input_border)
        stdscr.addstr(session_y, content_x, "│", input_border)
        stdscr.addstr(session_y, content_x + session_box_w - 1, "│", input_border)
        stdscr.addstr(session_y + 1, content_x, "└" + "─" * (session_box_w - 2) + "┘", input_border)
        stdscr.addstr(session_y - 1, content_x + 2, " Session ID ", modal_bg | curses.A_BOLD)
        session_attr = selection_bg if self.current_field == 3 else modal_bg
        session_text = self.native_session_id[:48] if self.native_session_id else ""
        session_cursor = "_" if self.current_field == 3 else ""
        stdscr.addstr(
            session_y,
            content_x + 2,
            session_text + session_cursor + " " * (48 - len(session_text)),
            session_attr,
        )

        # Actions (at bottom inside inner border)
        actions_y = start_y + modal_h - 3
        is_actions_focused = self.current_field == 4

        # Start button
        start_attr = selection_bg | curses.A_BOLD if is_actions_focused and self.selected_action == 0 else modal_bg
        stdscr.addstr(actions_y, content_x, "[Enter] Start", start_attr)

        # Spacing
        stdscr.addstr(actions_y, content_x + 14, "    ", modal_bg)

        # Cancel button
        cancel_attr = selection_bg | curses.A_BOLD if is_actions_focused and self.selected_action == 1 else modal_bg
        stdscr.addstr(actions_y, content_x + 18, "[Esc] Cancel", cancel_attr)


class ConfirmModal:
    """Simple confirmation modal dialog."""

    def __init__(self, title: str, message: str, details: list[str] | None = None):
        """Initialize confirmation modal.

        Args:
            title: Modal title
            message: Confirmation question
            details: Optional list of detail lines to show
        """
        self.title = title
        self.message = message
        self.details = details or []
        self.selected_action = 0  # 0=Yes (default), 1=No

    def run(self, stdscr: CursesWindow) -> bool:
        """Run modal event loop.

        Args:
            stdscr: Curses screen object

        Returns:
            True if confirmed (Y/Enter on Yes), False if cancelled (N/Esc/Enter on No)
        """
        while True:
            self._render(stdscr)
            key = stdscr.getch()

            if key == 27:  # Escape
                return False
            if key in (curses.KEY_ENTER, 10, 13):
                # Enter confirms the selected action
                return self.selected_action == 0  # True if Yes, False if No
            if key in (ord("y"), ord("Y")):
                return True
            if key in (ord("n"), ord("N")):
                return False
            if key == curses.KEY_LEFT:
                self.selected_action = 0  # Yes
            elif key == curses.KEY_RIGHT:
                self.selected_action = 1  # No
            elif key == ord("\t"):
                self.selected_action = (self.selected_action + 1) % 2

    def _render(self, stdscr: CursesWindow) -> None:
        """Render the modal.

        Args:
            stdscr: Curses screen object
        """
        height, width = stdscr.getmaxyx()

        # Modal dimensions (adjust based on content)
        detail_lines = len(self.details)
        modal_h = 9 + detail_lines  # borders + title + spacing + details + message + spacing + actions
        modal_w = max(50, len(self.message) + 8, max((len(d) for d in self.details), default=0) + 8)
        modal_w = min(modal_w, width - 4)  # Don't exceed screen

        start_y = (height - modal_h) // 2
        start_x = (width - modal_w) // 2

        # Modal background (z=2 layer - terminal default)
        modal_bg = get_layer_attr(2)
        border_attr = get_modal_border_attr()

        # Apply dim to existing screen content (true overlay, no redraw)
        _apply_dim_overlay(stdscr)

        # Draw modal background (terminal default - clears shadow underneath)
        for i in range(modal_h):
            try:
                stdscr.addstr(start_y + i, start_x, " " * modal_w, modal_bg)
            except curses.error:
                pass

        # Draw outer border
        try:
            stdscr.addstr(start_y, start_x, "┏" + "━" * (modal_w - 2) + "┓", border_attr)
            stdscr.addstr(start_y + modal_h - 1, start_x, "┗" + "━" * (modal_w - 2) + "┛", border_attr)
            for i in range(1, modal_h - 1):
                stdscr.addstr(start_y + i, start_x, "┃", border_attr)
                stdscr.addstr(start_y + i, start_x + modal_w - 1, "┃", border_attr)
        except curses.error:
            pass

        # Inner inset line
        inner_y = start_y + 1
        inner_x = start_x + 1
        inner_w = modal_w - 2
        inner_h = modal_h - 2
        try:
            stdscr.addstr(inner_y, inner_x, "┌" + "─" * (inner_w - 2) + "┐", modal_bg)
            stdscr.addstr(inner_y + inner_h - 1, inner_x, "└" + "─" * (inner_w - 2) + "┘", modal_bg)
            for i in range(1, inner_h - 1):
                stdscr.addstr(inner_y + i, inner_x, "│", modal_bg)
                stdscr.addstr(inner_y + i, inner_x + inner_w - 1, "│", modal_bg)
        except curses.error:
            pass

        # Title (centered in top inset line)
        title = f" {self.title} "
        title_x = start_x + (modal_w - len(title)) // 2
        try:
            stdscr.addstr(inner_y, title_x, title, modal_bg | curses.A_BOLD)
        except curses.error:
            pass

        # Content area
        content_x = start_x + 3
        content_y = start_y + 3

        # Details
        row = content_y
        for detail in self.details:
            try:
                stdscr.addstr(row, content_x, detail[: modal_w - 6], modal_bg)
            except curses.error:
                pass
            row += 1

        # Message (question)
        try:
            stdscr.addstr(row + 1, content_x, self.message[: modal_w - 6], modal_bg | curses.A_BOLD)
        except curses.error:
            pass

        # Actions (at bottom inside inner border) - with selection highlighting
        actions_y = start_y + modal_h - 3
        selection_bg = get_selection_attr(2)

        # Yes button (default selected)
        yes_attr = selection_bg | curses.A_BOLD if self.selected_action == 0 else modal_bg
        try:
            stdscr.addstr(actions_y, content_x, "[Enter] Yes", yes_attr)
        except curses.error:
            pass

        # Spacing
        try:
            stdscr.addstr(actions_y, content_x + 12, "    ", modal_bg)
        except curses.error:
            pass

        # No button
        no_attr = selection_bg | curses.A_BOLD if self.selected_action == 1 else modal_bg
        try:
            stdscr.addstr(actions_y, content_x + 16, "[N] No", no_attr)
        except curses.error:
            pass

        # Cancel hint (not selectable, just escape)
        try:
            stdscr.addstr(actions_y, content_x + 26, "[Esc] Cancel", modal_bg | curses.A_DIM)
        except curses.error:
            pass
