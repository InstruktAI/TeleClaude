"""History search service shared by local API and peer transport boundaries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import CliCaller, PersonCliCaller, SystemCliCaller
from teleclaude.core.agents import AgentName
from teleclaude.core.dates import format_utc_datetime, parse_iso_datetime
from teleclaude.core.db._sync import get_session_field_sync
from teleclaude.history.search_payload import HistorySearchPayload, HistorySearchRow
from teleclaude.identity_reach import Reach, resolve_reach
from teleclaude.mirrors.store import (
    MirrorCoverageState,
    MirrorRecord,
    MirrorSearchResult,
    get_mirror,
    get_session_mirror,
    search_mirrors,
)
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.utils.transcript import parse_session_transcript
from teleclaude.utils.transcript_discovery import discover_transcripts, extract_session_id

logger = get_logger(__name__)

__all__ = [
    "HistoryRelayCommand",
    "HistoryShowRequest",
    "_format_display_timestamp",
    "build_history_detail_payload",
    "history_caller_is_identified",
    "parse_history_agents",
    "resolve_history_reach",
]

HISTORY_SEARCH_ACCEPTED = "history.search.accepted"
HISTORY_SEARCH_COMPLETED = "history.search.completed"
_NATIVE_SESSION_ID_FIELD = "native_session_id"
_LIFECYCLE_STATUS_FIELD = "lifecycle_status"
_RUNNING_SESSION_STATES = frozenset({"active", "headless", "initializing"})
_UNKNOWN_VALUE = "unknown"
_YES_VALUE = "yes"
_NO_VALUE = "no"
_TRANSCRIPT_ID_READ_FAILED_EVENT = "history.transcript_id_read_failed"
_COVERAGE_LINE_TEMPLATE = "Coverage: through {timestamp_end}; state: {coverage_state}"
_RETAINED_COVERAGE_LINE_TEMPLATE = (
    "Coverage: through {timestamp_end}; state: {coverage_state}; shrink refusal observed: {shrink_refused_at}"
)


def history_caller_is_identified(caller: CliCaller) -> bool:
    """Whether history can bind this caller to a person or system principal."""
    return isinstance(caller, SystemCliCaller) or (
        isinstance(caller, PersonCliCaller) and caller.person_slug is not None
    )


def resolve_history_reach(caller: CliCaller) -> Reach | None:
    """Resolve identity reach only for a caller history can identify."""
    if not history_caller_is_identified(caller):
        return None
    return resolve_reach(caller)


class HistoryRelayCommand(StrEnum):
    """Commands supported by the history relay."""

    SEARCH = "history_search"
    SHOW = "history_show"


class HistoryShowRequest(TypedDict):
    """Structured request carried by the history-show relay command."""

    session_id: str
    agent: str
    thinking: bool
    raw: bool


class IdNamespace(StrEnum):
    """Identifier namespace supplied to history detail lookup."""

    TELECLAUDE = "tc_id"
    NATIVE = "native_id"


class DetailSource(StrEnum):
    """Source used to render a history detail response."""

    MIRROR = "mirror"
    TRANSCRIPT = "on-disk transcript"


@dataclass(frozen=True)
class MirrorResolution:
    """Resolved identity and source context for a detail lookup."""

    mirror: MirrorRecord | None
    requested_id: str
    requested_namespace: IdNamespace
    tc_id: str | None
    native_id: str | None
    source: DetailSource


class HistoryDetailPayload(TypedDict):
    """Machine-readable history detail result."""

    requested_id: str
    requested_namespace: str
    source: str
    tc_id: str | None
    native_id: str | None
    title: str | None
    project: str | None
    computer: str | None
    timestamp_start: str | None
    timestamp_end: str | None
    message_count: int | None
    coverage_state: str
    shrink_refused_at: str | None
    running: str
    raw: bool
    conversation_text: str


def _format_display_timestamp(value: str) -> str:
    parsed = parse_iso_datetime(value)
    return format_utc_datetime(parsed) if parsed is not None else value


def find_transcript(agents: Sequence[AgentName], session_id: str) -> tuple[Path, AgentName] | None:
    """Find a transcript file by its exact extracted session ID."""
    for candidate in discover_transcripts(agents):
        try:
            extracted = extract_session_id(candidate.path, candidate.agent)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                _TRANSCRIPT_ID_READ_FAILED_EVENT,
                transcript_path=str(candidate.path),
                agent=candidate.agent.value,
                error=str(exc),
            )
            continue
        if extracted == session_id:
            return candidate.path, candidate.agent
    return None


def _running_state(tc_id: str | None) -> str:
    if tc_id is None:
        return _UNKNOWN_VALUE
    lifecycle_status = get_session_field_sync(str(MAIN_DB_PATH), tc_id, _LIFECYCLE_STATUS_FIELD)
    if not isinstance(lifecycle_status, str):
        return _UNKNOWN_VALUE
    return _YES_VALUE if lifecycle_status in _RUNNING_SESSION_STATES else _NO_VALUE


def _detail_json_payload(
    resolution: MirrorResolution,
    *,
    body: str,
    raw: bool,
) -> HistoryDetailPayload:
    mirror = resolution.mirror
    return {
        "requested_id": resolution.requested_id,
        "requested_namespace": resolution.requested_namespace.value,
        "source": resolution.source.value,
        "tc_id": resolution.tc_id,
        "native_id": resolution.native_id,
        "title": mirror.title if mirror is not None else None,
        "project": mirror.project_path if mirror is not None else None,
        "computer": mirror.computer if mirror is not None else None,
        "timestamp_start": mirror.timestamp_start if mirror is not None else None,
        "timestamp_end": mirror.timestamp_end if mirror is not None else None,
        "message_count": mirror.message_count if mirror is not None else None,
        "coverage_state": mirror.coverage_state.value if mirror is not None else MirrorCoverageState.UNKNOWN.value,
        "shrink_refused_at": mirror.shrink_refused_at if mirror is not None else None,
        "running": _running_state(resolution.tc_id),
        "raw": raw,
        "conversation_text": body,
    }


def _resolve_local_mirror(
    session_id: str,
    *,
    reach: Reach,
) -> MirrorResolution:
    mirror = get_mirror(native_session_id=session_id, reach=reach)
    if mirror is not None:
        return MirrorResolution(
            mirror=mirror,
            requested_id=session_id,
            requested_namespace=IdNamespace.NATIVE,
            tc_id=mirror.session_id,
            native_id=mirror.native_session_id,
            source=DetailSource.MIRROR,
        )

    attributed_mirror = get_session_mirror(session_id, reach=reach)
    if attributed_mirror is not None:
        return MirrorResolution(
            mirror=attributed_mirror,
            requested_id=session_id,
            requested_namespace=IdNamespace.TELECLAUDE,
            tc_id=attributed_mirror.session_id,
            native_id=attributed_mirror.native_session_id,
            source=DetailSource.MIRROR,
        )

    resolved_native_id = get_session_field_sync(str(MAIN_DB_PATH), session_id, _NATIVE_SESSION_ID_FIELD)
    if isinstance(resolved_native_id, str) and resolved_native_id:
        translated_mirror = get_mirror(native_session_id=resolved_native_id, reach=reach)
        return MirrorResolution(
            mirror=translated_mirror,
            requested_id=session_id,
            requested_namespace=IdNamespace.TELECLAUDE,
            tc_id=session_id,
            native_id=resolved_native_id,
            source=DetailSource.MIRROR,
        )

    return MirrorResolution(
        mirror=None,
        requested_id=session_id,
        requested_namespace=IdNamespace.NATIVE,
        tc_id=None,
        native_id=session_id,
        source=DetailSource.TRANSCRIPT,
    )


def build_history_detail_payload(
    session_id: str,
    *,
    reach: Reach,
    agents: Sequence[AgentName],
    include_thinking: bool,
    raw: bool,
) -> HistoryDetailPayload | None:
    """Resolve one history detail within the caller's mirror access scope."""
    transcript_fallback_allowed = reach.everything
    resolution = _resolve_local_mirror(session_id, reach=reach)
    mirror = resolution.mirror
    if mirror and not raw:
        return _detail_json_payload(resolution, body=mirror.conversation_text.rstrip(), raw=False)
    if mirror and raw:
        transcript_path = mirror.metadata.get("transcript_path")
        if isinstance(transcript_path, str) and transcript_path:
            path = Path(transcript_path).expanduser()
            if path.exists():
                return _detail_json_payload(resolution, body=path.read_text(encoding="utf-8"), raw=True)

    if not transcript_fallback_allowed:
        return None
    match = find_transcript(agents, session_id)
    if not match:
        return None
    path, agent = match
    rendered = parse_session_transcript(
        str(path),
        f"{agent.value} session - {path.stem}",
        agent_name=agent,
        tail_chars=0,
        include_thinking=include_thinking,
        include_tools=False,
    )
    return _detail_json_payload(resolution, body=rendered, raw=False)


