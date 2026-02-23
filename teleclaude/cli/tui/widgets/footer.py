"""Status footer widget."""

import curses
import unicodedata
from datetime import datetime
from typing import Literal, TypeAlias, cast

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.theme import (
    AGENT_COLORS,
    PANE_THEMING_MODE_FULL,
    PANE_THEMING_MODE_OFF,
    get_agent_status_color_pair,
    get_pane_theming_mode_level,
    normalize_pane_theming_mode,
)
from teleclaude.cli.tui.widgets.agent_status import build_agent_render_spec

KnownAgent: TypeAlias = Literal["claude", "gemini", "codex"]


class Footer:
    """Persistent status footer showing agent availability and footer toggles."""

    def __init__(
        self,
        agent_availability: dict[str, AgentAvailabilityInfo],
        tts_enabled: bool = False,
        animation_mode: str = "periodic",
        pane_theming_mode: str = PANE_THEMING_MODE_FULL,
        pane_theming_agent: KnownAgent = "codex",
    ):
        self.agent_availability = agent_availability
        self.tts_enabled = tts_enabled
        self.animation_mode = animation_mode
        self.pane_theming_mode = pane_theming_mode
        self.pane_theming_agent = pane_theming_agent
        self._tts_col_start: int = -1
        self._tts_col_end: int = -1
        self._anim_col_start: int = -1
        self._anim_col_end: int = -1
        self._pane_theming_col_start: int = -1
        self._pane_theming_col_end: int = -1

    @staticmethod
    def _normalize_agent(agent: str) -> KnownAgent:
        """Normalize agent label and fail for unknown values."""
        normalized = agent.strip().lower()
        if normalized not in {"claude", "gemini", "codex"}:
            raise ValueError(f"Unknown agent for footer theming contract: {agent!r}")
        return cast(KnownAgent, normalized)

    def _format_pane_mode_cells(self, mode: str, *, agent: KnownAgent) -> list[tuple[str, int]]:
        """Return a multi-cell ASCII indicator pattern for pane coloring mode."""
        try:
            normalized = normalize_pane_theming_mode(mode)
        except ValueError:
            normalized = PANE_THEMING_MODE_OFF
            level = 0
        else:
            level = get_pane_theming_mode_level(normalized)
        try:
            safe_agent = self._normalize_agent(agent)
        except ValueError:
            safe_agent = "codex"

        outline_attr = get_agent_status_color_pair(safe_agent, muted=True) | curses.A_DIM
        ui_highlight_attr = AGENT_COLORS[safe_agent]["highlight"]
        agent_fill_attrs = tuple(AGENT_COLORS[agent_name]["normal"] for agent_name in ("claude", "gemini", "codex"))
        accent_fill = AGENT_COLORS["codex"]["highlight"]

        if level == 0:
            fill_attrs: tuple[int, ...] = ()
        elif level == 1:
            fill_attrs = (ui_highlight_attr,)
        elif level == 2:
            fill_attrs = (ui_highlight_attr, ui_highlight_attr)
        elif level == 3:
            fill_attrs = agent_fill_attrs
        else:
            fill_attrs = (*agent_fill_attrs, accent_fill)

        # Four indicator cells, each rendered as one box.
        # Level drives how many boxes are filled from left to right:
        # 0 = off, 1..4 = progressively stronger emphasis.
        cells: list[tuple[str, int]] = []
        for box_idx in range(4):
            if box_idx < len(fill_attrs):
                fill_attr = curses.color_pair(fill_attrs[box_idx])
            else:
                fill_attr = outline_attr
            cells.append(("◼" if box_idx < len(fill_attrs) else "◻", fill_attr))
        return cells

    def render(self, stdscr: object, row: int, width: int) -> None:
        """Render footer with left-aligned agent availability and right-aligned icons."""
        self._tts_col_start = -1
        self._tts_col_end = -1
        self._anim_col_start = -1
        self._anim_col_end = -1
        self._pane_theming_col_start = -1
        self._pane_theming_col_end = -1

        # Build agent availability parts with shared status renderer
        agent_parts: list[tuple[str, int, bool]] = []  # (text, color_pair, bold)
        for agent in ["claude", "gemini", "codex"]:
            info = self.agent_availability.get(agent)
            until = info.unavailable_until if info else None
            countdown = self._format_countdown(until) if until else "?"
            spec = build_agent_render_spec(agent, info, unavailable_detail=countdown, show_unavailable_detail=True)
            agent_parts.append((spec.text, spec.color_pair_id, spec.bold))

        # TTS indicator: bright green when on, dim when off
        tts_text = "🔊" if self.tts_enabled else "🔇"
        tts_width = self._display_width(tts_text)
        if tts_width <= 0:
            tts_text = "[TTS]"
            tts_width = len(tts_text)

        # Animation indicator
        anim_icons = {"off": "🚫 ", "periodic": "✨ ", "party": "🎉 "}
        anim_text = anim_icons.get(self.animation_mode, "✨ ")
        anim_width = self._display_width(anim_text)

        pane_mode_cells = self._format_pane_mode_cells(
            self.pane_theming_mode,
            agent=self.pane_theming_agent,
        )
        pane_mode_width = len(pane_mode_cells)

        max_width = max(0, width - 1)  # avoid last-column writes
        if max_width == 0:
            return

        icon_gap = 2
        icon_block_width = pane_mode_width + icon_gap + tts_width + icon_gap + anim_width
        icons_fit = icon_block_width <= max_width
        icon_block_start = max_width - icon_block_width if icons_fit else max_width
        agent_space = max(0, icon_block_start)

        # Render agent pills from left, clipping if we need to reserve icon space.
        col = 0
        try:
            for i, (text, color_pair_id, bold) in enumerate(agent_parts):
                if i > 0:
                    gap = 2
                    if col + gap > agent_space:
                        break
                    stdscr.addstr(row, col, "  ")  # type: ignore[attr-defined]
                    col += gap

                text_width = self._display_width(text)
                if col + text_width > agent_space:
                    break

                attr = curses.color_pair(color_pair_id)
                if bold:
                    attr |= curses.A_BOLD
                stdscr.addstr(row, col, text, attr)  # type: ignore[attr-defined]
                col += text_width

            # Render controls if they fit in the footer width.
            if not icons_fit:
                return

            self._pane_theming_col_start = icon_block_start
            self._pane_theming_col_end = icon_block_start + pane_mode_width

            col = icon_block_start
            for idx, (cell_text, cell_attr) in enumerate(pane_mode_cells):
                stdscr.addstr(row, col + idx, cell_text, cell_attr)  # type: ignore[attr-defined]

            self._tts_col_start = icon_block_start + pane_mode_width + icon_gap
            self._tts_col_end = self._tts_col_start + tts_width
            if self.tts_enabled:
                tts_attr = curses.color_pair(3) | curses.A_BOLD  # green + bold
            else:
                tts_attr = curses.A_DIM
            stdscr.addstr(row, self._tts_col_start, tts_text, tts_attr)  # type: ignore[attr-defined]

            anim_attr = curses.A_NORMAL if self.animation_mode != "off" else curses.A_DIM
            self._anim_col_start = self._tts_col_end + icon_gap
            self._anim_col_end = self._anim_col_start + anim_width
            stdscr.addstr(row, self._anim_col_start, anim_text, anim_attr)  # type: ignore[attr-defined]

        except curses.error:
            self._tts_col_start = -1
            self._tts_col_end = -1
            self._anim_col_start = -1
            self._anim_col_end = -1
            self._pane_theming_col_start = -1
            self._pane_theming_col_end = -1
            return

        # Ensure we never report invalid click regions when controls are not rendered.
        if self._pane_theming_col_start == -1 or self._tts_col_start == -1:
            self._pane_theming_col_start = -1
            self._pane_theming_col_end = -1
            self._tts_col_start = -1
            self._tts_col_end = -1
            self._anim_col_start = -1
            self._anim_col_end = -1

    def handle_click(self, col: int) -> str | None:
        """Check if a click at the given column hits a footer icon.

        Returns:
            "tts", "pane_theming_mode", "animation_mode", or None.
        """
        if self._pane_theming_col_start <= col < self._pane_theming_col_end:
            return "pane_theming_mode"
        if self._tts_col_start <= col < self._tts_col_end:
            return "tts"
        if self._anim_col_start <= col < self._anim_col_end:
            return "animation_mode"
        return None

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

    @staticmethod
    def _display_width(text: str) -> int:
        """Estimate terminal cell width for plain text and emoji."""
        width = 0
        for char in text:
            if unicodedata.combining(char):
                continue
            category = unicodedata.category(char)
            if category in {"Cf", "Mn", "Me"}:
                continue
            width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        return width
