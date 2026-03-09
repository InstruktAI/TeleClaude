"""Background reconciliation worker for mirror generation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from instrukt_ai_logging import get_logger

from teleclaude.config import config

from ..utils.transcript_discovery import (
    TranscriptCandidate,
)
from ..utils.transcript_discovery import (
    discover_transcripts as _discover_transcripts,
)
from ..utils.transcript_discovery import (
    extract_project as _fallback_project,
)
from ..utils.transcript_discovery import (
    extract_session_id as _fallback_session_id,
)
from .generator import generate_mirror
from .store import get_mirror_state_by_transcript, get_session_context, resolve_db_path

logger = get_logger(__name__)

RECONCILE_INTERVAL_S = 300

__all__ = ["MirrorWorker", "TranscriptCandidate"]


class MirrorWorker:
    """Idempotent reconciliation loop for stale or missing mirrors."""

    def __init__(self, db: object | None = None, interval_s: int = RECONCILE_INTERVAL_S) -> None:
        self.db_path = resolve_db_path(db)
        self.interval_s = interval_s

    async def run_once(self) -> int:
        """Reconcile all known transcripts once."""
        state = get_mirror_state_by_transcript(self.db_path)
        transcripts = _discover_transcripts()
        total = len(transcripts)
        processed = 0
        if total == 0:
            logger.info("Mirror reconciliation: 0 transcripts discovered")
            return 0

        logger.info("Mirror reconciliation: 0/%d", total)
        for index, candidate in enumerate(transcripts, start=1):
            transcript_path = str(candidate.path)
            mtime_dt = datetime.fromtimestamp(candidate.mtime, tz=timezone.utc)
            existing = state.get(transcript_path)
            updated_at = existing[1] if existing else None
            parsed_updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00")) if updated_at else None
            if parsed_updated is not None and parsed_updated >= mtime_dt:
                continue

            context = get_session_context(transcript_path=transcript_path, db=self.db_path)
            session_id = context.session_id if context else _fallback_session_id(candidate.path, candidate.agent)
            project = context.project if context else _fallback_project(candidate.path, candidate.agent)
            computer = context.computer if context and context.computer else config.computer.name

            await generate_mirror(
                session_id=session_id,
                transcript_path=transcript_path,
                agent_name=candidate.agent,
                computer=computer,
                project=project,
                db=self.db_path,
            )
            processed += 1
            if index == total or index % 100 == 0:
                logger.info("Mirror reconciliation: %d/%d", index, total)

        logger.info("Mirror reconciliation complete: %d/%d processed", processed, total)
        return processed

    async def run(self) -> None:
        """Run reconciliation on startup and every interval until cancelled."""
        # TODO: re-enable after mirror-runtime-isolation is delivered
        logger.info("Mirror worker disabled (pending mirror-runtime-isolation)")
        return
        await self.run_once()
        while True:
            await asyncio.sleep(self.interval_s)
            await self.run_once()
