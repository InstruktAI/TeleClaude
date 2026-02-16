"""Session memory extraction job.

Finds sessions needing processing (where help_desk_processed_at is
older than last_activity or NULL), reads transcripts since the last extraction,
and extracts personal + business memories plus actionable items.

Memory extraction runs as an idempotent job with two scopes:
- **Personal memories** are identity-scoped (tied to the user via identity_key).
- **Business memories** are project-scoped (shared across the project).

Actionable items (e.g. follow-ups, feature requests, bugs) are published to
the internal channels subsystem for downstream routing.

Consumers include help desk customer sessions, member personal assistant
sessions, and any future long-lived session type with an identity_key.

Integration:
- Scheduled via teleclaude.yml (default: every 30 minutes).
- Queries sessions from the core database.
- Saves memories via the MemoryStore.
- Publishes actionable items via the channels publisher.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from jobs.base import Job, JobResult

logger = logging.getLogger(__name__)

# Ensure repo root is in path for imports
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class SessionMemoryExtractionJob(Job):
    """Extract memories and actionable items from long-lived sessions.

    Scans for sessions where ``help_desk_processed_at`` is older than
    ``last_activity`` (or NULL), reads the transcript delta, and runs
    AI-powered extraction for personal memories, business memories, and
    actionable items. Works for any session with a human_role — customers,
    members, and other long-lived session types.
    """

    name = "session-memory-extraction"

    def run(self) -> JobResult:
        """Execute memory extraction for all pending sessions."""
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._run_async())
        finally:
            loop.close()

    async def _run_async(self) -> JobResult:
        """Async implementation of the extraction pipeline."""
        sessions = await self._find_sessions_needing_extraction()

        if not sessions:
            return JobResult(
                success=True,
                message="No sessions need extraction",
                items_processed=0,
            )

        processed = 0
        errors: list[str] = []

        for session in sessions:
            try:
                await self._process_session(session)
                processed += 1
            except Exception as e:
                sid = session.session_id[:8] if hasattr(session, "session_id") else "unknown"
                errors.append(f"session {sid}: {e}")

        success = len(errors) == 0
        message = (
            f"Extracted {processed} session(s)"
            if success
            else f"Extracted {processed} session(s) with {len(errors)} error(s)"
        )
        return JobResult(
            success=success,
            message=message,
            items_processed=processed,
            errors=errors if errors else None,
        )

    async def _find_sessions_needing_extraction(self) -> list[object]:
        """Find sessions where help_desk_processed_at < last_activity or is NULL.

        Returns sessions with a human_role that have unprocessed transcript
        content. This covers customer sessions, member sessions, and any
        other long-lived session type.
        """
        from teleclaude.core.db import db

        all_sessions = await db.list_sessions(include_closed=True)
        pending = []
        for session in all_sessions:
            # Any session with a human_role is eligible for extraction
            if not getattr(session, "human_role", None):
                continue
            last_activity = getattr(session, "last_activity", None)
            if not last_activity:
                continue
            processed_at = getattr(session, "help_desk_processed_at", None)
            if processed_at is None or processed_at < last_activity:
                pending.append(session)
        return pending

    async def _process_session(self, session: object) -> None:
        """Process a single session: extract memories and actionable items."""
        session_id: str = session.session_id  # type: ignore[attr-defined]
        last_extraction_at = getattr(session, "last_memory_extraction_at", None)

        # Step 1: Read transcript since last extraction
        transcript = await self._read_transcript_delta(session_id, since=last_extraction_at)
        if not transcript:
            return

        # Step 2: Derive identity key for personal memory scoping
        identity_key = self._resolve_identity_key(session)

        # Step 3: Extract personal memories (identity-scoped)
        await self._extract_personal_memories(transcript, identity_key, session)

        # Step 4: Extract business memories (project-scoped)
        await self._extract_business_memories(transcript, session)

        # Step 5: Extract actionable items and publish to channels
        await self._extract_and_publish_actionable_items(transcript, session)

        # Step 6: Update bookkeeping timestamps
        now = datetime.now(timezone.utc)
        await self._update_bookkeeping(session_id, now)

        # Step 7: Inject /compact into the session's tmux pane
        tmux_name = getattr(session, "tmux_session_name", None)
        if tmux_name:
            try:
                from teleclaude.core.tmux_bridge import send_keys_existing_tmux

                delivered = await send_keys_existing_tmux(tmux_name, "/compact", send_enter=True)
                if delivered:
                    logger.info("Injected /compact into session %s (tmux: %s)", session_id[:8], tmux_name)
                else:
                    logger.warning("Tmux session %s not found for /compact injection", tmux_name)
            except Exception:  # noqa: BLE001 - best-effort compact injection
                logger.warning("Failed to inject /compact into session %s", session_id[:8])

    async def _read_transcript_delta(
        self,
        session_id: str,
        since: datetime | None,
    ) -> str | None:
        """Read session transcript content since the given timestamp.

        Returns the transcript text, or None if no new content exists.
        """
        # TODO: Read native transcript file for the session.
        # Use teleclaude session data retrieval with since_timestamp filter.
        # For now this is a skeleton — the actual transcript reading will use
        # the session's claude_session_file or tmux pane capture.
        _ = session_id, since
        return None

    def _resolve_identity_key(self, session: object) -> str | None:
        """Derive the identity key from session adapter metadata."""
        from teleclaude.core.identity import derive_identity_key
        from teleclaude.core.models import SessionAdapterMetadata

        adapter_metadata_raw = getattr(session, "adapter_metadata", None)
        if adapter_metadata_raw is None:
            return None
        if isinstance(adapter_metadata_raw, str):
            adapter_metadata = SessionAdapterMetadata.from_json(adapter_metadata_raw)
        else:
            adapter_metadata = adapter_metadata_raw
        return derive_identity_key(adapter_metadata)

    async def _extract_personal_memories(
        self,
        transcript: str,
        identity_key: str | None,
        session: object,
    ) -> None:
        """Extract personal memories from transcript and save with identity scope.

        Personal memories capture user-specific information: preferences,
        communication style, history, and relationship context.
        """
        # TODO: Use AI agent to analyse transcript and extract personal memories.
        # For each extracted memory, save via MemoryStore with identity_key set:
        #
        #   from teleclaude.memory.store import MemoryStore
        #   from teleclaude.memory.types import ObservationInput, ObservationType
        #   store = MemoryStore()
        #   await store.save_observation(ObservationInput(
        #       text=memory_text,
        #       title=memory_title,
        #       project=project_name,
        #       type=ObservationType.CONTEXT,
        #       identity_key=identity_key,
        #   ))
        _ = transcript, identity_key, session

    async def _extract_business_memories(
        self,
        transcript: str,
        session: object,
    ) -> None:
        """Extract business memories from transcript and save at project scope.

        Business memories capture product feedback, feature requests, common
        pain points, and domain knowledge shared by users.
        """
        # TODO: Use AI agent to analyse transcript and extract business memories.
        # Save via MemoryStore WITHOUT identity_key (project-scoped):
        #
        #   from teleclaude.memory.store import MemoryStore
        #   from teleclaude.memory.types import ObservationInput, ObservationType
        #   store = MemoryStore()
        #   await store.save_observation(ObservationInput(
        #       text=memory_text,
        #       title=memory_title,
        #       project=project_name,
        #       type=ObservationType.DISCOVERY,
        #   ))
        _ = transcript, session

    async def _extract_and_publish_actionable_items(
        self,
        transcript: str,
        session: object,
    ) -> None:
        """Extract actionable items from transcript and publish to channels.

        Actionable items include follow-up tasks, bug reports, feature requests,
        and escalation triggers. Each item is published to the appropriate
        internal channel for downstream routing.
        """
        # TODO: Use AI agent to identify actionable items from transcript.
        # For each item, publish to the channels subsystem:
        #
        #   from teleclaude.channels.publisher import channel_key, publish
        #   from teleclaude.config import config
        #   redis = get_redis()
        #   key = channel_key(project, "actionable-items")
        #   await publish(redis, key, {
        #       "type": item_type,  # e.g. "bug", "feature-request", "follow-up"
        #       "summary": item_summary,
        #       "session_id": session.session_id,
        #       "identity_key": identity_key,
        #   })
        _ = transcript, session

    async def _update_bookkeeping(self, session_id: str, now: datetime) -> None:
        """Update session timestamps after successful extraction."""
        from teleclaude.core.db import db

        await db.update_session(
            session_id,
            last_memory_extraction_at=now.isoformat(),
            help_desk_processed_at=now.isoformat(),
        )


# Job instance for discovery by runner
JOB = SessionMemoryExtractionJob()
