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
from pathlib import Path
from typing import TypeVar, cast

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, TextArea

from teleclaude.api_models import AgentAvailabilityDTO
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import CreateSessionRequest, HandoffSessionRequest
from teleclaude.cli.tui.widgets.agent_status import build_agent_render_spec
from teleclaude.config.machine import config
from teleclaude.core.agents import get_enabled_agents
from teleclaude.core.command_dispatch import is_remote_target
from teleclaude.slug import SLUG_PATTERN
from teleclaude.types.todo_kind import ALL_DUMP_KINDS, TODO_KIND_CHOICES, TodoDumpKind

WIDGET_TYPE = TypeVar("WIDGET_TYPE", bound=Widget)
_CREATE_KIND_LABEL_ID = "kind-label"
_CREATE_KIND_LABEL = "Choose the todo kind:"
_CREATE_KIND_SELECT_ID = "kind-select"
_CREATE_KIND_SELECT_SELECTOR = "#kind-select"
_CREATE_KIND_SELECT_PROMPT = "Choose a kind"
_PRESET_KIND_LABEL_TEMPLATE = "Kind: {kind}"
_CREATE_KIND_REQUIRED_ERROR = "Choose a todo kind"


@dataclass
class NewProjectResult:
    """Result returned by NewProjectModal on success."""

    path: str


