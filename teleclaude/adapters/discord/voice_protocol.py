"""discord.py VoiceProtocol facade that keeps the Gateway in the Python adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from teleclaude.adapters.discord.voice_bridge_supervisor import VoiceBridgeSupervisor


class VoiceProtocol:
    """Forward Discord's voice Gateway events to the sidecar bridge.

    discord.py instantiates this object when a voice channel connects.  It
    intentionally owns no media socket; the sidecar translates the forwarded
    Gateway state into its own custom @discordjs/voice adapter.
    """

    def __init__(self, client: object, channel: object, *, supervisor: VoiceBridgeSupervisor) -> None:
        self.client = client
        self.channel = channel
        self._supervisor = supervisor

    async def connect(
        self, *, timeout: float, reconnect: bool, self_deaf: bool = False, self_mute: bool = False
    ) -> None:
        del timeout, reconnect, self_deaf, self_mute

    async def disconnect(self, *, force: bool = False) -> None:
        del force
        await self._supervisor.close()

    async def on_voice_state_update(self, data: Mapping[str, object]) -> None:
        await self._supervisor.forward_voice_state(data)

    async def on_voice_server_update(self, data: Mapping[str, object]) -> None:
        await self._supervisor.forward_voice_server(data)

    def cleanup(self) -> None:
        """Match discord.py's protocol lifecycle hook; supervisor close is async."""

    async def move_to(self, channel: object, *, timeout: float | None = None) -> None:
        del channel, timeout

    def is_connected(self) -> bool:
        return self._supervisor.is_open

    @property
    def guild(self) -> Any:
        return getattr(self.channel, "guild", None)
