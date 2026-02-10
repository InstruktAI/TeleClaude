"""Status footer widget."""

import curses
from datetime import datetime

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.theme import AGENT_COLORS


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
        """Render footer with right-aligned agent availability.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            width: Screen width
        """
        # Build agent availability parts with their colors
        agent_parts: list[tuple[str, int]] = []  # (text, color_pair)
        for agent in ["claude", "gemini", "codex"]:
            info = self.agent_availability.get(agent)
            available = info.available if info else True
            degraded = bool(info and (info.status == "degraded" or (info.reason or "").startswith("degraded")))

            # Get color pair for this agent (muted if unavailable, normal if available)
            agent_colors = AGENT_COLORS.get(agent, {"muted": 0, "normal": 0})
            color_pair_id = agent_colors["normal"] if available and not degraded else agent_colors["muted"]

            if degraded:
                agent_parts.append((f"{agent} ~", color_pair_id))
            elif available:
                agent_parts.append((f"{agent} ✔", color_pair_id))
            else:
                until = info.unavailable_until if info else None
                countdown = self._format_countdown(until) if until else "?"
                agent_parts.append((f"{agent} ✘ ({countdown})", color_pair_id))

        # Calculate total width needed for right alignment
        total_text_width = sum(len(text) for text, _ in agent_parts) + (len(agent_parts) - 1) * 2  # 2 spaces between
        max_width = max(0, width - 1)  # avoid last-column writes
        if max_width == 0:
            return

        # If overflow, drop leftmost parts until it fits (keep right aligned)
        if total_text_width > max_width:
            trimmed: list[tuple[str, int]] = []
            used = 0
            for text, color in reversed(agent_parts):
                needed = len(text) if not trimmed else len(text) + 2
                if used + needed > max_width:
                    break
                trimmed.append((text, color))
                used += needed
            agent_parts = list(reversed(trimmed))
            total_text_width = used

        start_col = max(0, max_width - total_text_width)  # right align within safe width

        # Render each agent with its color
        col = start_col
        try:
            for i, (text, color_pair_id) in enumerate(agent_parts):
                if i > 0:
                    # Add spacing between agents
                    stdscr.addstr(row, col, "  ")  # type: ignore[attr-defined]
                    col += 2
                stdscr.addstr(row, col, text, curses.color_pair(color_pair_id))  # type: ignore[attr-defined]
                col += len(text)
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
