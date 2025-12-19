from __future__ import annotations


def test_telegram_adapter_defines_agent_command_handlers() -> None:
    """UiAdapter._get_command_handlers expects _handle_{command} methods.

    Ensure we don't regress on /agent and /agent_resume support.
    """
    from teleclaude.adapters.telegram_adapter import TelegramAdapter

    assert hasattr(TelegramAdapter, "_handle_agent")
    assert hasattr(TelegramAdapter, "_handle_agent_resume")
