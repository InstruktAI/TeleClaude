"""Status footer widget."""

import curses
from datetime import datetime

from teleclaude.cli.models import AgentAvailabilityInfo


class Footer:
    """Persistent status footer showing agent availability."""

    def __init__(
        self,
        agent_availability: dict[str, AgentAvailabilityInfo],
    ):
        """Initialize footer.

        Args:
            agent_availability: Dict mapping agent name to availability info
        """
        self.agent_availability = agent_availability

    def render(self, stdscr: object, row: int, width: int) -> None:
        """Render footer.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            width: Screen width
        """
        # Agent availability
        agent_parts: list[str] = []
        for agent in ["claude", "gemini", "codex"]:
            info = self.agent_availability.get(agent)
            available = info.available if info else True
            if available:
                agent_parts.append(f"{agent} ✓")
            else:
                until = info.unavailable_until if info else None
                countdown = self._format_countdown(until) if until else "?"
                agent_parts.append(f"{agent} ✗ ({countdown})")

        footer = " " + "  ".join(agent_parts)

        try:
            stdscr.addstr(row, 0, footer[: width - 1])  # type: ignore[attr-defined]
        except curses.error:
            pass  # Screen too small

    def _format_countdown(self, until: str) -> str:
        """Format countdown string from ISO timestamp.

        Args:
            until: ISO 8601 timestamp

        Returns:
            Human-readable countdown (e.g., "2d 5h", "3h 15m", "45m")
        """
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
            now = datetime.now(until_dt.tzinfo)
            delta = until_dt - now
            if delta.total_seconds() <= 0:
                return "soon"

            total_seconds = int(delta.total_seconds())
            days, remainder = divmod(total_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes = remainder // 60

            if days > 0:
                return f"{days}d {hours}h"
            if hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"
        except (ValueError, AttributeError):
            return "?"
