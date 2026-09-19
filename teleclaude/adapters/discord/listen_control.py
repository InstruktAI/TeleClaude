"""Persistent, message-bound ``Listen here`` Discord component."""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import discord as discord_module

    discord = discord_module
else:
    discord = cast(Any, importlib.import_module("discord"))

_PREFIX = "teleclaude:listen:v1:"
ListenCallback = Callable[[object, str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ListenComponentIdentity:
    session_id: str


def build_listen_custom_id(session_id: str) -> str:
    if not session_id.strip():
        raise ValueError("Listen control session id must not be empty")
    return f"{_PREFIX}{session_id}"


def parse_listen_custom_id(value: object) -> ListenComponentIdentity | None:
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        return None
    session_id = value.removeprefix(_PREFIX)
    return ListenComponentIdentity(session_id=session_id) if session_id else None


class ListenHereView(discord.ui.View):
    def __init__(self, session_id: str, on_listen: ListenCallback) -> None:
        super().__init__(timeout=None)
        button: Any = discord.ui.Button(
            label="Listen here",
            custom_id=build_listen_custom_id(session_id),
            style=discord.ButtonStyle.secondary,
        )

        async def callback(interaction: object) -> None:
            await on_listen(interaction, session_id)

        button.callback = callback
        self.add_item(button)
