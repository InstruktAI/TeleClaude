"""Lifecycle owner for the private Python <-> Node Discord voice bridge."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.adapters.discord.voice_bridge_messages import (
    OUTBOUND_MESSAGES,
    CancelPlayback,
    InboundBridgeMessage,
    Join,
    Leave,
    OutboundBridgeMessage,
    PlayArtifact,
    ProtocolError,
    VoiceServerUpdate,
    VoiceStateUpdate,
)

logger = get_logger(__name__)

_BRIDGE_READY_TIMEOUT_S = 20.0
_BRIDGE_DIR = Path(__file__).with_name("voice_bridge")
_BRIDGE_ENTRYPOINT = _BRIDGE_DIR / "dist" / "main.js"
BridgeHandler = Callable[[OutboundBridgeMessage], Awaitable[None]]


class VoiceBridgeSupervisor:
    """Own one sidecar generation and expose its compact voice operations.

    The socketpair is created before spawn and the child inherits only its
    already-connected descriptor.  No port, token, or filesystem rendezvous is
    involved.  Every received message is validated before it reaches callers.
    """

    def __init__(self, handler: BridgeHandler) -> None:
        self._handler = handler
        self._generation = 0
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._recording_dir: tempfile.TemporaryDirectory[str] | None = None
        self._ready = asyncio.Event()
        self._closed = True

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def is_open(self) -> bool:
        return not self._closed and self._process is not None and self._process.returncode is None

    async def open(self, *, guild_id: int, channel_id: int, configured_user_id: str) -> None:
        """Spawn the sidecar, wait for its typed readiness, then join one room."""
        await self.close()
        if not _BRIDGE_ENTRYPOINT.is_file():
            raise RuntimeError(f"Discord voice sidecar is not built: {_BRIDGE_ENTRYPOINT}")

        parent_socket, child_socket = socket.socketpair()
        parent_socket.setblocking(False)
        child_socket.set_inheritable(True)
        self._generation += 1
        self._ready.clear()
        self._closed = False
        self._recording_dir = tempfile.TemporaryDirectory(prefix="teleclaude-discord-voice-")
        try:
            self._reader, self._writer = await asyncio.open_connection(sock=parent_socket)
            node_binary = shutil.which("node")
            if node_binary is None:
                raise RuntimeError("Node.js is required for the Discord voice sidecar")
            ffmpeg_binary = shutil.which("ffmpeg")
            if ffmpeg_binary is None:
                raise RuntimeError("FFmpeg is required for Discord voice playback")
            # Deliberately do not inherit the daemon environment: the child gets
            # only executable paths and its bounded recording identity, never credentials.
            child_env = {
                "PATH": os.defpath,
                "TELECLAUDE_CONFIGURED_USER_ID": configured_user_id,
                "TELECLAUDE_FFMPEG_BIN": ffmpeg_binary,
                "TELECLAUDE_VOICE_RECORDING_DIR": self._recording_dir.name,
            }
            self._process = await asyncio.create_subprocess_exec(
                node_binary,
                str(_BRIDGE_ENTRYPOINT),
                "--fd",
                str(child_socket.fileno()),
                "--generation",
                str(self._generation),
                pass_fds=(child_socket.fileno(),),
                cwd=str(_BRIDGE_DIR),
                env=child_env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except BaseException:
            await self.close()
            raise
        finally:
            child_socket.close()

        self._reader_task = asyncio.create_task(self._read_messages(), name="discord-voice-bridge-reader")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=_BRIDGE_READY_TIMEOUT_S)
            await self._send(
                Join(generation=self._generation, type="join", guildId=str(guild_id), channelId=str(channel_id))
            )
            logger.info("discord_voice_connection_opened", generation=self._generation, room_id=channel_id)
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """Idempotently leave the room and terminate the current sidecar."""
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            await self._send(Leave(generation=self._generation, type="leave"))
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._process.wait(), timeout=5)
            if self._process.returncode is None:
                self._process.kill()
                await self._process.wait()
        self._process = None
        self._reader = None
        self._writer = None
        self._reader_task = None
        if self._recording_dir is not None:
            self._recording_dir.cleanup()
            self._recording_dir = None
        logger.info("discord_voice_connection_closed", generation=self._generation)

    def owns_recording(self, path: Path) -> bool:
        """Return whether a sidecar recording remains inside this generation's root."""
        if self._recording_dir is None:
            return False
        try:
            path.resolve().relative_to(Path(self._recording_dir.name).resolve())
        except ValueError:
            return False
        return True

    async def forward_voice_state(self, payload: Mapping[str, object]) -> None:
        await self._send(
            VoiceStateUpdate(generation=self._generation, type="voice_state_update", payload=dict(payload))
        )

    async def forward_voice_server(self, payload: Mapping[str, object]) -> None:
        await self._send(
            VoiceServerUpdate(generation=self._generation, type="voice_server_update", payload=dict(payload))
        )

    async def play_artifact(self, path: Path) -> None:
        await self._send(PlayArtifact(generation=self._generation, type="play_artifact", path=str(path)))

    async def cancel_playback(self) -> None:
        if self._closed:
            return
        await self._send(CancelPlayback(generation=self._generation, type="cancel_playback"))

    async def _send(self, message: InboundBridgeMessage) -> None:
        writer = self._writer
        if self._closed or writer is None:
            return
        writer.write(message.model_dump_json().encode() + b"\n")
        await writer.drain()

    async def _read_messages(self) -> None:
        reader = self._reader
        if reader is None:
            return
        try:
            while not self._closed:
                line = await reader.readline()
                if not line:
                    break
                await self._handle_line(line)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError) as exc:
            logger.warning("bridge_protocol_error", reason="socket_error", error_type=type(exc).__name__)
        finally:
            if not self._closed:
                logger.warning("discord_voice_connection_closed", generation=self._generation, reason="sidecar_exited")
                await self._handler(
                    ProtocolError(generation=self._generation, type="protocol_error", message="sidecar_exited")
                )

    async def _handle_line(self, line: bytes) -> None:
        try:
            raw = json.loads(line)
            message = OUTBOUND_MESSAGES.validate_python(raw)
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
            logger.warning("bridge_protocol_error", reason="invalid_message", error_type=type(exc).__name__)
            return
        if message.generation != self._generation:
            logger.warning(
                "bridge_stale_generation_rejected",
                received_generation=message.generation,
                current_generation=self._generation,
            )
            return
        if message.type == "ready":
            self._ready.set()
            return
        if message.type == "protocol_error":
            logger.warning("bridge_protocol_error", generation=self._generation, reason="sidecar_rejected_message")
            await self._handler(cast(OutboundBridgeMessage, message))
            return
        await self._handler(cast(OutboundBridgeMessage, message))
