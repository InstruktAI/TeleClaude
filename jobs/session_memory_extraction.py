#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "redis",
#     "openai",
#     "anthropic",
#     "pyyaml",
#     "python-dotenv",
#     "aiosqlite",
#     "sqlalchemy",
#     "sqlmodel",
# ]
# ///
"""Session memory extraction job.

Finds sessions needing processing, reads transcripts since
``last_memory_extraction_at``, and extracts personal + business memories plus
actionable items. Closed sessions still use ``help_desk_processed_at`` to gate
their final post-mortem pass.

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

import asyncio
import json
import ssl
import sys
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis

# Ensure repo root is in path for imports
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# pylint: disable=wrong-import-position  # sys.path must be set before these imports resolve
from jobs.base import Job, JobResult, run_job_cli
from teleclaude.channels import publisher as channels_publisher
from teleclaude.config import config
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.identity import derive_identity_key
from teleclaude.core.models import Session
from teleclaude.core.summarizer import _call_summarizer
from teleclaude.memory.store import MemoryStore
from teleclaude.memory.types import ObservationInput, ObservationType
from teleclaude.mirrors.store import get_mirror
from teleclaude.utils.transcript import StructuredMessage, extract_structured_messages

# pylint: enable=wrong-import-position

logger = get_logger(__name__)
_redis_client: Redis | None = None  # pylint: disable=invalid-name  # mutable singleton, not a constant


class _MemoryCandidate(TypedDict):
    type: str
    title: str
    narrative: str
    facts: list[str]


class _ActionableItem(TypedDict):
    type: str
    summary: str


_MEMORY_CANDIDATE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": [member.value for member in ObservationType],
        },
        "title": {"type": "string"},
        "narrative": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["type", "title", "narrative", "facts"],
    "additionalProperties": False,
}
_MEMORY_EXTRACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": _MEMORY_CANDIDATE_SCHEMA,
        },
    },
    "required": ["memories"],
    "additionalProperties": False,
}
_ACTIONABLE_ITEM_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["bug", "feature-request", "follow-up", "escalation"],
        },
        "summary": {"type": "string"},
    },
    "required": ["type", "summary"],
    "additionalProperties": False,
}
_ACTIONABLE_EXTRACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": _ACTIONABLE_ITEM_SCHEMA,
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


class SessionMemoryExtractionJob(Job):
    """Extract memories and actionable items from long-lived sessions.

    Scans for sessions that have transcript content beyond
    ``last_memory_extraction_at`` (or, for closed sessions, still lack a final
    ``help_desk_processed_at`` pass), reads the transcript delta, and runs
    AI-powered extraction for personal memories, business memories, and
    actionable items. Works for any session with a human_role — customers,
    members, and other long-lived session types.
    """

    name = "session-memory-extraction"

    def run(self) -> JobResult:
        """Execute memory extraction for all pending sessions."""
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

        errors: list[str] = []
        processed = 0
        for session in sessions:
            try:
                await self._process_session(session)
                processed += 1
            except Exception as exc:  # pylint: disable=broad-exception-caught
                errors.append(f"{session.session_id}: {exc}")
                logger.warning("Session extraction failed for %s: %s", session.session_id, exc)

        return JobResult(
            success=len(errors) == 0,
            message=f"Extracted {processed}/{len(sessions)} session(s)",
            items_processed=processed,
            errors=errors if errors else None,
        )

    async def _find_sessions_needing_extraction(self) -> list[Session]:
        """Find sessions that have transcript content beyond the last extraction boundary.

        Closed sessions need a final post-mortem pass when ``help_desk_processed_at``
        is still NULL. Active long-lived sessions need extraction when
        ``last_memory_extraction_at`` is older than ``last_activity`` (or unset).
        """
        all_sessions = await db.list_sessions(include_closed=True)
        pending: list[Session] = []
        for session in all_sessions:
            # Any session with a human_role is eligible for extraction
            if not session.human_role:
                continue
            if session.last_activity is None:
                continue
            is_closed = session.closed_at is not None or session.lifecycle_status in {"closed", "stopped"}

            if is_closed:
                if session.help_desk_processed_at is None:
                    pending.append(session)
                continue

            if session.last_memory_extraction_at is None or session.last_memory_extraction_at < session.last_activity:
                pending.append(session)
        return pending

    async def _process_session(self, session: Session) -> None:
        """Process a single session: extract memories and actionable items."""
        # Step 1: Read transcript since last extraction
        transcript = await self._read_transcript_delta(session.session_id, since=session.last_memory_extraction_at)
        if not transcript or not transcript.strip():
            return

        # Step 2: Derive identity key for personal memory scoping
        identity_key = self._resolve_identity_key(session)

        # Step 3: Extract personal memories (identity-scoped)
        if identity_key is not None:
            await self._extract_personal_memories(transcript, identity_key, session)

        # Step 4: Extract business memories (project-scoped)
        await self._extract_business_memories(transcript, session)

        # Step 5: Extract actionable items and publish to channels
        await self._extract_and_publish_actionable_items(transcript, session)

        # Step 6: Update bookkeeping timestamps
        now = datetime.now(UTC)
        await self._update_bookkeeping(session.session_id, now)

    async def _read_transcript_delta(
        self,
        session_id: str,
        since: datetime | None,
    ) -> str | None:
        """Read session transcript content since the given timestamp.

        Returns the transcript text, or None if no new content exists.
        """
        mirror = get_mirror(session_id)
        if mirror is None:
            return None

        transcript_path_raw = mirror.metadata.get("transcript_path")
        if not isinstance(transcript_path_raw, str) or not transcript_path_raw.strip():
            return None

        agent_name_raw = mirror.metadata.get("agent")
        if not isinstance(agent_name_raw, str) or not agent_name_raw.strip():
            agent_name_raw = mirror.agent
        try:
            agent_name = AgentName.from_str(agent_name_raw)
        except ValueError:
            logger.warning("Skipping transcript delta for session %s: unknown agent %r", session_id, agent_name_raw)
            return None

        messages = extract_structured_messages(
            transcript_path_raw,
            agent_name,
            since=since.isoformat() if since is not None else None,
        )
        if not messages:
            return None

        transcript_lines = _format_memory_transcript(messages)
        if not transcript_lines:
            return None
        return "\n\n".join(transcript_lines)

    def _resolve_identity_key(self, session: Session) -> str | None:
        """Derive the identity key from session origin_metadata."""
        return derive_identity_key(session.origin_metadata)

    async def _extract_personal_memories(
        self,
        transcript: str,
        identity_key: str | None,
        session: Session,
    ) -> None:
        """Extract personal memories from transcript and save with identity scope.

        Personal memories capture user-specific information: preferences,
        communication style, history, and relationship context.
        """
        if identity_key is None:
            logger.info("Skipping personal memory extraction for session %s: identity key missing", session.session_id)
            return

        project = _get_session_project(session)
        if project is None:
            logger.warning("Skipping personal memory extraction for session %s: project missing", session.session_id)
            return

        memories = await _call_summarizer(
            _build_personal_memory_prompt(transcript),
            _MEMORY_EXTRACTION_SCHEMA,
            _parse_memory_response,
        )
        if not memories:
            return

        store = MemoryStore()
        for candidate in memories:
            observation_type = _parse_observation_type(candidate["type"])
            if observation_type is None:
                continue
            await store.save_observation(
                ObservationInput(
                    text=candidate["narrative"],
                    title=candidate["title"],
                    project=project,
                    type=observation_type,
                    facts=candidate["facts"],
                    identity_key=identity_key,
                )
            )

    async def _extract_business_memories(
        self,
        transcript: str,
        session: Session,
    ) -> None:
        """Extract business memories from transcript and save at project scope.

        Business memories capture product feedback, feature requests, common
        pain points, and domain knowledge shared by users.
        """
        project = _get_session_project(session)
        if project is None:
            logger.warning("Skipping business memory extraction for session %s: project missing", session.session_id)
            return

        memories = await _call_summarizer(
            _build_business_memory_prompt(transcript),
            _MEMORY_EXTRACTION_SCHEMA,
            _parse_memory_response,
        )
        if not memories:
            return

        store = MemoryStore()
        for candidate in memories:
            observation_type = _parse_observation_type(candidate["type"])
            if observation_type is None:
                continue
            await store.save_observation(
                ObservationInput(
                    text=candidate["narrative"],
                    title=candidate["title"],
                    project=project,
                    type=observation_type,
                    facts=candidate["facts"],
                )
            )

    async def _extract_and_publish_actionable_items(
        self,
        transcript: str,
        session: Session,
    ) -> None:
        """Extract actionable items from transcript and publish to channels.

        Actionable items include follow-up tasks, bug reports, feature requests,
        and escalation triggers. Each item is published to the appropriate
        internal channel for downstream routing.
        """
        project = _get_session_project(session)
        if project is None:
            logger.warning("Skipping actionable item extraction for session %s: project missing", session.session_id)
            return

        items = await _call_summarizer(
            _build_actionable_items_prompt(transcript),
            _ACTIONABLE_EXTRACTION_SCHEMA,
            _parse_actionable_response,
        )
        if not items:
            return

        if not config.redis.enabled:
            logger.warning("Skipping actionable item publish for session %s: redis unavailable", session.session_id)
            return

        redis_client = await get_redis()
        channel = channels_publisher.channel_key(project, "actionable-items")
        for item in items:
            await channels_publisher.publish(
                redis_client,
                channel,
                {
                    "type": item["type"],
                    "summary": item["summary"],
                    "session_id": session.session_id,
                },
            )

    async def _update_bookkeeping(self, session_id: str, now: datetime) -> None:
        """Update session timestamps after successful extraction."""
        await db.update_session(
            session_id,
            last_memory_extraction_at=now.isoformat(),
            help_desk_processed_at=now.isoformat(),
        )


# Job instance for discovery by runner
JOB = SessionMemoryExtractionJob()


if __name__ == "__main__":
    raise SystemExit(run_job_cli(JOB))


def _format_memory_transcript(messages: list[StructuredMessage]) -> list[str]:
    """Normalize structured transcript messages into user/assistant text blocks."""
    transcript_lines: list[str] = []
    for message in messages:
        if message.role not in {"user", "assistant"}:
            continue
        if message.type != "text":
            continue
        text = message.text.strip()
        if not text:
            continue
        transcript_lines.append(f"{message.role.title()}: {text}")
    return transcript_lines


def _build_personal_memory_prompt(transcript: str) -> str:
    """Build the personal-memory extraction prompt."""
    return (
        "Extract durable personal memories from this session transcript.\n\n"
        "Return only long-lived user-specific observations such as preferences, context, "
        "frictions, decisions, discoveries, patterns, or gotchas.\n\n"
        f"Transcript:\n{transcript}"
    )


def _build_business_memory_prompt(transcript: str) -> str:
    """Build the business-memory extraction prompt."""
    return (
        "Extract durable business or project memories from this session transcript.\n\n"
        "Return only reusable project-scoped observations such as customer discoveries, "
        "product friction, decisions, patterns, or gotchas.\n\n"
        f"Transcript:\n{transcript}"
    )


def _build_actionable_items_prompt(transcript: str) -> str:
    """Build the actionable-items extraction prompt."""
    return (
        "Extract actionable items from this session transcript.\n\n"
        "Return only concrete bugs, feature requests, follow-ups, or escalations that "
        "should be routed to downstream systems.\n\n"
        f"Transcript:\n{transcript}"
    )


def _parse_memory_response(text: str) -> list[_MemoryCandidate]:
    """Parse structured memory extraction output."""
    data = json.loads(text.strip())
    memories_raw = data.get("memories", [])
    if not isinstance(memories_raw, list):
        raise ValueError("Memory response is missing a memories list")

    memories: list[_MemoryCandidate] = []
    for item in memories_raw:
        if not isinstance(item, dict):
            raise ValueError("Memory item must be an object")

        raw_type = item.get("type")
        title = item.get("title")
        narrative = item.get("narrative")
        facts_raw = item.get("facts")
        if not isinstance(raw_type, str) or not isinstance(title, str) or not isinstance(narrative, str):
            raise ValueError("Memory item fields must be strings")
        if not isinstance(facts_raw, list) or any(not isinstance(fact, str) for fact in facts_raw):
            raise ValueError("Memory item facts must be a list of strings")

        memories.append(
            _MemoryCandidate(
                type=raw_type,
                title=title,
                narrative=narrative,
                facts=facts_raw,
            )
        )
    return memories


def _parse_actionable_response(text: str) -> list[_ActionableItem]:
    """Parse structured actionable-item extraction output."""
    data = json.loads(text.strip())
    items_raw = data.get("items", [])
    if not isinstance(items_raw, list):
        raise ValueError("Actionable response is missing an items list")

    items: list[_ActionableItem] = []
    for item in items_raw:
        if not isinstance(item, dict):
            raise ValueError("Actionable item must be an object")

        raw_type = item.get("type")
        summary = item.get("summary")
        if not isinstance(raw_type, str) or not isinstance(summary, str):
            raise ValueError("Actionable item fields must be strings")

        items.append(_ActionableItem(type=raw_type, summary=summary))
    return items


def _parse_observation_type(raw_type: str) -> ObservationType | None:
    """Convert summarizer output into a valid observation type."""
    try:
        return ObservationType(raw_type)
    except ValueError:
        logger.warning("Skipping memory candidate with unknown type %r", raw_type)
        return None


def _get_session_project(session: Session) -> str | None:
    """Resolve a normalized project scope from the session."""
    if session.project_path is None:
        return None
    project = session.project_path.strip()
    return project or None


async def get_redis() -> Redis:
    """Return the configured Redis client for channels publication."""
    global _redis_client  # pylint: disable=global-statement
    if not config.redis.enabled:
        raise RuntimeError("Redis transport is disabled")

    if _redis_client is None:
        kwargs: dict[str, Any] = {
            "password": config.redis.password,
            "max_connections": config.redis.max_connections,
            "socket_timeout": config.redis.socket_timeout,
            "health_check_interval": 10,
            "decode_responses": False,
        }
        if config.redis.url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
        _redis_client = Redis.from_url(config.redis.url, **kwargs)

    await cast(Awaitable[bool], _redis_client.ping())
    return _redis_client
