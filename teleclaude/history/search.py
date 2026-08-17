"""Reusable history search functions backed by conversation mirrors."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core.agents import AgentName
from teleclaude.core.dates import format_utc_datetime, parse_iso_datetime
from teleclaude.core.db._sync import get_session_field_sync, get_session_ids_by_native_sync
from teleclaude.history.remote_detail import get_remote_detail, resolve_remote_detail_base
from teleclaude.history.service import HistorySearchPayload, HistorySearchRow
from teleclaude.mirrors.store import MirrorRecord, get_mirror
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.utils.transcript import parse_session_transcript
from teleclaude.utils.transcript_discovery import discover_transcripts, extract_session_id

_NATIVE_SESSION_ID_FIELD = "native_session_id"
_LIFECYCLE_STATUS_FIELD = "lifecycle_status"
_TRANSCRIPT_NOT_FOUND = "No transcript found for session '{session_id}'"
_RUNNING_SESSION_STATES = frozenset({"active", "headless", "initializing"})
_UNKNOWN_VALUE = "unknown"
_YES_VALUE = "yes"
_NO_VALUE = "no"
_TRANSCRIPT_ID_READ_FAILED_EVENT = "history.transcript_id_read_failed"

logger = get_logger(__name__)


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


def _format_display_timestamp(value: str) -> str:
    parsed = parse_iso_datetime(value)
    return format_utc_datetime(parsed) if parsed is not None else value


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
    running: str
    raw: bool
    conversation_text: str


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


def _print_results(
    search_term: str,
    results: list[HistorySearchRow],
    *,
    show_computer: bool,
    limit: int,
    excluded_workers: int = 0,
    json_output: bool = False,
) -> None:
    results = results[:limit]
    if json_output:
        print(json.dumps(results))
        return
    if not results:
        return
    print(f"\nSearch results for '{search_term}' ({len(results)} found):\n")

    if excluded_workers:
        print(f"Excluded worker matches: {excluded_workers}\n")

    for entry in results:
        tc_id = entry["tc_id"]
        native_id = entry["native_id"]
        if tc_id is not None:
            identifier_label = "tc_id:"
            identifier = tc_id
        elif native_id is not None:
            identifier_label = "native_id:"
            identifier = native_id
        else:
            identifier_label = "no_session"
            identifier = ""
        computer = f"  {entry['computer']:<12}" if show_computer else ""
        print(
            f"{entry['timestamp']}  {entry['agent']:<7}{computer}  "
            f"{identifier_label:<10} {identifier:<36}  {entry['project']}"
        )
        topic = " ".join(entry["topic"].splitlines())
        print(f"    {topic}")


def _running_state(tc_id: str | None) -> str:
    if tc_id is None:
        return _UNKNOWN_VALUE
    lifecycle_status = get_session_field_sync(str(MAIN_DB_PATH), tc_id, _LIFECYCLE_STATUS_FIELD)
    if not isinstance(lifecycle_status, str):
        return _UNKNOWN_VALUE
    return _YES_VALUE if lifecycle_status in _RUNNING_SESSION_STATES else _NO_VALUE


def _detail_header_lines(resolution: MirrorResolution) -> list[str]:
    mirror = resolution.mirror
    header_lines = [mirror.title] if mirror is not None and mirror.title else []
    if mirror is not None and mirror.project:
        header_lines.append(f"Project: {mirror.project}")
    if mirror is not None and mirror.computer:
        header_lines.append(f"Computer: {mirror.computer}")
    if mirror is not None and mirror.timestamp_start:
        header_lines.append(f"Started: {_format_display_timestamp(mirror.timestamp_start)}")
    if mirror is not None and mirror.timestamp_end:
        header_lines.append(f"Ended: {_format_display_timestamp(mirror.timestamp_end)}")
    if mirror is not None:
        header_lines.append(f"Messages: {mirror.message_count}")
    header_lines.extend(
        [
            f"Running: {_running_state(resolution.tc_id)}",
            f"tc_id: {resolution.tc_id or _UNKNOWN_VALUE}",
            f"native_id: {resolution.native_id or _UNKNOWN_VALUE}",
            f"Requested as: {resolution.requested_namespace.value}",
            f"Source: {resolution.source.value}",
        ]
    )
    return header_lines


def _mirror_to_display(resolution: MirrorResolution) -> str:
    mirror = resolution.mirror
    header = "\n".join(_detail_header_lines(resolution))
    if mirror is None:
        return header
    body = mirror.conversation_text.rstrip()
    return f"{header}\n\n{body}".strip()


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
        "project": mirror.project if mirror is not None else None,
        "computer": mirror.computer if mirror is not None else None,
        "timestamp_start": mirror.timestamp_start if mirror is not None else None,
        "timestamp_end": mirror.timestamp_end if mirror is not None else None,
        "message_count": mirror.message_count if mirror is not None else None,
        "running": _running_state(resolution.tc_id),
        "raw": raw,
        "conversation_text": body,
    }


def _resolve_local_mirror(
    session_id: str,
    *,
    caller_email: str | None,
    caller_role: str | None,
) -> MirrorResolution:
    mirror = get_mirror(session_id, caller_email=caller_email, caller_role=caller_role)
    if mirror is not None:
        native_id = mirror.session_id
        tc_ids = get_session_ids_by_native_sync(
            str(MAIN_DB_PATH),
            [native_id] if native_id is not None else [],
        )
        return MirrorResolution(
            mirror=mirror,
            requested_id=session_id,
            requested_namespace=IdNamespace.NATIVE,
            tc_id=tc_ids.get(native_id) if native_id is not None else None,
            native_id=native_id,
            source=DetailSource.MIRROR,
        )

    resolved_native_id = get_session_field_sync(str(MAIN_DB_PATH), session_id, _NATIVE_SESSION_ID_FIELD)
    if isinstance(resolved_native_id, str) and resolved_native_id:
        translated_mirror = get_mirror(
            resolved_native_id,
            caller_email=caller_email,
            caller_role=caller_role,
        )
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


async def _search_through_daemon(
    *,
    computers: Sequence[str | None],
    search_term: str,
    agents: Sequence[AgentName],
    limit: int,
    include_workers: bool,
    identity: str | None,
    project: str | None,
) -> list[HistorySearchPayload | BaseException]:
    client = TelecAPIClient()
    await client.connect()
    try:
        agent_filter = ",".join(agent.value for agent in agents) if agents else "all"
        tasks = [
            client.search_history(
                query=search_term,
                agent=agent_filter,
                limit=limit,
                computer=computer,
                include_workers=include_workers,
                identity=identity,
                project=project,
            )
            for computer in computers
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await client.close()


def display_combined_history(
    agents: list[AgentName],
    search_term: str = "",
    limit: int = 20,
    computers: Sequence[str] | None = None,
    include_workers: bool = False,
    identity: str | None = None,
    project: str | None = None,
    json_output: bool = False,
) -> None:
    """Display session history using local mirrors or remote daemon search."""
    targets: Sequence[str | None] = computers if computers else [None]
    responses = asyncio.run(
        _search_through_daemon(
            computers=targets,
            search_term=search_term,
            agents=agents,
            limit=limit,
            include_workers=include_workers,
            identity=identity,
            project=project,
        )
    )
    results: list[HistorySearchRow] = []
    excluded_workers = 0
    for response, computer in zip(responses, targets, strict=True):
        if isinstance(response, BaseException):
            target = computer or "local"
            print(f"[{target}] History search failed: {response}", file=sys.stderr)
            continue
        results.extend(response["rows"])
        excluded_workers += response["excluded_workers"]
    if not results:
        if json_output:
            print(json.dumps([]))
            return
        scope = ", ".join(computers) if computers else ", ".join(agent.value for agent in agents)
        print(f"No conversations found matching '{search_term}' across {scope}")
        return
    results.sort(key=lambda entry: entry["sort_timestamp"], reverse=True)
    _print_results(
        search_term,
        results,
        show_computer=bool(computers),
        limit=limit,
        excluded_workers=excluded_workers,
        json_output=json_output,
    )


def show_transcript(
    agents: list[AgentName],
    session_id: str,
    include_thinking: bool = False,
    raw: bool = False,
    computers: Sequence[str] | None = None,
    caller_email: str | None = None,
    caller_role: str | None = None,
    json_output: bool = False,
) -> None:
    """Show a mirror or raw transcript for a local or remote session."""
    if computers:
        if len(computers) != 1:
            print("history show accepts exactly one --computer value")
            sys.exit(1)
        computer = computers[0]
        path = f"/api/mirrors/{session_id}/transcript" if raw else f"/api/mirrors/{session_id}"
        try:
            base_url = asyncio.run(resolve_remote_detail_base(computer))
            response = asyncio.run(get_remote_detail(base_url, path))
        except Exception as exc:
            print(f"Failed to fetch session '{session_id}' from {computer}: {exc}")
            sys.exit(1)
        if raw:
            if json_output:
                resolution = MirrorResolution(
                    mirror=None,
                    requested_id=session_id,
                    requested_namespace=IdNamespace.NATIVE,
                    tc_id=None,
                    native_id=session_id,
                    source=DetailSource.TRANSCRIPT,
                )
                print(json.dumps(_detail_json_payload(resolution, body=response.text, raw=True)))
            else:
                print(response.text)
            return
        payload = response.json()
        if not isinstance(payload, dict):
            print(f"Invalid mirror response for session '{session_id}'")
            sys.exit(1)
        mirror = MirrorRecord(
            session_id=str(payload.get("session_id", session_id)),
            computer=str(payload.get("computer", computer)),
            agent=str(payload.get("agent", "")),
            project=str(payload.get("project", "")),
            title=str(payload.get("title", "")),
            timestamp_start=payload.get("timestamp_start"),
            timestamp_end=payload.get("timestamp_end"),
            conversation_text=str(payload.get("conversation_text", "")),
            message_count=int(payload.get("message_count", 0) or 0),
            metadata={},
            created_at="",
            updated_at="",
        )
        resolution = MirrorResolution(
            mirror=mirror,
            requested_id=session_id,
            requested_namespace=IdNamespace.NATIVE,
            tc_id=None,
            native_id=mirror.session_id,
            source=DetailSource.MIRROR,
        )
        if json_output:
            print(
                json.dumps(
                    _detail_json_payload(
                        resolution,
                        body=mirror.conversation_text.rstrip(),
                        raw=False,
                    )
                )
            )
        else:
            print(_mirror_to_display(resolution))
        return

    transcript_fallback_allowed = caller_role is None or caller_role == HUMAN_ROLE_ADMIN
    resolution = _resolve_local_mirror(
        session_id,
        caller_email=caller_email,
        caller_role=caller_role,
    )
    mirror = resolution.mirror
    if mirror and not raw:
        if json_output:
            print(
                json.dumps(
                    _detail_json_payload(
                        resolution,
                        body=mirror.conversation_text.rstrip(),
                        raw=False,
                    )
                )
            )
        else:
            print(_mirror_to_display(resolution))
        return
    if mirror and raw:
        transcript_path = mirror.metadata.get("transcript_path")
        if isinstance(transcript_path, str) and transcript_path:
            path = Path(transcript_path).expanduser()  # type: ignore[assignment]
            if path.exists():  # type: ignore[attr-defined]
                raw_text = path.read_text(encoding="utf-8")  # type: ignore[attr-defined]
                if json_output:
                    print(json.dumps(_detail_json_payload(resolution, body=raw_text, raw=True)))
                else:
                    print(raw_text)
                return

    if not transcript_fallback_allowed:
        print(_TRANSCRIPT_NOT_FOUND.format(session_id=session_id))
        sys.exit(1)

    match = find_transcript(agents, session_id)
    if not match:
        print(_TRANSCRIPT_NOT_FOUND.format(session_id=session_id))
        sys.exit(1)

    path, agent = match  # type: ignore[assignment]
    rendered = parse_session_transcript(
        str(path),
        f"{agent.value} session - {path.stem}",  # type: ignore[attr-defined]
        agent_name=agent,
        tail_chars=0,
        include_thinking=include_thinking,
        include_tools=False,
    )
    if json_output:
        print(json.dumps(_detail_json_payload(resolution, body=rendered, raw=False)))
        return
    header = "\n".join(_detail_header_lines(resolution))
    print(f"{header}\n\n{rendered}".strip())


def parse_agents(agent_arg: str) -> list[AgentName]:
    """Parse agent argument into list of AgentName."""
    agent_arg = agent_arg.strip().lower()
    if agent_arg == "all":
        return [AgentName.CLAUDE, AgentName.CODEX, AgentName.GEMINI]

    agents: list[AgentName] = []
    for part in agent_arg.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            agents.append(AgentName.from_str(part))
        except ValueError:
            print(f"Unknown agent: {part}")
            sys.exit(1)
    return agents
