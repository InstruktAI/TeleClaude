"""Status footer widget."""

import curses
from datetime import datetime

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.widgets.agent_status import build_agent_render_spec


class Footer:
    """Persistent status footer showing agent availability and TTS toggle."""

    def __init__(
        self,
        agent_availability: dict[str, AgentAvailabilityInfo],
        tts_enabled: bool = False,
    ):
        self.agent_availability = agent_availability
        self.tts_enabled = tts_enabled
        self._tts_col_start: int = -1
        self._tts_col_end: int = -1

    def render(self, stdscr: object, row: int, width: int) -> None:
        """Render footer with right-aligned agent availability and TTS indicator."""
        # Build agent availability parts with shared status renderer
        agent_parts: list[tuple[str, int, bool]] = []  # (text, color_pair, bold)
        for agent in ["claude", "gemini", "codex"]:
            info = self.agent_availability.get(agent)
            until = info.unavailable_until if info else None
            countdown = self._format_countdown(until) if until else "?"
            spec = build_agent_render_spec(agent, info, unavailable_detail=countdown, show_unavailable_detail=True)
            agent_parts.append((spec.text, spec.color_pair_id, spec.bold))

        # TTS indicator: bright green when on, dim when off
        tts_text = "[TTS]"
        spacing = 2  # space between agent pills and TTS

        # Calculate total width needed for right alignment
        agents_width = sum(len(text) for text, _, _ in agent_parts) + (len(agent_parts) - 1) * 2
        total_text_width = agents_width + spacing + len(tts_text)
        max_width = max(0, width - 1)  # avoid last-column writes
        if max_width == 0:
            return

        # If overflow, drop leftmost agent parts until it fits
        if total_text_width > max_width:
            trimmed: list[tuple[str, int, bool]] = []
            used = spacing + len(tts_text)
            for text, color, bold in reversed(agent_parts):
                needed = len(text) if not trimmed else len(text) + 2
                if used + needed > max_width:
                    break
                trimmed.append((text, color, bold))
                used += needed
            agent_parts = list(reversed(trimmed))
            total_text_width = used

        start_col = max(0, max_width - total_text_width)

        # Render each agent with its color
        col = start_col
        try:
            for i, (text, color_pair_id, bold) in enumerate(agent_parts):
                if i > 0:
                    stdscr.addstr(row, col, "  ")  # type: ignore[attr-defined]
                    col += 2
                attr = curses.color_pair(color_pair_id)
                if bold:
                    attr |= curses.A_BOLD
                stdscr.addstr(row, col, text, attr)  # type: ignore[attr-defined]
                col += len(text)

            # Render TTS indicator
            col += spacing
            self._tts_col_start = col
            self._tts_col_end = col + len(tts_text)
            if self.tts_enabled:
                tts_attr = curses.color_pair(3) | curses.A_BOLD  # green + bold
            else:
                tts_attr = curses.A_DIM
            stdscr.addstr(row, col, tts_text, tts_attr)  # type: ignore[attr-defined]
        except curses.error:
            pass  # Screen too small

    def handle_click(self, col: int) -> bool:
        """Check if a click at the given column hits the TTS indicator.

        Returns True if the TTS region was clicked.
        """
        return self._tts_col_start <= col < self._tts_col_end

    def _format_countdown(self, until: str) -> str:
        """Format countdown string from ISO timestamp."""
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
