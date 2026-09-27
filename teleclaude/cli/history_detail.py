"""Presentation for one local or remote history detail response."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence

from teleclaude.cli.session_auth import no_identity_refusal, require_cli_clearance
from teleclaude.config import config
from teleclaude.core.agents import AgentName
from teleclaude.core.command_dispatch import is_remote_target
from teleclaude.core.dates import format_utc_datetime, parse_iso_datetime
from teleclaude.history.remote_detail import get_remote_detail, resolve_remote_detail_base
from teleclaude.history.service import (
    DetailSource,
    HistoryDetailPayload,
    IdNamespace,
    MirrorResolution,
    _detail_json_payload,
    _remote_coverage_state,
    _remote_shrink_refused_at,
    build_history_detail_payload,
)
from teleclaude.mirrors.store import MirrorCoverageState, MirrorRecord, history_access_for_caller

__all__ = ["show_transcript"]

_REMOTE_RAW_MIRROR_PATH_TEMPLATE = "/api/mirrors/{session_id}/transcript"
_REMOTE_MIRROR_PATH_TEMPLATE = "/api/mirrors/{session_id}"
_TRANSCRIPT_NOT_FOUND = "No transcript found for session '{session_id}'"
_HISTORY_SHOW_ONE_COMPUTER_ERROR = "history show accepts exactly one --computer value"
_UNKNOWN_VALUE = "unknown"
_COVERAGE_LINE_TEMPLATE = "Coverage: through {timestamp_end}; state: {coverage_state}"
_RETAINED_COVERAGE_LINE_TEMPLATE = (
    "Coverage: through {timestamp_end}; state: {coverage_state}; shrink refusal observed: {shrink_refused_at}"
)


def _format_display_timestamp(value: str) -> str:
    parsed = parse_iso_datetime(value)
    return format_utc_datetime(parsed) if parsed is not None else value


def _coverage_header_line(payload: HistoryDetailPayload) -> str:
    timestamp_end = payload["timestamp_end"]
    timestamp = _format_display_timestamp(timestamp_end) if timestamp_end else _UNKNOWN_VALUE
    coverage_state = MirrorCoverageState(payload["coverage_state"])
    values = {
        "timestamp_end": timestamp,
        "coverage_state": coverage_state.value,
        "shrink_refused_at": payload["shrink_refused_at"] or _UNKNOWN_VALUE,
    }
    if coverage_state is MirrorCoverageState.RETAINED_AFTER_SHRINK:
        return _RETAINED_COVERAGE_LINE_TEMPLATE.format(**values)
    return _COVERAGE_LINE_TEMPLATE.format(**values)


def _detail_header_lines(payload: HistoryDetailPayload) -> list[str]:
    header_lines = [payload["title"]] if payload["title"] else []
    if payload["project"]:
        header_lines.append(f"Project: {payload['project']}")
    if payload["computer"]:
        header_lines.append(f"Computer: {payload['computer']}")
    if payload["timestamp_start"]:
        header_lines.append(f"Started: {_format_display_timestamp(payload['timestamp_start'])}")
    if payload["timestamp_end"]:
        header_lines.append(f"Ended: {_format_display_timestamp(payload['timestamp_end'])}")
    if payload["computer"] is not None:
        header_lines.append(f"Messages: {payload['message_count']}")
        header_lines.append(_coverage_header_line(payload))
    header_lines.extend(
        [
            f"Running: {payload['running']}",
            f"tc_id: {payload['tc_id'] or _UNKNOWN_VALUE}",
            f"native_id: {payload['native_id'] or _UNKNOWN_VALUE}",
            f"Requested as: {payload['requested_namespace']}",
            f"Source: {payload['source']}",
        ]
    )
    return header_lines


def render_history_detail(payload: HistoryDetailPayload, *, json_output: bool = False) -> None:
    """Render the published detail payload for terminal or JSON output."""
    if json_output:
        print(json.dumps(payload))
    elif payload["raw"]:
        print(payload["conversation_text"])
    else:
        header = "\n".join(_detail_header_lines(payload))
        body = payload["conversation_text"].rstrip()
        print(f"{header}\n\n{body}".strip() if body else header)


def show_transcript(
    agents: list[AgentName],
    session_id: str,
    include_thinking: bool = False,
    raw: bool = False,
    computers: Sequence[str] | None = None,
    json_output: bool = False,
) -> None:
    """Fetch and render one history detail for a local or remote computer."""
    if computers and len(computers) != 1:
        print(_HISTORY_SHOW_ONE_COMPUTER_ERROR)
        raise SystemExit(1)
    if computers and is_remote_target(computers[0], config.computer.name):
        _show_remote_detail(
            session_id,
            computer=computers[0],
            agent_count=len(computers),
            raw=raw,
            json_output=json_output,
        )
        return

    identity = require_cli_clearance("telec history show")
    access = history_access_for_caller(identity.caller)
    if access is None:
        print(f"Error: {no_identity_refusal(identity)}", file=sys.stderr)
        raise SystemExit(1)
    detail = build_history_detail_payload(
        session_id,
        access=access,
        agents=agents,
        include_thinking=include_thinking,
        raw=raw,
    )
    if detail is None:
        print(_TRANSCRIPT_NOT_FOUND.format(session_id=session_id))
        raise SystemExit(1)
    render_history_detail(detail, json_output=json_output)


def _show_remote_detail(
    session_id: str,
    *,
    computer: str,
    agent_count: int,
    raw: bool,
    json_output: bool,
) -> None:
    if agent_count != 1:
        print(_HISTORY_SHOW_ONE_COMPUTER_ERROR)
        raise SystemExit(1)
    path = (
        _REMOTE_RAW_MIRROR_PATH_TEMPLATE.format(session_id=session_id)
        if raw
        else _REMOTE_MIRROR_PATH_TEMPLATE.format(session_id=session_id)
    )
    try:
        base_url = asyncio.run(resolve_remote_detail_base(computer))
        response = asyncio.run(get_remote_detail(base_url, path))
    except Exception as exc:
        print(f"Failed to fetch session '{session_id}' from {computer}: {exc}")
        raise SystemExit(1) from exc

    if raw:
        resolution = MirrorResolution(
            mirror=None,
            requested_id=session_id,
            requested_namespace=IdNamespace.NATIVE,
            tc_id=None,
            native_id=session_id,
            source=DetailSource.TRANSCRIPT,
        )
        render_history_detail(_detail_json_payload(resolution, body=response.text, raw=True), json_output=json_output)
        return

    payload = response.json()
    if not isinstance(payload, dict):
        print(f"Invalid mirror response for session '{session_id}'")
        raise SystemExit(1)
    try:
        mirror = MirrorRecord(
            native_session_id=str(payload.get("session_id", session_id)),
            session_id=None,
            position=None,
            computer=str(payload.get("computer", computer)),
            agent=str(payload.get("agent", "")),
            project_path=str(payload.get("project", "")),
            title=str(payload.get("title", "")),
            timestamp_start=payload.get("timestamp_start"),
            timestamp_end=payload.get("timestamp_end"),
            conversation_text=str(payload.get("conversation_text", "")),
            message_count=int(payload.get("message_count", 0) or 0),
            metadata={},
            created_at="",
            updated_at="",
            coverage_state=_remote_coverage_state(payload),
            shrink_refused_at=_remote_shrink_refused_at(payload),
        )
    except ValueError as exc:
        print(f"Invalid mirror response for session '{session_id}': {exc}")
        raise SystemExit(1) from exc
    resolution = MirrorResolution(
        mirror=mirror,
        requested_id=session_id,
        requested_namespace=IdNamespace.NATIVE,
        tc_id=mirror.session_id,
        native_id=mirror.native_session_id,
        source=DetailSource.MIRROR,
    )
    detail = _detail_json_payload(resolution, body=mirror.conversation_text.rstrip(), raw=False)
    render_history_detail(detail, json_output=json_output)
