from __future__ import annotations


def test_ui_adapter_command_override_mapping() -> None:
    from teleclaude.adapters.telegram_adapter import TelegramAdapter
    from teleclaude.core.events import UiCommands

    assert "agent_resume" in UiCommands
    assert TelegramAdapter.COMMAND_HANDLER_OVERRIDES.get("agent_resume") == "_handle_agent_resume_command"