class AgentSelector(TelecMixin, Widget, can_focus=True):
    """Horizontal agent radio selector with agent-colored labels.

    Renders agents side by side: ● claude ✔ ○ gemini ✔ ○ codex ✘
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
        availability: dict[str, AgentAvailabilityDTO],
        allow_unavailable: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._agents = agents
        self._render_specs = [build_agent_render_spec(agent, availability.get(agent)) for agent in agents]
        self._selectable = [spec.selectable or allow_unavailable for spec in self._render_specs]
        selectable_indices = [index for index, selectable in enumerate(self._selectable) if selectable]
        if selectable_indices:
            self.selected = selectable_indices[0]
        # Per-cell rendered widths for click detection (one space separates cells).
        self._cell_widths: list[int] = []

    def render(self) -> Text:
        line = Text()
        cells: list[tuple[str, Style]] = []
        for i, agent in enumerate(self._agents):
            spec = self._render_specs[i]
            selectable = self._selectable[i] and not self.grayed_out

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

                indicator = spec.indicator
                style = Style(color=spec.color_pair_id, bold=spec.bold)

                # Highlight selected when focused
                if i == self.selected and self.has_focus:
                    style = Style(color=style.color, bold=True, reverse=True)

            cells.append((f" {marker} {agent} {indicator}", style))

        self._cell_widths = [len(cell) + 1 for cell, _style in cells]
        for i, (cell, style) in enumerate(cells):
            line.append(cell, style=style)
            if i < len(cells) - 1:
                line.append(" ")

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
        x = event.x
        idx = 0
        offset = 0
        for i, width in enumerate(self._cell_widths):
            offset += width
            if x < offset:
                idx = i
                break
        else:
            idx = len(self._cell_widths) - 1
        if 0 <= idx < len(self._agents) and self._selectable[idx]:
            self.selected = idx

    def watch_selected(self, _value: int) -> None:
        self.refresh()

    def watch_grayed_out(self, _value: bool) -> None:
        self.refresh()

    @property
    def selected_agent(self) -> str:
        return self._agents[self.selected]

    @property
    def selected_is_selectable(self) -> bool:
        """Return whether the current agent choice may start a new session."""
        return self._selectable[self.selected]


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

    _MODES = (("fast", "fast"), ("slow", "slow"), ("med", "med"), ("default", "default"))
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
            parent.on_session_id_type_changed()

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


class StartSessionModal(ModalScreen[CreateSessionRequest | HandoffSessionRequest | None]):
    """Session creation modal with thin border and titled field groups.

    Fields: Agent, Mode, Prompt, Session ID (with native/teleclaude toggle).
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
        agent_availability: dict[str, AgentAvailabilityDTO] | None = None,
        default_message: str | None = None,
        path_mode: bool = False,
        title: str | None = None,
        handoff_session_id: str | None = None,
        handoff_source_selection: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._computer = computer
        self._project_path = project_path
        self._agent_availability = agent_availability or {}
        self._default_message = default_message
        self._path_mode = path_mode
        self._title = title
        self._handoff_session_id = handoff_session_id
        self._handoff_source_selection = handoff_source_selection
        self._agents = tuple(get_enabled_agents())

    def compose(self) -> ComposeResult:
        project_name = self._project_path.rsplit("/", 1)[-1]

        with Vertical(id="modal-box") as box:
            box.border_title = self._title or "Start Session"

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
                        allow_unavailable=self._handoff_source_selection,
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

            with Vertical(id="session-id-group") as sg:
                sg.border_title = "Session ID (resume/revive)"
                yield SessionIdTypeSelector(id="session-id-type")
                yield Input(placeholder="Paste session ID to resume", id="session-id-input")

            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Start", variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        agent_selector = self._query_optional("#agent-selector", AgentSelector)
        if agent_selector is not None:
            agent_selector.focus()

    def _query_optional(self, selector: str, widget_type: type[WIDGET_TYPE]) -> WIDGET_TYPE | None:
        """Return a widget when it exists, or ``None`` for optional form sections."""
        try:
            return self.query_one(selector, widget_type)
        except Exception:
            return None

    def _get_focusable_groups(self) -> list[Widget]:
        """Ordered list of focusable widgets for up/down navigation."""
        groups: list[Widget] = []

        optional_widgets: list[Widget | None] = []
        if self._path_mode:
            optional_widgets.append(self._query_optional("#path-input", Input))
        if self._agents:
            agent_sel = self._query_optional("#agent-selector", AgentSelector)
            optional_widgets.append(agent_sel if agent_sel is not None and not agent_sel.grayed_out else None)
        optional_widgets.extend(
            [
                self._query_optional("#mode-selector", ModeSelector),
                self._query_optional("#message-input", Input),
                self._query_optional("#session-id-type", SessionIdTypeSelector),
                self._query_optional("#session-id-input", Input),
                self._query_optional("#create-btn", Button),
            ]
        )
        groups.extend(widget for widget in optional_widgets if widget is not None)
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

    def on_session_id_type_changed(self) -> None:
        """Called by SessionIdTypeSelector when toggle changes."""
        self._sync_agent_grayed()

    def _sync_agent_grayed(self) -> None:
        """Gray out agent selector when teleclaude session ID type is selected."""
        type_sel = self._query_optional("#session-id-type", SessionIdTypeSelector)
        agent_sel = self._query_optional("#agent-selector", AgentSelector)
        if type_sel is None or agent_sel is None:
            return
        is_teleclaude = type_sel.is_teleclaude
        agent_sel.grayed_out = is_teleclaude
        # Update border title to indicate grayed state
        agent_group = self._query_optional("#agent-group", Vertical)
        if agent_group is not None:
            agent_group.border_title = "Agent (n/a for teleclaude ID)" if is_teleclaude else "Agent"

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_create_session(self) -> None:
        """Enter from anywhere creates the session (unless in text input)."""
        focused = self.focused
        if isinstance(focused, Input):
            return
        self._do_create()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Enter while in an Input field submits the form."""
        self._do_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            self._do_create()

    def _resolve_project_path(self) -> str | None:
        """Validate and resolve the optional project-path input field.

        The filesystem check applies to this computer only; a path for another computer is
        sent as entered, and that computer decides.
        """
        if not self._path_mode:
            return self._project_path

        path_input = self.query_one("#path-input", Input)
        path_error = self.query_one("#path-error", Label)
        raw_path = path_input.value.strip()
        if not raw_path:
            path_error.update("Path is required")
            return None
        remote = is_remote_target(self._computer, config.computer.name)
        resolved = raw_path if remote else os.path.expanduser(raw_path)
        if not remote and not os.path.isdir(resolved):
            path_error.update("Path does not exist or is not a directory")
            return None
        path_error.update("")
        return resolved

    def _do_create(self) -> None:
        """Gather form values and dismiss with CreateSessionRequest."""
        if not self._agents:
            self.dismiss(None)
            return

        if self._handoff_session_id is not None:
            agent_sel = self.query_one("#agent-selector", AgentSelector)
            if agent_sel.selected_is_selectable:
                self.dismiss(HandoffSessionRequest(self._handoff_session_id, self._computer, agent_sel.selected_agent))
            return

        project_path = self._resolve_project_path()
        if project_path is None:
            return

        agent_sel = self.query_one("#agent-selector", AgentSelector)
        mode_sel = self.query_one("#mode-selector", ModeSelector)
        message_input = self.query_one("#message-input", Input)
        session_id_input = self.query_one("#session-id-input", Input)
        session_id_type = self.query_one("#session-id-type", SessionIdTypeSelector)

        if not session_id_type.is_teleclaude and not agent_sel.selected_is_selectable:
            return

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
            message=message_input.value or None if not session_id else None,
            revive_session_id=revive_session_id,
            native_session_id=native_session_id,
        )
        self.dismiss(request)


class NewProjectModal(ModalScreen[NewProjectResult | None]):
    """New project modal requesting only the folder path.

    Validates:
    - Path resolves to an absolute directory path.
    - Path must not duplicate an existing project on this computer.
    """

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
    ]

    def __init__(
        self,
        existing_paths: set[str] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._existing_paths = {
            str(Path(os.path.expandvars(path)).expanduser().resolve(strict=False)) for path in (existing_paths or set())
        }

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box") as box:
            box.border_title = "New Project"
            with Vertical(id="path-group") as pg:
                pg.border_title = "Folder"
                yield Input(placeholder="~/path/to/project", id="path-input")
                yield Label("", id="path-error")
            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Create", variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#path-input", Input).focus()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._do_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            self._do_create()

    def _do_create(self) -> None:
        path_input = self.query_one("#path-input", Input)
        path_error = self.query_one("#path-error", Label)

        raw_path = path_input.value.strip()

        # Validate path
        if not raw_path:
            path_error.update("Path is required")
            return
        resolved = str(Path(os.path.expandvars(raw_path)).expanduser().resolve(strict=False))
        if resolved in self._existing_paths:
            path_error.update("A project at this path already exists")
            return
        if os.path.exists(resolved) and not os.path.isdir(resolved):
            path_error.update("Path exists and is not a directory")
            return
        path_error.update("")

        self.dismiss(NewProjectResult(path=resolved))


@dataclass(frozen=True)
class CreateSlugResult:
    """Slug and kind selected for a new todo."""

    slug: str
    kind: TodoDumpKind


class CreateSlugModal(ModalScreen[CreateSlugResult | None]):
    """Slug creation modal — parameterized for todo or bug."""

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
    ]

    def __init__(
        self,
        title: str = "New Todo",
        placeholder: str = "my-new-todo",
        preset_kind: TodoDumpKind | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._placeholder = placeholder
        self._preset_kind = preset_kind

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box") as box:
            box.border_title = self._title
            yield Label("Enter a slug (lowercase, hyphens, numbers):", id="slug-label")
            yield Input(placeholder=self._placeholder, id="slug-input")
            if self._preset_kind is None:
                yield Label(_CREATE_KIND_LABEL, id=_CREATE_KIND_LABEL_ID)
                yield Select(
                    [(kind, kind) for kind in TODO_KIND_CHOICES],
                    prompt=_CREATE_KIND_SELECT_PROMPT,
                    allow_blank=True,
                    id=_CREATE_KIND_SELECT_ID,
                )
            else:
                yield Label(_PRESET_KIND_LABEL_TEMPLATE.format(kind=self._preset_kind), id=_CREATE_KIND_LABEL_ID)
            yield Label("", id="slug-error")
            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Create", variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#slug-input", Input).focus()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._do_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            self._do_create()

    def _do_create(self) -> None:
        slug_input = self.query_one("#slug-input", Input)
        error_label = self.query_one("#slug-error", Label)
        slug = slug_input.value.strip()

        if not slug:
            error_label.update("Slug is required")
            return
        if not SLUG_PATTERN.match(slug):
            error_label.update("Invalid: use lowercase, numbers, hyphens only")
            return

        kind = self._preset_kind
        if kind is None:
            selected_kind = self.query_one(_CREATE_KIND_SELECT_SELECTOR, Select).value
            if not isinstance(selected_kind, str) or selected_kind not in ALL_DUMP_KINDS:
                error_label.update(_CREATE_KIND_REQUIRED_ERROR)
                return
            kind = cast(TodoDumpKind, selected_kind)

        self.dismiss(CreateSlugResult(slug=slug, kind=kind))


class ContentInputModal(ModalScreen[str | None]):
    """Content input modal — prompts for a plain-text description."""

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
    ]

    def __init__(
        self,
        title: str = "Content",
        placeholder: str = "Enter description...",
        prompt: str = "Enter a description:",
        submit_label: str = "Create",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._title = title
        self._placeholder = placeholder
        self._prompt = prompt
        self._submit_label = submit_label

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box") as box:
            box.border_title = self._title
            yield Label(self._prompt, id="content-label")
            yield TextArea(placeholder=self._placeholder, id="content-input")
            yield Label("", id="content-error")
            with Horizontal(id="modal-actions"):
                yield Button(self._submit_label, variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#content-input", TextArea).focus()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            self._do_create()

    def _do_create(self) -> None:
        content_input = self.query_one("#content-input", TextArea)
        error_label = self.query_one("#content-error", Label)
        content = content_input.text.strip()
        if not content:
            error_label.update("Content is required")
            return
        self.dismiss(content)
