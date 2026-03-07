"""Modal dialogs built on Textual ModalScreen.

Visual design:
- Single thin border (solid ┌─┐) with title on top border
- Horizontal radio selections with ●/○ markers
- Agent-colored labels with availability indicators
- Labeled field groups with thin borders
"""

from __future__ import annotations

import os
from dataclasses import dataclass

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
from teleclaude.core.agents import get_enabled_agents


@dataclass
class NewProjectResult:
    """Result returned by NewProjectModal on success."""

    name: str
    description: str
    path: str


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
    When disabled, all agents render as grayed out.
    """

    DEFAULT_CSS = """
    AgentSelector {
        height: 1;
        width: 100%;
        padding: 0 1;
    }
    """

    selected = reactive(0)
    grayed_out = reactive(False)

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
            selectable = self._selectable[i] and not self.grayed_out
            available = info is None or info.available
            degraded = info is not None and (
                info.status == "degraded" or (isinstance(info.reason, str) and info.reason.startswith("degraded"))
            )

            if self.grayed_out:
                marker = "\u2591"  # ░
                indicator = ""
                style = Style(dim=True)
            else:
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
        if self.grayed_out:
            return
        available = [i for i, s in enumerate(self._selectable) if s]
        if not available:
            return
        try:
            pos = available.index(self.selected)
            self.selected = available[(pos - 1) % len(available)]
        except ValueError:
            self.selected = available[0]

    def action_next(self) -> None:
        if self.grayed_out:
            return
        available = [i for i, s in enumerate(self._selectable) if s]
        if not available:
            return
        try:
            pos = available.index(self.selected)
            self.selected = available[(pos + 1) % len(available)]
        except ValueError:
            self.selected = available[0]

    def on_click(self, event: Click) -> None:
        if self.grayed_out:
            return
        idx = event.x // self._cell_width
        if 0 <= idx < len(self._agents) and self._selectable[idx]:
            self.selected = idx

    def watch_selected(self, _value: int) -> None:
        self.refresh()

    def watch_grayed_out(self, _value: bool) -> None:
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


class SessionIdTypeSelector(TelecMixin, Widget, can_focus=True):
    """Toggle between native and teleclaude session ID types."""

    DEFAULT_CSS = """
    SessionIdTypeSelector {
        height: 1;
        width: 100%;
        padding: 0 1;
    }
    """

    selected = reactive(0)  # 0=native, 1=teleclaude

    BINDINGS = [
        ("left", "prev", "Previous"),
        ("right", "next", "Next"),
    ]

    _TYPES = (("native", "native"), ("teleclaude", "teleclaude"))
    _CELL_WIDTH = 16

    def render(self) -> Text:
        line = Text()
        for i, (_, label) in enumerate(self._TYPES):
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
        self.selected = (self.selected - 1) % len(self._TYPES)

    def action_next(self) -> None:
        self.selected = (self.selected + 1) % len(self._TYPES)

    def on_click(self, event: Click) -> None:
        idx = event.x // self._CELL_WIDTH
        if 0 <= idx < len(self._TYPES):
            self.selected = idx

    def watch_selected(self, _value: int) -> None:
        self.refresh()
        # Notify parent modal about type change
        parent = self.screen
        if isinstance(parent, StartSessionModal):
            parent._on_session_id_type_changed()

    @property
    def is_teleclaude(self) -> bool:
        return self.selected == 1


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
    """Session creation modal with thin border and titled field groups.

    Fields: Agent, Mode, Prompt, Title, Session ID (with native/teleclaude toggle).
    Up/down arrows navigate between field groups. Left/right within radio selectors.

    When a TeleClaude session ID is provided, agent selection is grayed out
    (the revive endpoint resolves the agent from the session record).
    When a native session ID is provided, agent_resume is used with the selected agent.
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
        ("enter", "create_session", "Create"),
        ("up", "focus_prev_group", "Up"),
        ("down", "focus_next_group", "Down"),
    ]

    def __init__(
        self,
        computer: str,
        project_path: str,
        agent_availability: dict[str, AgentAvailabilityInfo] | None = None,
        default_message: str | None = None,
        path_mode: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._computer = computer
        self._project_path = project_path
        self._agent_availability = agent_availability or {}
        self._default_message = default_message
        self._path_mode = path_mode
        self._agents = tuple(get_enabled_agents())

    def compose(self) -> ComposeResult:
        project_name = self._project_path.rsplit("/", 1)[-1]

        with Vertical(id="modal-box") as box:
            box.border_title = "Start Session"

            yield Label(f"Computer: {self._computer}", id="modal-computer")

            if self._path_mode:
                with Vertical(id="path-group") as pg:
                    pg.border_title = "Project Path"
                    yield Input(
                        value="",
                        placeholder="~/path/to/project",
                        id="path-input",
                    )
                    yield Label("", id="path-error")
            else:
                yield Label(f"Project:  {project_name}", id="modal-project")

            with Vertical(id="agent-group") as ag:
                ag.border_title = "Agent"
                if self._agents:
                    yield AgentSelector(
                        agents=self._agents,
                        availability=self._agent_availability,
                        id="agent-selector",
                    )
                else:
                    yield Label(
                        "No enabled agents in config.yml (set agents.<name>.enabled: true)",
                        id="agent-disabled-note",
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

            with Vertical(id="session-id-group") as sg:
                sg.border_title = "Session ID (resume/revive)"
                yield SessionIdTypeSelector(id="session-id-type")
                yield Input(placeholder="Paste session ID to resume", id="session-id-input")

            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Start", variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#agent-selector", AgentSelector).focus()

    def _get_focusable_groups(self) -> list[Widget]:
        """Ordered list of focusable widgets for up/down navigation."""
        groups: list[Widget] = []
        if self._path_mode:
            try:
                groups.append(self.query_one("#path-input", Input))
            except Exception:
                pass
        if self._agents:
            try:
                agent_sel = self.query_one("#agent-selector", AgentSelector)
                if not agent_sel.grayed_out:
                    groups.append(agent_sel)
            except Exception:
                pass
        try:
            groups.append(self.query_one("#mode-selector", ModeSelector))
        except Exception:
            pass
        try:
            groups.append(self.query_one("#message-input", Input))
        except Exception:
            pass
        try:
            groups.append(self.query_one("#title-input", Input))
        except Exception:
            pass
        try:
            groups.append(self.query_one("#session-id-type", SessionIdTypeSelector))
        except Exception:
            pass
        try:
            groups.append(self.query_one("#session-id-input", Input))
        except Exception:
            pass
        try:
            groups.append(self.query_one("#create-btn", Button))
        except Exception:
            pass
        return groups

    def action_focus_prev_group(self) -> None:
        """Move focus to previous field group (up arrow)."""
        groups = self._get_focusable_groups()
        if not groups:
            return
        focused = self.focused
        current_idx = -1
        for i, w in enumerate(groups):
            if w is focused:
                current_idx = i
                break
        if current_idx <= 0:
            groups[-1].focus()
        else:
            groups[current_idx - 1].focus()

    def action_focus_next_group(self) -> None:
        """Move focus to next field group (down arrow)."""
        groups = self._get_focusable_groups()
        if not groups:
            return
        focused = self.focused
        current_idx = -1
        for i, w in enumerate(groups):
            if w is focused:
                current_idx = i
                break
        if current_idx < 0 or current_idx >= len(groups) - 1:
            groups[0].focus()
        else:
            groups[current_idx + 1].focus()

    def _on_session_id_type_changed(self) -> None:
        """Called by SessionIdTypeSelector when toggle changes."""
        self._sync_agent_grayed()

    def _sync_agent_grayed(self) -> None:
        """Gray out agent selector when teleclaude session ID type is selected."""
        try:
            type_sel = self.query_one("#session-id-type", SessionIdTypeSelector)
            agent_sel = self.query_one("#agent-selector", AgentSelector)
        except Exception:
            return
        is_teleclaude = type_sel.is_teleclaude
        agent_sel.grayed_out = is_teleclaude
        # Update border title to indicate grayed state
        try:
            agent_group = self.query_one("#agent-group", Vertical)
            agent_group.border_title = "Agent (n/a for teleclaude ID)" if is_teleclaude else "Agent"
        except Exception:
            pass

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_create_session(self) -> None:
        """Enter from anywhere creates the session (unless in text input)."""
        focused = self.focused
        if isinstance(focused, Input):
            return
        self._do_create()

    def on_input_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002
        """Enter while in an Input field submits the form."""
        self._do_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            self._do_create()

    def _do_create(self) -> None:
        """Gather form values and dismiss with CreateSessionRequest."""
        if not self._agents:
            self.dismiss(None)
            return

        project_path = self._project_path

        if self._path_mode:
            path_input = self.query_one("#path-input", Input)
            path_error = self.query_one("#path-error", Label)
            raw_path = path_input.value.strip()
            if not raw_path:
                path_error.update("Path is required")
                return
            resolved = os.path.expanduser(raw_path)
            if not os.path.isdir(resolved):
                path_error.update("Path does not exist or is not a directory")
                return
            path_error.update("")
            project_path = resolved

        agent_sel = self.query_one("#agent-selector", AgentSelector)
        mode_sel = self.query_one("#mode-selector", ModeSelector)
        title_input = self.query_one("#title-input", Input)
        message_input = self.query_one("#message-input", Input)
        session_id_input = self.query_one("#session-id-input", Input)
        session_id_type = self.query_one("#session-id-type", SessionIdTypeSelector)

        session_id = session_id_input.value.strip()

        # Determine revive vs resume vs normal start
        revive_session_id: str | None = None
        native_session_id: str | None = None
        if session_id:
            if session_id_type.is_teleclaude:
                revive_session_id = session_id
            else:
                native_session_id = session_id

        request = CreateSessionRequest(
            computer=self._computer,
            project_path=project_path,
            agent=agent_sel.selected_agent,
            thinking_mode=mode_sel.selected_mode,
            title=title_input.value or None,
            message=message_input.value or None if not session_id else None,
            revive_session_id=revive_session_id,
            native_session_id=native_session_id,
        )
        self.dismiss(request)


class NewProjectModal(ModalScreen[NewProjectResult | None]):
    """New project modal with name, description, and path fields.

    Validates:
    - Path resolves via os.path.expanduser() and must be an existing directory.
    - Name and path must not duplicate an existing project on this computer.
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
    ]

    def __init__(
        self,
        existing_names: set[str] | None = None,
        existing_paths: set[str] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._existing_names = existing_names or set()
        self._existing_paths = existing_paths or set()

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box") as box:
            box.border_title = "New Project"
            with Vertical(id="name-group") as ng:
                ng.border_title = "Name"
                yield Input(placeholder="my-project", id="name-input")
                yield Label("", id="name-error")
            with Vertical(id="desc-group") as dg:
                dg.border_title = "Description (optional)"
                yield Input(placeholder="Short description", id="desc-input")
            with Vertical(id="path-group") as pg:
                pg.border_title = "Path"
                yield Input(placeholder="~/path/to/project", id="path-input")
                yield Label("", id="path-error")
            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Create", variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

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
        name_input = self.query_one("#name-input", Input)
        name_error = self.query_one("#name-error", Label)
        path_input = self.query_one("#path-input", Input)
        path_error = self.query_one("#path-error", Label)
        desc_input = self.query_one("#desc-input", Input)

        name = name_input.value.strip()
        raw_path = path_input.value.strip()
        description = desc_input.value.strip()

        # Validate name
        if not name:
            name_error.update("Name is required")
            return
        if name in self._existing_names:
            name_error.update(f"A project named '{name}' already exists")
            return
        name_error.update("")

        # Validate path
        if not raw_path:
            path_error.update("Path is required")
            return
        resolved = os.path.expanduser(raw_path)
        if not os.path.isdir(resolved):
            path_error.update("Path does not exist or is not a directory")
            return
        if resolved in self._existing_paths:
            path_error.update("A project at this path already exists")
            return
        path_error.update("")

        self.dismiss(NewProjectResult(name=name, description=description, path=resolved))


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
        from teleclaude.slug import SLUG_PATTERN

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
