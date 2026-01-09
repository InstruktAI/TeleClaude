"""Status footer widget."""

from datetime import datetime


class Footer:
    """Persistent status footer showing agent availability and last refresh."""

    def __init__(self, agent_availability: dict[str, dict[str, object]]):
        """Initialize footer.

        Args:
            agent_availability: Dict mapping agent name to availability info
        """
        self.agent_availability = agent_availability
        self.last_refresh = datetime.now()

    def update_availability(self, availability: dict[str, dict[str, object]]) -> None:
        """Update agent availability.

        Args:
            availability: New availability data
        """
        self.agent_availability = availability
        self.last_refresh = datetime.now()

    def render(self, stdscr: object, row: int, width: int) -> None:
        """Render footer.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            width: Screen width
        """
        agent_parts: list[str] = []
        for agent in ["claude", "gemini", "codex"]:
            info = self.agent_availability.get(agent, {"available": True})
            available = info.get("available", True)
            if available:
                agent_parts.append(f"{agent} ✓")
            else:
                until = info.get("unavailable_until")
                countdown = self._format_countdown(until) if until else "?"  # type: ignore[arg-type]
                agent_parts.append(f"{agent} ✗ ({countdown})")

        agents_str = "Agents: " + "  ".join(agent_parts)

        elapsed = (datetime.now() - self.last_refresh).seconds
        refresh_str = f"Last: {elapsed}s ago"

        footer = f"{agents_str} │ {refresh_str}"
        # Use addstr with type ignore for curses compatibility
        stdscr.addstr(row, 0, footer[:width])  # type: ignore[attr-defined]

    def _format_countdown(self, until: str) -> str:
        """Format countdown string from ISO timestamp.

        Args:
            until: ISO 8601 timestamp

        Returns:
            Formatted countdown (e.g., "2h 15m")
        """
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            now = datetime.now(until_dt.tzinfo)
            delta = until_dt - now
            if delta.total_seconds() <= 0:
                return "soon"
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes = remainder // 60
            if hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"
        except (ValueError, AttributeError):
            return "?"
