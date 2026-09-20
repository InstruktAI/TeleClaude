"""discord.py VoiceProtocol facade that keeps the Gateway in the Python adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from discord import VoiceProtocol as DiscordVoiceProtocol

from teleclaude.adapters.discord.voice_bridge_supervisor import VoiceBridgeSupervisor


class VoiceProtocol(DiscordVoiceProtocol):
    """Forward Discord's voice Gateway events to the sidecar bridge.

    discord.py instantiates this object when a voice channel connects.  It
    intentionally owns no media socket; the sidecar translates the forwarded
    Gateway state into its own custom @discordjs/voice adapter.
    """

    def __init__(self, client: object, channel: object, *, supervisor: VoiceBridgeSupervisor) -> None:
        super().__init__(client, channel)  # type: ignore[arg-type]
        self._supervisor = supervisor

    async def connect(
        self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False
    ) -> None:
        del timeout, reconnect, self_deaf, self_mute

    async def disconnect(self, *, force: bool = False) -> None:
        del force
        try:
            await self._supervisor.close()
            guild = self.guild
            change_voice_state = getattr(guild, "change_voice_state", None)
            if callable(change_voice_state):
                await cast(Callable[..., Awaitable[object]], change_voice_state)(channel=None)
        finally:
            self.cleanup()

    async def on_voice_state_update(self, data: Mapping[str, object]) -> None:
        await self._supervisor.forward_voice_state(data)

    async def on_voice_server_update(self, data: Mapping[str, object]) -> None:
        await self._supervisor.forward_voice_server(data)

    def cleanup(self) -> None:
        """Remove this protocol from discord.py's one-client-per-guild registry."""
        super().cleanup()

    async def move_to(self, channel: object, *, timeout: float | None = None) -> None:
        del timeout
        guild = self.guild
        change_voice_state = getattr(guild, "change_voice_state", None)
        if callable(change_voice_state):
            await cast(Callable[..., Awaitable[object]], change_voice_state)(channel=channel)
            self.channel = channel  # type: ignore[assignment]

    def is_connected(self) -> bool:
        return self._supervisor.is_open

    @property
    def guild(self) -> Any:
        return getattr(self.channel, "guild", None)
