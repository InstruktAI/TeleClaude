"""Discord persistent launcher view."""

from __future__ import annotations

import importlib
from typing import Awaitable, Callable

discord = importlib.import_module("discord")

LaunchCallback = Callable[[object, str], Awaitable[None]]


class SessionLauncherView(discord.ui.View):
    """Persistent launcher view with one button per enabled agent."""

    def __init__(self, *, enabled_agents: list[str], on_launch: LaunchCallback) -> None:
        super().__init__(timeout=None)
        for agent_name in enabled_agents:
            button = discord.ui.Button(
                label=agent_name.capitalize(),
                custom_id=f"launch:{agent_name}",
                style=discord.ButtonStyle.primary,
            )

            async def _callback(interaction: object, selected_agent: str = agent_name) -> None:
                await on_launch(interaction, selected_agent)

            button.callback = _callback
            self.add_item(button)
