from __future__ import annotations


def test_telegram_adapter_exposes_agent_resume_command() -> None:
    from teleclaude.adapters.telegram_adapter import TelegramAdapter
    from teleclaude.core.events import UiCommands

    assert "agent_resume" in UiCommands
    assert hasattr(TelegramAdapter, "_handle_agent_resume")
