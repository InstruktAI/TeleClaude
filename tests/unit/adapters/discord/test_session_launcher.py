from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from teleclaude.adapters.discord.session_launcher import SessionLauncherView

pytestmark = pytest.mark.unit


def test_session_launcher_view_builds_primary_buttons_for_enabled_agents() -> None:
    view = SessionLauncherView(enabled_agents=["alpha", "beta"], on_launch=AsyncMock())

    buttons = [(child.label, child.custom_id, child.style) for child in view.children]

    assert buttons == [
        ("Alpha", "launch:alpha", discord.ButtonStyle.primary),
        ("Beta", "launch:beta", discord.ButtonStyle.primary),
    ]


@pytest.mark.asyncio
async def test_session_launcher_view_callbacks_capture_the_matching_agent_name() -> None:
    on_launch = AsyncMock()
    view = SessionLauncherView(enabled_agents=["alpha", "beta"], on_launch=on_launch)
    interaction = SimpleNamespace(id="interaction-1")
    beta_button = next(child for child in view.children if child.custom_id == "launch:beta")

    await beta_button.callback(interaction)

    on_launch.assert_awaited_once_with(interaction, "beta")
