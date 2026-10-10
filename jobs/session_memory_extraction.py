#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
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
``last_memory_extraction_at``, and extracts personal + business memories.
Closed sessions still use ``help_desk_processed_at`` to gate their final
post-mortem pass.

Memory extraction runs as an idempotent job with two scopes:
- **Personal memories** are identity-scoped (tied to the user via identity_key).
- **Business memories** are project-scoped (shared across the project).

Consumers include help desk customer sessions, member personal assistant
sessions, and any future long-lived session type with an identity_key.

Integration:
- Scheduled via teleclaude.yml (default: every 30 minutes).
- Queries sessions from the core database.
- Saves memories via the MemoryStore.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import get_logger

# Ensure repo root is in path for imports
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from jobs.base import Job, JobResult, JobRunContext, run_job_cli
from teleclaude.caller_identity import PersonCliCaller, SystemCliCaller, caller_from_principal
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.identity import derive_identity_key
from teleclaude.core.models import Session
from teleclaude.core.summarizer import _call_summarizer
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.home_owner import EventHomeOwnerMarker
from teleclaude.identity_reach import resolve_reach
from teleclaude.memory.store import MemoryStore
from teleclaude.memory.types import ObservationInput, ObservationType
from teleclaude.mirrors.store import get_mirror
from teleclaude.utils.transcript import StructuredMessage, extract_structured_messages

logger = get_logger(__name__)


class _MemoryCandidate(TypedDict):
    type: str
    title: str
    narrative: str
    facts: list[str]


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


class SessionMemoryExtractionJob(Job):
    """Extract memories from long-lived sessions.

    Scans for sessions that have transcript content beyond
    ``last_memory_extraction_at`` (or, for closed sessions, still lack a final
    ``help_desk_processed_at`` pass), reads the transcript delta, and runs
    AI-powered extraction for personal and business memories. Works for any
    session with a human_role — customers, members, and other long-lived
    session types.
    """

    def run(self, context: JobRunContext | None = None) -> JobResult:
        """Execute memory extraction for all pending sessions."""
        del context
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
            except Exception as exc:
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
        """Process a single session: extract personal and business memories."""
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

        # Step 5: Update bookkeeping timestamps
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
        mirror = get_mirror(
            native_session_id=session_id,
            reach=resolve_reach(SystemCliCaller()),
        )
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
        return derive_identity_key(dict(session.origin_metadata))

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
        caller = caller_from_principal(session.principal)
        subject = (
            SubjectRef(ConfigSubjectKind.PERSON, caller.person_slug).to_token()
            if isinstance(caller, PersonCliCaller) and caller.person_slug is not None
            else EventHomeMarker.UNKNOWN.value
        )
        principal = session.principal or EventHomeMarker.UNKNOWN.value
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
                    subject=subject,
                    subject_owner=EventHomeOwnerMarker.NONE.value,
                    principal=principal,
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
                    subject=session.config_subject or EventHomeMarker.UNKNOWN.value,
                    subject_owner=session.subject_owner or EventHomeOwnerMarker.UNRESOLVED.value,
                    principal=session.principal or EventHomeMarker.UNKNOWN.value,
                )
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
