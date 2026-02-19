"""Modal dialogs built on Textual ModalScreen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from teleclaude.cli.models import AgentAvailabilityInfo
from teleclaude.cli.tui.messages import CreateSessionRequest


class ConfirmModal(ModalScreen[bool]):
    """Simple confirmation dialog with Yes/No buttons."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Vertical {
        width: 50;
        height: auto;
        max-height: 12;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    ConfirmModal Button {
        width: 1fr;
        margin: 1 1 0 0;
    }
    """

    def __init__(self, title: str, message: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title, id="confirm-title")
            yield Label(self._message, id="confirm-message")
            with Horizontal():
                yield Button("Yes", variant="error", id="confirm-yes")
                yield Button("No", variant="primary", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")


class StartSessionModal(ModalScreen[CreateSessionRequest | None]):
    """Modal for creating a new session with agent/mode/prompt fields."""

    DEFAULT_CSS = """
    StartSessionModal {
        align: center middle;
    }
    StartSessionModal > Vertical {
        width: 70;
        height: auto;
        max-height: 25;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    StartSessionModal Input {
        margin: 0 0 1 0;
    }
    StartSessionModal Select {
        margin: 0 0 1 0;
    }
    StartSessionModal Button {
        width: 1fr;
        margin: 1 1 0 0;
    }
    """

    AGENTS = [("Claude", "claude"), ("Gemini", "gemini"), ("Codex", "codex")]
    MODES = [("Fast", "fast"), ("Medium", "med"), ("Slow", "slow")]

    def __init__(
        self,
        computer: str,
        project_path: str,
        agent_availability: dict[str, AgentAvailabilityInfo] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._computer = computer
        self._project_path = project_path
        self._agent_availability = agent_availability or {}

    def compose(self) -> ComposeResult:
        # Filter to available agents
        available_agents = [
            (label, value)
            for label, value in self.AGENTS
            if self._agent_availability.get(value, None) is None or self._agent_availability[value].available
        ]
        if not available_agents:
            available_agents = self.AGENTS

        with Vertical():
            yield Label(f"New Session on {self._project_path.rsplit('/', 1)[-1]}", id="modal-title")
            yield Label("Agent:")
            yield Select(available_agents, value=available_agents[0][1], id="agent-select")
            yield Label("Thinking Mode:")
            yield Select(self.MODES, value="slow", id="mode-select")
            yield Label("Title (optional):")
            yield Input(placeholder="Session title", id="title-input")
            yield Label("Initial message (optional):")
            yield Input(placeholder="Message to send after session starts", id="message-input")
            with Horizontal():
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return

        agent_select = self.query_one("#agent-select", Select)
        mode_select = self.query_one("#mode-select", Select)
        title_input = self.query_one("#title-input", Input)
        message_input = self.query_one("#message-input", Input)

        request = CreateSessionRequest(
            computer=self._computer,
            project_path=self._project_path,
            agent=str(agent_select.value) if agent_select.value != Select.BLANK else None,
            thinking_mode=str(mode_select.value) if mode_select.value != Select.BLANK else None,
            title=title_input.value or None,
            message=message_input.value or None,
        )
        self.dismiss(request)