def parse_history_agents(agent_filter: str) -> list[AgentName]:
    """Parse a comma-separated agent filter for service boundaries."""
    if agent_filter == "all":
        return list(AgentName)
    return [AgentName(value.strip().lower()) for value in agent_filter.split(",") if value.strip()]


def history_results_to_rows(results: Sequence[MirrorSearchResult]) -> list[HistorySearchRow]:
    """Attach TeleClaude ids to mirror-native search rows."""
    return [
        HistorySearchRow(
            sort_timestamp=result.sort_timestamp,
            timestamp=result.timestamp,
            computer=result.computer,
            agent=result.agent,
            project=result.project_path or "",
            topic=result.topic,
            tc_id=result.session_id,
            native_id=result.native_session_id,
        )
        for result in results
    ]


def build_history_search_payload(
    *,
    computer: str,
    query: str,
    agents: Sequence[AgentName],
    limit: int,
    reach: Reach,
    include_workers: bool,
    identity: str | None,
    project: str | None,
) -> HistorySearchPayload:
    """Search local mirrors and return the federated wire contract."""
    search_id = str(uuid4())
    logger.info(
        HISTORY_SEARCH_ACCEPTED,
        search_id=search_id,
        requested_limit=limit,
        include_workers=include_workers,
        has_identity=identity is not None,
        has_project=project is not None,
        has_query=bool(query.strip()),
    )
    page = search_mirrors(
        query,
        agents,
        limit=limit,
        reach=reach,
        include_workers=include_workers,
        identity=identity,
        project=project,
    )
    rows = history_results_to_rows(page.results)
    mapped_count = sum(row["tc_id"] is not None for row in rows)
    logger.info(
        HISTORY_SEARCH_COMPLETED,
        search_id=search_id,
        outcome="success",
        requested_limit=limit,
        candidate_count=page.physical_candidate_count,
        eligible_candidate_count=page.eligible_candidate_count,
        canonical_count=page.canonical_count,
        collapsed_count=page.eligible_candidate_count - page.canonical_count,
        unreprojectable_excluded_count=page.unreprojectable_excluded_count,
        mapped_count=mapped_count,
        unmapped_count=len(rows) - mapped_count,
    )
    return HistorySearchPayload(
        computer=computer,
        rows=rows,
        excluded_workers=page.excluded_workers,
    )
