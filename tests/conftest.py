"""Pytest configuration for TeleClaude tests."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import pytest

from teleclaude.core.command_registry import reset_command_service
from teleclaude.core.event_bus import event_bus

try:
    import instrukt_ai_logging

    def _noop_configure_logging(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None

    instrukt_ai_logging.configure_logging = _noop_configure_logging  # type: ignore[assignment]
    logging.getLogger("teleclaude").handlers.clear()
    logging.getLogger().handlers.clear()
except Exception:
    pass


def pytest_collection_modifyitems(config, items):
    """Set per-marker timeouts: unit=1s, integration=5s."""
    for item in items:
        if "unit" in item.keywords:
            item.add_marker(pytest.mark.timeout(1))
        elif "integration" in item.keywords:
            item.add_marker(pytest.mark.timeout(5))


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """Ensure global event bus handlers do not leak across tests."""
    event_bus.clear()
    reset_command_service()
    yield
    event_bus.clear()
    reset_command_service()


@pytest.fixture(autouse=True)
def _isolate_tui_state(tmp_path: "Path", monkeypatch: pytest.MonkeyPatch):
    """Isolate TUI sticky state from user ~/.teleclaude/tui_state.json."""
    from teleclaude import paths
    from teleclaude.cli.tui import state_store
    from teleclaude.cli.tui.views import sessions as sessions_view

    tui_state = tmp_path / "tui_state.json"
    monkeypatch.setattr(paths, "TUI_STATE_PATH", tui_state)
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tui_state)
    monkeypatch.setattr(sessions_view, "TUI_STATE_PATH", tui_state)
    yield


# TUI Test Fixtures


def create_mock_session(
    session_id: str = "test-session-001",
    title: str = "Test Session",
    status: str = "active",
    computer: str = "test-computer",
    active_agent: str = "claude",
    thinking_mode: str = "slow",
    last_input: str | None = None,
    last_output: str | None = None,
    last_activity: str | None = None,
) -> dict[str, object]:  # guard: loose-dict
    """Create mock session data for testing.

    Args:
        session_id: Session ID
        title: Session title
        status: Session status
        computer: Computer name
        active_agent: Active agent name
        thinking_mode: Thinking mode
        last_input: Last input text
        last_output: Last output text
        last_activity: Last activity timestamp (ISO format)

    Returns:
        Session data dict
    """
    now = datetime.now(UTC).isoformat()
    return {
        "session_id": session_id,
        "title": title,
        "status": status,
        "computer": computer,
        "active_agent": active_agent,
        "thinking_mode": thinking_mode,
        "last_input_origin": "telegram",
        "project_path": "/test/path",
        "created_at": now,
        "last_activity": last_activity or now,
        "last_input": last_input,
        "last_output": last_output,
        "display_index": "1",
        "tmux_session_name": f"teleclaude-{session_id}",
    }


def create_mock_computer(
    name: str = "test-computer",
    status: str = "online",
) -> dict[str, object]:  # guard: loose-dict
    """Create mock computer data for testing.

    Args:
        name: Computer name
        status: Computer status

    Returns:
        Computer data dict
    """
    return {
        "name": name,
        "status": status,
        "user": "testuser",
        "host": "test.local",
    }


def create_mock_project(
    path: str = "/test/project",
    computer: str = "test-computer",
) -> dict[str, object]:  # guard: loose-dict
    """Create mock project data for testing.

    Args:
        path: Project path
        computer: Computer name

    Returns:
        Project data dict
    """
    return {
        "path": path,
        "computer": computer,
    }


class MockAPIClient:
    """Mock API client that can simulate push events."""

    def __init__(self) -> None:
        """Initialize mock API client."""
        self._event_handlers: list[Callable[[str, dict[str, object]], None]] = []  # guard: loose-dict
        self.sessions: list[dict[str, object]] = []  # guard: loose-dict
        self.projects: list[dict[str, object]] = []  # guard: loose-dict
        self.computers: list[dict[str, object]] = []  # guard: loose-dict

    def on_event(self, handler: Callable[[str, dict[str, object]], None]) -> None:  # guard: loose-dict
        """Register event handler (like real client).

        Args:
            handler: Event handler function
        """
        self._event_handlers.append(handler)

    def simulate_event(self, event: str, data: dict[str, object]) -> None:  # guard: loose-dict
        """Simulate a push event from backend.

        Args:
            event: Event type
            data: Event data
        """
        for handler in self._event_handlers:
            handler(event, data)

    def get_sessions(self) -> list[dict[str, object]]:  # guard: loose-dict
        """Return mock sessions.

        Returns:
            List of session dicts
        """
        return self.sessions

    async def create_session(
        self,
        computer: str | None = None,  # noqa: ARG002
        project_path: str | None = None,  # noqa: ARG002
        agent: str = "claude",  # noqa: ARG002
        thinking_mode: str = "slow",  # noqa: ARG002
        message: str | None = None,  # noqa: ARG002
    ) -> dict[str, object]:  # guard: loose-dict
        """Mock create session.

        Args:
            computer: Computer name
            project_path: Project directory
            agent: Agent name
            thinking_mode: Thinking mode
            message: Initial message

        Returns:
            Session creation result
        """
        return {
            "session_id": "new-session-001",
            "tmux_session_name": "teleclaude-new-session-001",
        }

    async def end_session(
        self,
        session_id: str,  # noqa: ARG002
        computer: str,  # noqa: ARG002
    ) -> bool:
        """Mock end session.

        Args:
            session_id: Session ID
            computer: Computer name

        Returns:
            Success status
        """
        return True
