"""Resolve session-record facts used to classify and attribute mirror writes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude import paths as tc_paths
from teleclaude.core.db._sync import (
    SessionIdentityError,
    SessionMirrorFacts,
    get_session_mirror_facts_sync,
    resolve_session_principal,
)
from teleclaude.core.models._adapter import SessionAdapterMetadata
from teleclaude.services.project_catalog import get_project_catalog_service

_ADAPTER_ORIGINS = frozenset({"telegram", "discord", "whatsapp"})


class MirrorAttributionReason(StrEnum):
    """Why a transcript path resolved to its attributed session."""

    CURRENT = "current_transcript"
    CHAIN = "chain_transcript"
    NO_RECORD = "no_record"


@dataclass(frozen=True)
class SessionMirrorContext:
    """Resolved session facts shared by reconciliation, fan-out, and backfill."""

    session_id: str
    computer: str
    agent: str | None
    project_path: str
    transcript_path: str | None
    lineage: tuple[str, ...]
    human_email: str | None
    visibility: str | None
    last_input_origin: str | None
    adapter_metadata_json: str | None
    system_role: str | None
    command: str | None
    todo: str | None
    title: str | None
    subdir: str | None
    initiator_session_id: str | None
    initiator_computer: str | None
    initiated_by_ai: bool | None
    job: str | None
    created_at: str | None
    closed_at: str | None
    position: int | None
    reason: MirrorAttributionReason
    principal: str | None
    project: str | None
    subject: str | None
    subject_owner: str | None
    channel_identifiers: dict[str, str]


def _extract_channel_identifiers(origin: str | None, raw_json: str | None) -> dict[str, str]:
    """Extract platform identifiers from the session's adapter metadata."""
    if not origin or origin not in _ADAPTER_ORIGINS or not raw_json:
        return {}
    try:
        adapter = SessionAdapterMetadata.from_json(raw_json)
    except (ValueError, KeyError, TypeError):
        return {}
    identifiers: dict[str, str] = {}
    ui = adapter.get_ui()
    if origin == "telegram":
        telegram = ui.telegram
        if telegram and telegram.user_id is not None:
            identifiers["user_id"] = str(telegram.user_id)
    elif origin == "discord":
        discord = ui.discord
        if discord:
            if discord.user_id is not None:
                identifiers["user_id"] = discord.user_id
            if discord.channel_id is not None:
                identifiers["channel_id"] = str(discord.channel_id)
    elif origin == "whatsapp":
        whatsapp = ui.whatsapp
        if whatsapp and whatsapp.phone_number is not None:
            identifiers["phone_number"] = whatsapp.phone_number
    return identifiers


def _position_for_transcript(facts: SessionMirrorFacts, transcript_path: str | None) -> int | None:
    """Return the transcript's position in the session's ordered lineage."""
    if transcript_path is None:
        return None
    try:
        return facts.lineage.index(transcript_path)
    except ValueError:
        return None


def session_context_from_facts(facts: SessionMirrorFacts, transcript_path: str | None) -> SessionMirrorContext:
    """Build the one canonical mirror context from published session facts."""
    try:
        principal, _role = resolve_session_principal(facts.identity)
    except SessionIdentityError:
        principal = None
    project = None
    if facts.project_path:
        project_record = get_project_catalog_service().get_by_root(Path(facts.project_path))
        if project_record is not None:
            project = project_record.slug
    reason = (
        MirrorAttributionReason.CURRENT if transcript_path == facts.native_log_file else MirrorAttributionReason.CHAIN
    )
    return SessionMirrorContext(
        session_id=facts.session_id,
        computer=facts.computer_name,
        agent=facts.active_agent,
        project_path=facts.project_path or "",
        transcript_path=transcript_path or facts.native_log_file,
        lineage=facts.lineage,
        human_email=facts.identity.human_email,
        visibility=facts.visibility,
        last_input_origin=facts.last_input_origin,
        adapter_metadata_json=facts.adapter_metadata,
        system_role=facts.system_role,
        command=facts.command,
        todo=facts.working_slug,
        title=facts.title,
        subdir=facts.subdir,
        initiator_session_id=facts.initiator_session_id,
        initiator_computer=facts.initiator_computer,
        initiated_by_ai=facts.initiated_by_ai,
        job=facts.job,
        created_at=facts.created_at,
        closed_at=facts.closed_at,
        position=_position_for_transcript(facts, transcript_path),
        reason=reason,
        principal=principal,
        project=project,
        subject=facts.config_subject,
        subject_owner=facts.subject_owner,
        channel_identifiers=_extract_channel_identifiers(facts.last_input_origin, facts.adapter_metadata),
    )


def get_session_context(
    *, session_id: str | None = None, transcript_path: str | None = None
) -> SessionMirrorContext | None:
    """Look up a session record by TeleClaude id or any transcript in its chain."""
    facts = get_session_mirror_facts_sync(
        str(tc_paths.MAIN_DB_PATH),
        session_id=session_id,
        transcript_path=transcript_path,
    )
    return session_context_from_facts(facts, transcript_path) if facts is not None else None
