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

import json
import logging
import ssl
import sys
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from redis.asyncio import Redis

from jobs.base import Job, JobResult
from teleclaude.channels import publisher as channels_publisher
from teleclaude.config import config
from teleclaude.core.agents import AgentName
from teleclaude.core.summarizer import _call_summarizer
from teleclaude.memory.store import MemoryStore
from teleclaude.memory.types import ObservationInput, ObservationType
from teleclaude.mirrors.store import get_mirror
from teleclaude.utils.transcript import StructuredMessage, extract_structured_messages

logger = logging.getLogger(__name__)
_REDIS_CLIENT: Redis | None = None


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
                sid = session.session_id if hasattr(session, "session_id") else "unknown"
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
        return pending  # type: ignore[return-value]

    async def _process_session(self, session: object) -> None:
        """Process a single session: extract memories and actionable items."""
        session_id: str = session.session_id  # type: ignore[attr-defined]
        last_processed_at = getattr(session, "help_desk_processed_at", None)

        # Step 1: Read transcript since last extraction
        transcript = await self._read_transcript_delta(session_id, since=last_processed_at)
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
        await self._update_bookkeeping(session_id, now)

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

    def _resolve_identity_key(self, session: object) -> str | None:
        """Derive the identity key from session origin_metadata."""
        from teleclaude.core.identity import derive_identity_key

        origin = getattr(session, "origin_metadata", None)
        if not isinstance(origin, dict):
            return None
        return derive_identity_key(origin)

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
        session_id = getattr(session, "session_id", "?")
        if identity_key is None:
            logger.info("Skipping personal memory extraction for session %s: identity key missing", session_id)
            return

        project = _get_session_project(session)
        if project is None:
            logger.warning("Skipping personal memory extraction for session %s: project missing", session_id)
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
        session: object,
    ) -> None:
        """Extract business memories from transcript and save at project scope.

        Business memories capture product feedback, feature requests, common
        pain points, and domain knowledge shared by users.
        """
        session_id = getattr(session, "session_id", "?")
        project = _get_session_project(session)
        if project is None:
            logger.warning("Skipping business memory extraction for session %s: project missing", session_id)
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
        session: object,
    ) -> None:
        """Extract actionable items from transcript and publish to channels.

        Actionable items include follow-up tasks, bug reports, feature requests,
        and escalation triggers. Each item is published to the appropriate
        internal channel for downstream routing.
        """
        session_id = getattr(session, "session_id", None)
        if not isinstance(session_id, str) or not session_id.strip():
            logger.warning("Skipping actionable item extraction: session_id missing")
            return

        project = _get_session_project(session)
        if project is None:
            logger.warning("Skipping actionable item extraction for session %s: project missing", session_id)
            return

        items = await _call_summarizer(
            _build_actionable_items_prompt(transcript),
            _ACTIONABLE_EXTRACTION_SCHEMA,
            _parse_actionable_response,
        )
        if not items:
            return

        try:
            redis_client = await get_redis()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Skipping actionable item publish for session %s: %s", session_id, exc)
            return

        channel = channels_publisher.channel_key(project, "actionable-items")
        for item in items:
            try:
                await channels_publisher.publish(
                    redis_client,
                    channel,
                    {
                        "type": item["type"],
                        "summary": item["summary"],
                        "session_id": session_id,
                    },
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Failed to publish actionable item for session %s: %s",
                    session_id,
                    exc,
                )

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


def _get_session_project(session: object) -> str | None:
    """Resolve a normalized project scope from the session."""
    project_raw = getattr(session, "project_path", None)
    if not isinstance(project_raw, str):
        return None
    project = project_raw.strip()
    return project or None


async def get_redis() -> Redis:
    """Return the configured Redis client for channels publication."""
    global _REDIS_CLIENT  # pylint: disable=global-statement
    if not config.redis.enabled:
        raise RuntimeError("Redis transport is disabled")

    if _REDIS_CLIENT is None:
        kwargs: dict[str, Any] = {
            "password": config.redis.password,
            "max_connections": config.redis.max_connections,
            "socket_timeout": config.redis.socket_timeout,
            "health_check_interval": 10,
            "decode_responses": False,
        }
        if config.redis.url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
        _REDIS_CLIENT = Redis.from_url(config.redis.url, **kwargs)

    await cast(Awaitable[bool], _REDIS_CLIENT.ping())
    return _REDIS_CLIENT
