"""Modal dialog widgets."""

import asyncio
import curses


class StartSessionModal:
    """Modal for starting a new session with agent/mode selection."""

    AGENTS = ["claude", "gemini", "codex"]
    MODES = ["fast", "slow", "med"]

    def __init__(
        self,
        computer: str,
        project_path: str,
        api: object,
        agent_availability: dict[str, dict[str, object]],
    ):
        """Initialize modal.

        Args:
            computer: Computer name
            project_path: Project directory path
            api: API client instance
            agent_availability: Agent availability status
        """
        self.computer = computer
        self.project_path = project_path
        self.api = api
        self.agent_availability = agent_availability

        # Find first available agent
        self.selected_agent = 0
        for i, agent in enumerate(self.AGENTS):
            if self._is_agent_available(agent):
                self.selected_agent = i
                break

        self.selected_mode = 1  # default: slow
        self.prompt = ""
        self.current_field = 0  # 0=agent, 1=mode, 2=prompt

    def _is_agent_available(self, agent: str) -> bool:
        """Check if agent is available.

        Args:
            agent: Agent name

        Returns:
            True if available
        """
        info = self.agent_availability.get(agent, {})
        return bool(info.get("available", True))

    def _get_available_agents(self) -> list[int]:
        """Get indices of available agents.

        Returns:
            List of available agent indices
        """
        return [i for i, a in enumerate(self.AGENTS) if self._is_agent_available(a)]

    def run(self, stdscr: object) -> dict[str, object] | None:
        """Run modal event loop.

        Args:
            stdscr: Curses screen object

        Returns:
            Session info or None if cancelled
        """
        while True:
            self._render(stdscr)
            key = stdscr.getch()  # type: ignore[attr-defined]

            if key == 27:  # Escape
                return None
            if key in (curses.KEY_ENTER, 10, 13):
                if self.current_field == 2 and self.prompt.strip():
                    return self._start_session()
                if self.current_field < 2:
                    self.current_field += 1
            elif key == ord("\t"):
                self.current_field = (self.current_field + 1) % 3
            elif key == curses.KEY_UP:
                self.current_field = max(0, self.current_field - 1)
            elif key == curses.KEY_DOWN:
                self.current_field = min(2, self.current_field + 1)
            elif key == curses.KEY_LEFT:
                self._select_prev()
            elif key == curses.KEY_RIGHT:
                self._select_next()
            elif self.current_field == 2:
                self._handle_prompt_key(key)

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

    def _handle_prompt_key(self, key: int) -> None:
        """Handle key input in prompt field.

        Args:
            key: Key code
        """
        if key in (curses.KEY_BACKSPACE, 127):
            self.prompt = self.prompt[:-1]
        elif 32 <= key <= 126:
            self.prompt += chr(key)

    def _start_session(self) -> dict[str, object]:
        """Start the session via API.

        Returns:
            Session creation result
        """
        agent = self.AGENTS[self.selected_agent]
        mode = self.MODES[self.selected_mode]

        result = asyncio.get_event_loop().run_until_complete(
            self.api.create_session(  # type: ignore[attr-defined]
                computer=self.computer,
                project_dir=self.project_path,
                agent=agent,
                thinking_mode=mode,
                message=self.prompt,
            )
        )
        return result  # type: ignore[no-any-return]

    def _render(self, stdscr: object) -> None:
        """Render the modal.

        Args:
            stdscr: Curses screen object
        """
        height, width = stdscr.getmaxyx()  # type: ignore[attr-defined]

        # Modal dimensions
        modal_h, modal_w = 15, 60
        start_y = (height - modal_h) // 2
        start_x = (width - modal_w) // 2

        # Draw border
        for i in range(modal_h):
            stdscr.addstr(start_y + i, start_x, " " * modal_w, curses.A_REVERSE)  # type: ignore[attr-defined]

        stdscr.addstr(start_y, start_x, "─ Start Session " + "─" * (modal_w - 16))  # type: ignore[attr-defined]

        # Computer/Project (read-only)
        stdscr.addstr(start_y + 2, start_x + 2, f"Computer: {self.computer}")  # type: ignore[attr-defined]
        stdscr.addstr(start_y + 3, start_x + 2, f"Project:  {self.project_path[:45]}")  # type: ignore[attr-defined]

        # Agent selection
        agent_y = start_y + 5
        stdscr.addstr(agent_y, start_x + 2, "Agent:")  # type: ignore[attr-defined]
        for i, agent in enumerate(self.AGENTS):
            x = start_x + 10 + i * 15
            available = self._is_agent_available(agent)

            if i == self.selected_agent and available:
                marker = "●"
                attr = curses.A_BOLD if self.current_field == 0 else 0
            elif available:
                marker = "○"
                attr = 0
            else:
                # Unavailable - show grayed with countdown
                info = self.agent_availability.get(agent, {})
                until = info.get("unavailable_until", "")
                marker = "░"
                agent_text = f"{agent} ({until})" if until else agent
                attr = curses.A_DIM
                stdscr.addstr(agent_y, x, f"{marker} {agent_text}", attr)  # type: ignore[attr-defined]
                continue

            stdscr.addstr(agent_y, x, f"{marker} {agent}", attr)  # type: ignore[attr-defined]

        # Mode selection
        mode_y = start_y + 7
        stdscr.addstr(mode_y, start_x + 2, "Mode:")  # type: ignore[attr-defined]
        for i, mode in enumerate(self.MODES):
            x = start_x + 10 + i * 12
            if i == self.selected_mode:
                marker = "●"
                attr = curses.A_BOLD if self.current_field == 1 else 0
            else:
                marker = "○"
                attr = 0
            stdscr.addstr(mode_y, x, f"{marker} {mode}", attr)  # type: ignore[attr-defined]

        # Prompt input
        prompt_y = start_y + 9
        stdscr.addstr(prompt_y, start_x + 2, "Prompt:")  # type: ignore[attr-defined]
        prompt_attr = curses.A_UNDERLINE if self.current_field == 2 else 0
        stdscr.addstr(prompt_y + 1, start_x + 2, self.prompt[:50] + "_", prompt_attr)  # type: ignore[attr-defined]

        # Actions
        stdscr.addstr(start_y + 12, start_x + 2, "[Enter] Start    [Esc] Cancel")  # type: ignore[attr-defined]
