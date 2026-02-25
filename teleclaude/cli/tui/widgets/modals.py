"""Modal dialogs built on Textual ModalScreen.

Visual design:
- Single thin border (solid ┌─┐) with title on top border
- Horizontal radio selections with ●/○ markers
- Agent-colored labels with availability indicators
- Labeled field groups with thin borders
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import CreateSessionRequest
from teleclaude.cli.tui.theme import resolve_style


def _is_agent_selectable(info: AgentAvailabilityInfo | None) -> bool:
    """Agent is selectable if available or degraded (manual override)."""
    if info is None:
        return True
    if info.available:
        return True
    if info.status == "degraded":
        return True
    if isinstance(info.reason, str) and info.reason.startswith("degraded"):
        return True
    return False


class AgentSelector(TelecMixin, Widget, can_focus=True):
    """Horizontal agent radio selector with agent-colored labels.

    Renders agents side by side: ● claude ✔  ○ gemini ✔  ○ codex ✘
    """

    DEFAULT_CSS = """
    AgentSelector {
        height: 1;
        width: 100%;
        padding: 0 1;
    }
    """

    selected = reactive(0)

    BINDINGS = [
        ("left", "prev", "Previous"),
        ("right", "next", "Next"),
    ]

    def __init__(
        self,
        agents: tuple[str, ...],
        availability: dict[str, AgentAvailabilityInfo],
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._agents = agents
        self._availability = availability
        self._selectable = [_is_agent_selectable(availability.get(a)) for a in agents]
        # Cell width per agent for click detection
        self._cell_width = 16

    def render(self) -> Text:
        line = Text()
        for i, agent in enumerate(self._agents):
            info = self._availability.get(agent)
            selectable = self._selectable[i]
            available = info is None or info.available
            degraded = info is not None and (
                info.status == "degraded" or (isinstance(info.reason, str) and info.reason.startswith("degraded"))
            )

            # Radio marker
            if i == self.selected and selectable:
                marker = "\u25cf"  # ●
            elif selectable:
                marker = "\u25cb"  # ○
            else:
                marker = "\u2591"  # ░

            # Status indicator
            if degraded:
                indicator = "~"
            elif available:
                indicator = "\u2714"  # ✔
            else:
                indicator = "\u2718"  # ✘

            # Agent color
            tier = "muted" if (not available or degraded) else "normal"
            style = resolve_style(agent, tier)

            # Highlight selected when focused
            if i == self.selected and self.has_focus:
                style = Style(color=style.color, bold=True, reverse=True)

            cell = f" {marker} {agent} {indicator} "
            line.append(cell.ljust(self._cell_width), style=style)

        return line

    def action_prev(self) -> None:
        available = [i for i, s in enumerate(self._selectable) if s]
        if not available:
            return
        try:
            pos = available.index(self.selected)
            self.selected = available[(pos - 1) % len(available)]
        except ValueError:
            self.selected = available[0]

    def action_next(self) -> None:
        available = [i for i, s in enumerate(self._selectable) if s]
        if not available:
            return
        try:
            pos = available.index(self.selected)
            self.selected = available[(pos + 1) % len(available)]
        except ValueError:
            self.selected = available[0]

    def on_click(self, event: Click) -> None:
        idx = event.x // self._cell_width
        if 0 <= idx < len(self._agents) and self._selectable[idx]:
            self.selected = idx

    def watch_selected(self, _value: int) -> None:
        self.refresh()

    @property
    def selected_agent(self) -> str:
        return self._agents[self.selected]


class ModeSelector(TelecMixin, Widget, can_focus=True):
    """Horizontal mode radio selector."""

    DEFAULT_CSS = """
    ModeSelector {
        height: 1;
        width: 100%;
        padding: 0 1;
    }
    """

    selected = reactive(1)  # Default: slow (index 1 in fast/slow/med)

    BINDINGS = [
        ("left", "prev", "Previous"),
        ("right", "next", "Next"),
    ]

    _MODES = (("fast", "fast"), ("slow", "slow"), ("med", "med"))
    _CELL_WIDTH = 12

    def render(self) -> Text:
        line = Text()
        for i, (_, label) in enumerate(self._MODES):
            if i == self.selected:
                marker = "\u25cf"  # ●
                if self.has_focus:
                    style = Style(bold=True, reverse=True)
                else:
                    style = Style(bold=True)
            else:
                marker = "\u25cb"  # ○
                style = Style()

            cell = f" {marker} {label} "
            line.append(cell.ljust(self._CELL_WIDTH), style=style)

        return line

    def action_prev(self) -> None:
        self.selected = (self.selected - 1) % len(self._MODES)

    def action_next(self) -> None:
        self.selected = (self.selected + 1) % len(self._MODES)

    def on_click(self, event: Click) -> None:
        idx = event.x // self._CELL_WIDTH
        if 0 <= idx < len(self._MODES):
            self.selected = idx

    def watch_selected(self, _value: int) -> None:
        self.refresh()

    @property
    def selected_mode(self) -> str:
        return self._MODES[self.selected][0]


class ConfirmModal(ModalScreen[bool]):
    """Confirmation dialog with thin border and title on border line."""

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
        ("n", "dismiss_no", "No"),
        ("y", "dismiss_yes", "Yes"),
    ]

    def __init__(self, title: str, message: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box") as box:
            box.border_title = self._title
            yield Label(self._message, id="confirm-message")
            yield Label("")
            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Yes", variant="primary", id="confirm-yes")
                yield Button("[N] No", id="confirm-no")
                yield Label("[Esc] Cancel", id="cancel-hint")

    def action_dismiss_modal(self) -> None:
        self.dismiss(False)

    def action_dismiss_no(self) -> None:
        self.dismiss(False)

    def action_dismiss_yes(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")


class StartSessionModal(ModalScreen[CreateSessionRequest | None]):
    """Session creation modal with thin border and titled field groups."""

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
        ("enter", "create_session", "Create"),
    ]

    _AGENTS = ("claude", "gemini", "codex")

    def __init__(
        self,
        computer: str,
        project_path: str,
        agent_availability: dict[str, AgentAvailabilityInfo] | None = None,
        default_message: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._computer = computer
        self._project_path = project_path
        self._agent_availability = agent_availability or {}
        self._default_message = default_message

    def compose(self) -> ComposeResult:
        project_name = self._project_path.rsplit("/", 1)[-1]

        with Vertical(id="modal-box") as box:
            box.border_title = "Start Session"

            yield Label(f"Computer: {self._computer}", id="modal-computer")
            yield Label(f"Project:  {project_name}", id="modal-project")

            with Vertical(id="agent-group") as ag:
                ag.border_title = "Agent"
                yield AgentSelector(
                    agents=self._AGENTS,
                    availability=self._agent_availability,
                    id="agent-selector",
                )

            with Vertical(id="mode-group") as mg:
                mg.border_title = "Mode"
                yield ModeSelector(id="mode-selector")

            with Vertical(id="prompt-group") as pg:
                pg.border_title = "Prompt"
                yield Input(
                    value=self._default_message or "",
                    placeholder="Message to send after start",
                    id="message-input",
                )

            with Vertical(id="title-group") as tg:
                tg.border_title = "Title"
                yield Input(placeholder="Session title (optional)", id="title-input")

            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Start", variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_create_session(self) -> None:
        """Enter from anywhere creates the session."""
        focused = self.focused
        if isinstance(focused, Input):
            return
        self._do_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            self._do_create()

    def _do_create(self) -> None:
        """Gather form values and dismiss with CreateSessionRequest."""
        agent_sel = self.query_one("#agent-selector", AgentSelector)
        mode_sel = self.query_one("#mode-selector", ModeSelector)
        title_input = self.query_one("#title-input", Input)
        message_input = self.query_one("#message-input", Input)

        request = CreateSessionRequest(
            computer=self._computer,
            project_path=self._project_path,
            agent=agent_sel.selected_agent,
            thinking_mode=mode_sel.selected_mode,
            title=title_input.value or None,
            message=message_input.value or None,
        )
        self.dismiss(request)


class CreateSlugModal(ModalScreen[str | None]):
    """Slug creation modal — parameterized for todo or bug."""

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
    ]

    def __init__(
        self,
        title: str = "New Todo",
        placeholder: str = "my-new-todo",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box") as box:
            box.border_title = self._title
            yield Label("Enter a slug (lowercase, hyphens, numbers):", id="slug-label")
            yield Input(placeholder=self._placeholder, id="slug-input")
            yield Label("", id="slug-error")
            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Create", variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#slug-input", Input).focus()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            self._do_create()

    def _do_create(self) -> None:
        from teleclaude.todo_scaffold import SLUG_PATTERN

        slug_input = self.query_one("#slug-input", Input)
        error_label = self.query_one("#slug-error", Label)
        slug = slug_input.value.strip()

        if not slug:
            error_label.update("Slug is required")
            return
        if not SLUG_PATTERN.match(slug):
            error_label.update("Invalid: use lowercase, numbers, hyphens only")
            return

        self.dismiss(slug)
