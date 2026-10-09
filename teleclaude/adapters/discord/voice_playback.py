"""Owner-local Discord-room reply playback and remote observation leases."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core import voice_focus
from teleclaude.core.db import db
from teleclaude.core.models import PeerCapabilityMissing
from teleclaude.core.reconciliation.feature_ids import SESSION_OBSERVED_STOP_FEATURE_ID
from teleclaude.tts.manager import TTSManager

if TYPE_CHECKING:
    from teleclaude.adapters.discord.voice_bridge_supervisor import VoiceBridgeSupervisor
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_OBSERVATION_TTL_S = 60
_OBSERVATION_RENEW_S = 30


class VoicePlayback:
    """Speak only a focused session's complete reply into the active room."""

    def __init__(self, client: AdapterClient, supervisor: VoiceBridgeSupervisor, active: Callable[[], bool]) -> None:
        self._client = client
        self._supervisor = supervisor
        self._active = active
        self._tts = TTSManager()
        self._observation_task: asyncio.Task[None] | None = None
        self._observed_session: str | None = None

    async def close(self) -> None:
        if self._observation_task is not None:
            self._observation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._observation_task
            self._observation_task = None
        self._observed_session = None
        await self._supervisor.cancel_playback()
        logger.info("voice_playback_cancelled")

    async def cancel_for_focus_change(self) -> None:
        """Stop speech immediately when conversation focus moves."""
        previous_session_id = self._observed_session
        await self._supervisor.cancel_playback()
        logger.info("voice_playback_cancelled", previous_session_id=previous_session_id)

    async def play_current(self, person_slug: str, session_id: str) -> None:
        cache = self._client.cache
        if cache is None or not self._active():
            return
        focus = await voice_focus.resolve(person_slug, cache.get_sessions())
        if focus.focused_session_id != session_id:
            return
        snapshot = next((item for item in cache.get_sessions() if item.session_id == session_id), None)
        if snapshot is None:
            return
        text: str | None = None
        version: str | None = None
        if not snapshot.computer or snapshot.computer in {LOCAL_COMPUTER, config.computer.name}:
            session = await db.get_session(session_id)
            if session is not None:
                text = session.last_output_raw
                version = session.last_output_stop_at.isoformat() if session.last_output_stop_at else None
        else:
            remote = await self._client.fetch_session_final_output(snapshot.computer, session_id)
            if isinstance(remote, PeerCapabilityMissing):
                logger.info("voice_reply_unavailable", session_id=session_id, reason="peer_capability")
                return
            text, version = remote.last_output_raw, remote.last_output_stop_at
        if not text or not version:
            return
        rendered = await self._tts.render_for_discord(session_id, text, version)
        if rendered is None:
            logger.info("voice_reply_unavailable", session_id=session_id, reason="render_failed")
            return
        await self._supervisor.cancel_playback()
        await self._supervisor.play_artifact(rendered.path)
        logger.info(
            "voice_reply_rendered",
            session_id=session_id,
            output_version=version,
            artifact_reused=rendered.artifact_reused,
        )
        logger.info("voice_reply_played", session_id=session_id, output_version=version)

    async def observe_focus(self, person_slug: str) -> None:
        cache = self._client.cache
        if cache is None or not self._active():
            return
        focus = await voice_focus.resolve(person_slug, cache.get_sessions())
        session_id = focus.focused_session_id
        if session_id is None:
            await self._stop_observation()
            return
        await self.observe_session(session_id)

    async def observe_session(self, session_id: str) -> None:
        """Observe one authoritative focused session without re-deriving stale cache state."""
        cache = self._client.cache
        if cache is None or not self._active():
            return
        snapshot = next((item for item in cache.get_sessions() if item.session_id == session_id), None)
        if snapshot is None or not snapshot.computer or snapshot.computer in {LOCAL_COMPUTER, config.computer.name}:
            await self._stop_observation()
            return
        peer = next(
            (item for item in await self._client.discover_peers() if item.get("name") == snapshot.computer), None
        )
        capabilities = peer.get("capability_set") if peer else None
        if not isinstance(capabilities, list) or SESSION_OBSERVED_STOP_FEATURE_ID not in capabilities:
            await self._stop_observation()
            logger.info("voice_reply_unavailable", session_id=session_id, reason="peer_capability")
            return
        if self._observed_session != session_id and self._observation_task is not None:
            self._observation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._observation_task
            self._observation_task = None
        self._observed_session = session_id
        if self._observation_task is None or self._observation_task.done():
            self._observation_task = asyncio.create_task(
                self._renew(snapshot.computer, session_id), name="voice-observation"
            )

    async def _stop_observation(self) -> None:
        if self._observation_task is not None:
            self._observation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._observation_task
        self._observation_task = None
        self._observed_session = None

    async def _renew(self, host: str, session_id: str) -> None:
        while self._active() and self._observed_session == session_id:
            await self._client.observe_session(host, session_id, _OBSERVATION_TTL_S)
            logger.info("voice_observation_renewed", session_id=session_id, host=host)
            await asyncio.sleep(_OBSERVATION_RENEW_S)
