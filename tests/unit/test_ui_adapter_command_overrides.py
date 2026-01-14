"""Unit tests for UI adapter command override mappings."""

from __future__ import annotations

import os

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.core.events import UiCommands


def test_ui_adapter_command_override_mapping() -> None:
    """Test that the agent_resume command is mapped to the adapter override."""
    assert "agent_resume" in UiCommands
    assert TelegramAdapter.COMMAND_HANDLER_OVERRIDES.get("agent_resume") == "_handle_agent_resume_command"
