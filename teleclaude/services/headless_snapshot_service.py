"""Headless session transcript snapshot service."""

from __future__ import annotations

import time
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agents import AgentName
from teleclaude.core.models import Session
from teleclaude.utils.transcript import parse_session_transcript

logger = get_logger(__name__)


class HeadlessSnapshotService:
    """Emit transcript snapshots for headless sessions."""

    def __init__(self) -> None:
        self._last_headless_snapshot_fingerprint: dict[str, str] = {}

    async def send_snapshot(self, session: Session, *, reason: str, client: AdapterClient) -> None:
        """Send a transcript snapshot to UI for headless sessions."""
        transcript_path = session.native_log_file
        active_agent = session.active_agent
        agent_name = AgentName.from_str(active_agent)
        transcript_file = Path(transcript_path)
        try:
            stat = transcript_file.stat()
        except FileNotFoundError:
            logger.error(
                "Headless snapshot transcript missing",
                reason=reason,
                session=session.session_id[:8],
                transcript_path=transcript_path,
            )
            return

        fingerprint = f"{transcript_path}:{stat.st_size}:{stat.st_mtime_ns}"
        last_fingerprint = self._last_headless_snapshot_fingerprint.get(session.session_id)
        first_snapshot = last_fingerprint is None
        if last_fingerprint == fingerprint:
            logger.debug(
                "Headless snapshot skipped (duplicate)",
                reason=reason,
                session=session.session_id[:8],
            )
            return

        try:
            markdown_content = parse_session_transcript(
                transcript_path,
                session.title,
                agent_name=agent_name,
                tail_chars=0 if first_snapshot else UI_MESSAGE_MAX_CHARS,
                escape_triple_backticks=True,
            )
        except Exception as exc:
            logger.error(
                "Headless snapshot parse failed for session %s: %s",
                session.session_id[:8],
                exc,
            )
            return

        if not markdown_content.strip():
            logger.debug("Headless snapshot skipped (empty)", reason=reason, session=session.session_id[:8])
            return

        if first_snapshot:
            markdown_content = markdown_content[UI_MESSAGE_MAX_CHARS:]

        self._last_headless_snapshot_fingerprint[session.session_id] = fingerprint

        now_ts = time.time()
        try:
            await client.send_output_update(
                session,
                markdown_content,
                now_ts,
                now_ts,
                render_markdown=True,
            )
        except Exception as exc:
            logger.error(
                "Headless snapshot send failed for session %s: %s",
                session.session_id[:8],
                exc,
            )
