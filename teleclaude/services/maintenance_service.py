"""Maintenance loops for cleanup and polling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core import polling_coordinator, session_cleanup, tmux_bridge, tmux_io
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agents import get_agent_command
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.session_utils import get_display_title_for_session, get_output_file, resolve_working_dir
from teleclaude.core.voice_assignment import get_voice_env_vars

logger = get_logger(__name__)


class MaintenanceService:
    """Background maintenance loops."""

    def __init__(
        self,
        *,
        client: AdapterClient,
        output_poller: OutputPoller,
        poller_watch_interval_s: float,
    ) -> None:
        self._client = client
        self._output_poller = output_poller
        self._poller_watch_interval_s = poller_watch_interval_s

    async def periodic_cleanup(self) -> None:
        """Clean up inactive sessions and orphans (runs forever)."""
        first_run = True
        while True:
            try:
                if not first_run:
                    await asyncio.sleep(3600)
                first_run = False

                await self._cleanup_inactive_sessions()
                await session_cleanup.cleanup_orphan_tmux_sessions()
                await session_cleanup.cleanup_orphan_workspaces()
                await session_cleanup.cleanup_orphan_mcp_wrappers()
                await db.cleanup_stale_voice_assignments()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in periodic cleanup: %s", exc, exc_info=True)

    async def poller_watch_loop(self) -> None:
        """Watch tmux foreground commands and ensure pollers are running when needed."""
        while True:
            try:
                await self._poller_watch_iteration()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in poller watch loop: %s", exc, exc_info=True)
            await asyncio.sleep(self._poller_watch_interval_s)

    async def _poller_watch_iteration(self) -> None:
        sessions = await db.get_active_sessions()
        if not sessions:
            return

        try:
            active_tmux_sessions = set(await tmux_bridge.list_tmux_sessions())
        except Exception as exc:
            logger.warning("Failed to list tmux sessions during poller watch: %s", exc)
            return

        for session in sessions:
            if await polling_coordinator.is_polling(session.session_id):
                continue

            if session.last_input_origin == InputOrigin.TELEGRAM.value:
                if (
                    not session.adapter_metadata
                    or not session.adapter_metadata.telegram
                    or not session.adapter_metadata.telegram.topic_id
                    or not session.output_message_id
                ):
                    try:
                        display_title = await get_display_title_for_session(session)
                        await self._client.ensure_ui_channels(session, display_title)
                    except Exception as exc:
                        logger.warning(
                            "Failed to ensure UI channels for session %s: %s",
                            session.session_id[:8],
                            exc,
                        )
                        continue

            if session.tmux_session_name not in active_tmux_sessions:
                recreated = await self.ensure_tmux_session(session)
                if not recreated:
                    continue

            if await tmux_bridge.is_pane_dead(session.tmux_session_name):
                recovered = await self.ensure_tmux_session(session)
                if not recovered:
                    continue

            await polling_coordinator.schedule_polling(
                session_id=session.session_id,
                tmux_session_name=session.tmux_session_name,
                output_poller=self._output_poller,
                adapter_client=self._client,
                get_output_file=self._get_output_file_path,
            )

    async def _cleanup_inactive_sessions(self) -> None:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=72)
        sessions = await db.list_sessions(include_closed=True, include_headless=True)

        for session in sessions:
            if not session.last_activity:
                logger.warning("No last_activity for session %s", session.session_id[:8])
                continue

            if session.last_activity < cutoff_time:
                logger.info(
                    "Cleaning up inactive session %s (inactive for %s)",
                    session.session_id[:8],
                    datetime.now(timezone.utc) - session.last_activity,
                )
                await session_cleanup.terminate_session(
                    session.session_id,
                    self._client,
                    reason="inactive_72h",
                    session=session,
                )
                logger.info("Session %s cleaned up (72h lifecycle)", session.session_id[:8])

    async def ensure_tmux_session(self, session: Session) -> bool:
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        env_vars = await self._build_tmux_env_vars(session.session_id)
        existed = await tmux_bridge.session_exists(session.tmux_session_name, log_missing=False)
        created = False
        if not existed:
            created = await tmux_bridge.ensure_tmux_session(
                name=session.tmux_session_name,
                working_dir=working_dir,
                session_id=session.session_id,
                env_vars=env_vars,
            )
            if not created:
                logger.warning("Failed to recreate tmux session for %s", session.session_id[:8])
                return False
        else:
            return True

        if session.active_agent and session.native_session_id:
            cmd = get_agent_command(
                agent=session.active_agent,
                thinking_mode=session.thinking_mode,
                exec=False,
                native_session_id=session.native_session_id,
            )

            wrapped_cmd = tmux_io.wrap_bracketed_paste(cmd, active_agent=session.active_agent)

            restored = await tmux_bridge.send_keys(
                session_name=session.tmux_session_name,
                text=wrapped_cmd,
                session_id=session.session_id,
                working_dir=working_dir,
                active_agent=session.active_agent,
            )
            if restored:
                logger.info(
                    "Restored agent %s for session %s (native=%s)",
                    session.active_agent,
                    session.session_id[:8],
                    session.native_session_id[:8],
                )
            else:
                logger.warning(
                    "Failed to restore agent %s for session %s",
                    session.active_agent,
                    session.session_id[:8],
                )
        return created

    async def _build_tmux_env_vars(self, session_id: str) -> dict[str, str]:
        env_vars: dict[str, str] = {}
        voice = await db.get_voice(session_id)
        if voice:
            env_vars.update(get_voice_env_vars(voice))
        return env_vars

    @staticmethod
    def _get_output_file_path(session_id: str) -> Path:
        return get_output_file(session_id)
