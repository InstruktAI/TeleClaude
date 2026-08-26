"""Session display row with expand/collapse, agent colors, activity indicators."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.api_models import SessionDTO
from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import ChipFilterToggle, JumpToTodo
from teleclaude.cli.tui.theme import (
    CONNECTOR_COLOR,
    get_selection_fg_hex,
    resolve_color,
    resolve_preview_bg_hex,
    resolve_selection_bg_hex,
    resolve_style,
)
from teleclaude.cli.tui.utils.formatters import DATE_SUFFIX_WIDTH, format_time, truncate_text
from teleclaude.cli.tui.widgets.chip import resolve_person_chip
from teleclaude.core.session_utils import session_display_title
from teleclaude.slug import strip_slug_token

_DETAIL_PREFIX_OVERHEAD = 17  # │ + [HH:MM:SS] + label (" in: " / "out: ")

# Textual injects the content (column, row) of a click into the click's style
# meta under this key; the row maps it to the title line's sub-regions.
_CLICK_OFFSET_META = "offset"


class SessionRow(TelecMixin, Widget):
    """Multi-line expandable session row for the sessions tree."""

    class Pressed(Message):
        """Posted when a session row is clicked."""

        def __init__(self, session_row: SessionRow, *, shift: bool = False, meta: bool = False) -> None:
            super().__init__()
            self.session_row = session_row
            self.shift = shift
            self.meta = meta

    DEFAULT_CSS = """
    SessionRow {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    collapsed = reactive(True, layout=True)
    is_sticky = reactive(False)
    is_preview = reactive(False)
    input_highlight = reactive(False)
    output_highlight = reactive(False)
    activity_event = reactive("")  # hook event type, not persisted
    activity_text = reactive("", layout=True)  # tool name or summary
    last_output_summary = reactive("", layout=True)  # retained out-line text used by the render fallback
    skip_bottom_connector = reactive(False)
    is_last_child = reactive(False)

    def __init__(
        self,
        session: SessionDTO,
        display_index: str = "",
        depth: int = 0,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.display_index = display_index
        self.depth = depth
        # Click sub-regions on the title line (row 0), recorded each render: the
        # owner-chip cell span (and its email) and the work-slug cell span.
        self._chip_region: tuple[int, int] | None = None
        self._chip_email: str | None = None
        self._slug_region: tuple[int, int] | None = None
        # The active shared human filter, pushed by the view; the matching
        # person's chip renders inverted.
        self._active_human_filter: str | None = None

    @property
    def session_id(self) -> str:
        return self.session.session_id

    @property
    def agent(self) -> str | None:
        return self.session.active_agent

    @property
    def mode(self) -> str:
        return self.session.thinking_mode or "?"

    @property
    def status(self) -> str:
        return self.session.status or "idle"

    @property
    def _is_headless(self) -> bool:
        return self.status.startswith("headless") or not self.session.tmux_session_name

    @property
    def _content_width(self) -> int:
        """Available content width (widget width minus horizontal padding)."""
        return max(self.size.width - 2, 40)

    @property
    def _detail_text_limit(self) -> int:
        """Dynamic text limit for detail lines based on available width.

        When expanded, timestamps carry the ``-DD/MM`` date suffix, so the
        prefix grows by ``DATE_SUFFIX_WIDTH`` and the text budget shrinks to match.
        """
        overhead = _DETAIL_PREFIX_OVERHEAD + (0 if self.collapsed else DATE_SUFFIX_WIDTH)
        return min(75, max(20, self._content_width - self._connector_col - overhead))

    @property
    def _child_indent(self) -> str:
        """Leading indent before the badge — constant for all depths."""
        return " "

    @property
    def _connector_col(self) -> int:
        """Column for tree │ and └ connectors (depth-based, independent of badge indent).

        depth=2 → 2, depth=3 → 3, depth=4 → 5
        """
        raw = max(0, self.depth - 2) * 2
        return (raw if raw > 0 else 1) + 1

    def _tier(self, tier: str) -> str:
        """Resolve color tier, shifting one level down for headless sessions."""
        if not self._is_headless:
            return tier
        _shift = {"highlight": "normal", "normal": "muted", "muted": "subtle", "subtle": "subtle"}
        return _shift.get(tier, tier)

    def _get_row_style(self, *, selected: bool = False, previewed: bool = False) -> Style:
        """Determine the style for the title line based on selection state."""
        if selected:
            return Style(
                color=get_selection_fg_hex(),
                bgcolor=resolve_selection_bg_hex(self.agent),
                bold=True,
            )
        if previewed:
            return Style(
                color=get_selection_fg_hex(),
                bgcolor=resolve_preview_bg_hex(self.agent),
                bold=True,
            )
        return resolve_style(self.agent, self._tier("normal"))

    def _build_title_line(self, *, selected: bool = False, previewed: bool = False) -> Text:
        """Build the header: `[N] ▶ agent/mode "Title"` matching old TUI format."""
        line = Text(no_wrap=True)
        indent = self._child_indent
        if indent:
            line.append(indent)

        style = self._get_row_style(selected=selected, previewed=previewed)

        # Badge: sticky → reverse. Otherwise → tier-shifted normal.
        # Never inherits selection/preview background.
        if self.is_sticky:
            badge_style = Style(reverse=True, bold=selected)
        else:
            badge_style = resolve_style(self.agent, self._tier("normal"))
        line.append(f"[{self.display_index}]", style=badge_style)

        # Space between badge and chevron inherits the row style (shows highlight)
        line.append(" ", style=style)

        # Collapse indicator
        collapse_char = "\u25b6" if self.collapsed else "\u25bc"
        line.append(f"{collapse_char} ", style=style)

        # Agent/mode — show "shell" for sessions without an active agent
        agent_label = self.agent or "shell"
        line.append(f"{agent_label}/{self.mode}", style=style)

        # Owner chip — the owning human's initials right after the agent/mode
        # segment; the separating space sits outside the styled chip region.
        chip = resolve_person_chip(getattr(self.session, "human_email", None))
        self._chip_region = None
        self._chip_email = None
        if chip is not None:
            filtered = self._active_human_filter is not None and self._active_human_filter == chip.person_email
            # Selection/preview drives weight and snaps the chip to its extreme;
            # the active filter swaps its colors when the row is not highlighted.
            line.append(" ", style=style)
            chip_start = line.cell_len
            line.append(chip.initials, style=chip.style(selected=selected or previewed, inverted=filtered))
            self._chip_region = (chip_start, line.cell_len)
            self._chip_email = chip.person_email

        working_slug = getattr(self.session, "working_slug", None)
        self._slug_region = None

        # Title with the work-slug token removed (no quotes), then truncate to
        # fit. session_display_title applies the universal [HEADLESS] marker.
        title = session_display_title(self.session, fallback="(untitled)").splitlines()[0]
        title_text = strip_slug_token(title, working_slug)
        content_w = self._content_width
        slug_reserved = len(working_slug) + 1 if working_slug else 0
        avail = content_w - line.cell_len - slug_reserved - 1
        if 0 < avail < len(title_text):
            title_text = title_text[: max(1, avail - 1)] + "\u2026"
        if title_text:
            line.append(" ", style=style)
            line.append(title_text, style=style)

        # The work slug rendered once as a single highlighted span: a fill —
        # the agent subtle background under its highlight text — carried in
        # every state, with weight alone encoding selection. The two tiers are
        # opposite poles in each mode, so the span separates from the row and
        # from the terminal background identically in dark and light.
        if working_slug:
            slug_style = Style(
                color=resolve_color(self.agent, self._tier("highlight")),
                bgcolor=resolve_color(self.agent, self._tier("subtle")),
                bold=selected or previewed,
            )
            line.append(" ", style=style)
            slug_start = line.cell_len
            line.append(working_slug, style=slug_style)
            self._slug_region = (slug_start, line.cell_len)

        return line

    def _build_owner_line(self, *, connector_pad: str, detail_pad: str, connector_style: Style) -> Text | None:
        """Build the owner line when it should be visible."""
        human_email = getattr(self.session, "human_email", None)
        viewer_email = read_current_session_email()
        if human_email and viewer_email and human_email.lower() == viewer_email.lower():
            return None

        human_name = getattr(self.session, "human_name", None)
        human_role = getattr(self.session, "human_role", None)
        if human_name and human_role:
            line = Text(no_wrap=True)
            line.append(connector_pad)
            line.append("\u2502", style=connector_style)
            line.append(f"{detail_pad}{human_role}: ", style=resolve_style(self.agent, self._tier("muted")))
            line.append(str(human_name), style=resolve_style(self.agent, self._tier("normal")))
            return line

        return None

    def _build_summary_lines(self) -> list[Text]:
        """Build always-visible summary lines with owner, input, and output."""
        lines: list[Text] = []
        connector_pad = " " * self._connector_col
        detail_pad = ""
        connector_style = Style(color=CONNECTOR_COLOR)
        text_limit = self._detail_text_limit
        # Date suffix on activity timestamps only while the row is expanded.
        with_date = not self.collapsed

        base_style = resolve_style(self.agent, self._tier("normal"))
        highlight_style = resolve_style(self.agent, self._tier("highlight"))
        has_input_highlight = self.input_highlight
        has_output_highlight = self.output_highlight
        has_live_output_activity = self.activity_event == "pre_tool_use"
        input_style = highlight_style if has_input_highlight else base_style
        output_style = highlight_style if (has_output_highlight or has_live_output_activity) else base_style

        owner_line = self._build_owner_line(
            connector_pad=connector_pad,
            detail_pad=detail_pad,
            connector_style=connector_style,
        )
        if owner_line is not None:
            lines.append(owner_line)

        last_input = (self.session.last_input or "").strip()
        last_input_at = getattr(self.session, "last_input_at", None)
        if last_input:
            input_text = last_input.replace("\n", " ")[:text_limit]
            input_time = format_time(last_input_at, with_date=with_date)
            line3 = Text(no_wrap=True)
            line3.append(connector_pad)
            line3.append("\u2502", style=connector_style)
            line3.append(f"{detail_pad}[{input_time}]  in: {input_text}", style=input_style)
            lines.append(line3)

        if self.activity_event == "pre_tool_use" and self.activity_text:
            activity_time_str = format_time(self.session.last_activity, with_date=with_date)
            line4 = Text(no_wrap=True)
            line4.append(connector_pad)
            line4.append("\u2502", style=connector_style)
            line4.append(f"{detail_pad}[{activity_time_str}] out: ", style=output_style)
            line4.append(truncate_text(self.activity_text, text_limit), style=output_style)
            lines.append(line4)
        elif self.activity_event == "thinking" and self.activity_text:
            activity_time_str = format_time(self.session.last_activity, with_date=with_date)
            line4 = Text(no_wrap=True)
            line4.append(connector_pad)
            line4.append("\u2502", style=connector_style)
            thinking_text = self.activity_text.replace("\n", " ")[:text_limit]
            line4.append(f"{detail_pad}[{activity_time_str}] out: {thinking_text}", style=highlight_style)
            lines.append(line4)
        elif self.activity_event == "agent_stop" and self.activity_text:
            output_text = self.activity_text.replace("\n", " ")[:text_limit]
            summary_at = getattr(self.session, "last_output_summary_at", None) or self.session.last_activity
            output_time = format_time(summary_at, with_date=with_date)
            line4 = Text(no_wrap=True)
            line4.append(connector_pad)
            line4.append("\u2502", style=connector_style)
            line4.append(f"{detail_pad}[{output_time}] out: {output_text}", style=output_style)
            lines.append(line4)
        elif self.last_output_summary or self.session.last_output_summary:
            # Idle — persisted summary, NOT italic
            summary_at = getattr(self.session, "last_output_summary_at", None) or self.session.last_activity
            output_time = format_time(summary_at, with_date=with_date)
            output_text = (self.last_output_summary or self.session.last_output_summary or "").replace("\n", " ")[
                :text_limit
            ]
            line4 = Text(no_wrap=True)
            line4.append(connector_pad)
            line4.append("\u2502", style=connector_style)
            line4.append(f"{detail_pad}[{output_time}] out: {output_text}", style=output_style)
            lines.append(line4)

        return lines

    def _build_id_detail_line(self) -> Text:
        """Build the expanded technical id line."""
        connector_pad = " " * self._connector_col
        detail_pad = ""
        connector_style = Style(color=CONNECTOR_COLOR)
        id_style = resolve_style(self.agent, self._tier("normal"))
        created_time = format_time(getattr(self.session, "created_at", None), with_date=True)
        sid = self.session.session_id
        native_id = getattr(self.session, "native_session_id", None) or "-"
        line = Text(no_wrap=True)
        line.append(connector_pad)
        line.append("\u2502", style=connector_style)
        line.append(f"{detail_pad}[{created_time}] {sid}/{native_id}", style=id_style)
        return line

    def _build_connector_bottom(self) -> Text:
        """Build the bottom connector line.

        Uses \u2514 (corner) for last child in a subtree, \u251c (tee) otherwise.
        """
        connector_pad = " " * self._connector_col
        connector_style = Style(color=CONNECTOR_COLOR)
        run_len = max(self.size.width - self._connector_col - 1, 20)
        char = "\u2514" if self.is_last_child else "\u251c"
        line = Text(no_wrap=True)
        line.append(connector_pad)
        line.append(char, style=connector_style)
        line.append("-" * run_len, style=connector_style)
        return line

    def render(self) -> Text:
        is_selected = self.has_class("selected")
        is_previewed = self.is_preview

        result = self._build_title_line(selected=is_selected, previewed=is_previewed)
        if not self.collapsed:
            result.append("\n")
            result.append_text(self._build_id_detail_line())
        for summary in self._build_summary_lines():
            result.append("\n")
            result.append_text(summary)
        if not self.skip_bottom_connector:
            result.append("\n")
            result.append_text(self._build_connector_bottom())
        return result

    def on_click(self, event: Click) -> None:
        """Jump to the matching todo when the work-slug span is clicked.

        A click on the highlighted slug span (title line, row 0) jumps to that
        todo; any other click selects the row.
        """
        event.stop()
        if event.meta and event.shift:
            self.post_message(self.Pressed(self, shift=event.shift, meta=event.meta))
            return
        offset = event.style.meta.get(_CLICK_OFFSET_META) if event.style else None
        if isinstance(offset, tuple) and len(offset) == 2:
            column, row = int(offset[0]), int(offset[1])
            if row == 0:
                working_slug = getattr(self.session, "working_slug", None)
                if working_slug and self._slug_region and self._slug_region[0] <= column < self._slug_region[1]:
                    self.post_message(JumpToTodo(str(working_slug)))
                    return
                if self._chip_email and self._chip_region and self._chip_region[0] <= column < self._chip_region[1]:
                    self.post_message(ChipFilterToggle(self._chip_email))
                    return
        self.post_message(self.Pressed(self, shift=event.shift, meta=event.meta))

    def update_session(self, session: SessionDTO) -> None:
        """Update the underlying session data and trigger re-render."""
        self.session = session
        self.refresh(layout=True)

    def watch_collapsed(self, _value: bool) -> None:
        self.refresh()

    def watch_is_sticky(self, _value: bool) -> None:
        self.set_class(self.is_sticky, "sticky")
        self.refresh()

    def watch_is_preview(self, _value: bool) -> None:
        self.set_class(self.is_preview, "preview")
        self.refresh()

    def watch_input_highlight(self, _value: bool) -> None:
        self.refresh()

    def watch_output_highlight(self, _value: bool) -> None:
        self.refresh()

    def watch_activity_event(self, _value: str) -> None:
        self.refresh()

    def watch_activity_text(self, _value: str) -> None:
        self.refresh()

    def watch_last_output_summary(self, _value: str) -> None:
        self.refresh()
