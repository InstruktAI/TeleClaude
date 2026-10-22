"""Inspection of one stored session record: the complete view and its grouped curated projection."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Final

from teleclaude.caller_identity import CliCaller
from teleclaude.core.db import SessionRecordFound, SessionRecordRead, db
from teleclaude.core.github_identity import read_origin_github_posting_binding
from teleclaude.core.models import JsonDict, JsonValue
from teleclaude.core.models._types import to_json_dict, to_json_value
from teleclaude.core.session_listing import build_session_listing_selection
from teleclaude.types.github_binding import (
    GITHUB_POSTING_RELATED_FIELD,
    GitHubOriginBindingRead,
    GitHubOriginBindingRefusal,
)

_JSON_SERIALIZATION_MODE = "json"

OUTSIDE_REACH_DETAIL_TEMPLATE: Final[str] = (
    "session {session_id} exists on {computer} but is outside your reach; "
    "run `telec sessions list` to see the sessions you can reach"
)


class SessionColumn(StrEnum):
    """Stored session columns that inspection excludes, decodes, or groups by name."""

    SESSION_ID = "session_id"
    COMPUTER_NAME = "computer_name"
    NATIVE_SESSION_ID = "native_session_id"
    ACTIVE_AGENT = "active_agent"
    THINKING_MODE = "thinking_mode"
    PROJECT_PATH = "project_path"
    SUBDIR = "subdir"
    INITIATOR_SESSION_ID = "initiator_session_id"
    INITIATOR_COMPUTER = "initiator_computer"
    PRINCIPAL = "principal"
    HUMAN_EMAIL = "human_email"
    HUMAN_ROLE = "human_role"
    COMMAND = "command"
    WORKING_SLUG = "working_slug"
    JOB = "job"
    ROLE = "role"
    COMPANY = "company"
    VISIBILITY = "visibility"
    LIFECYCLE_STATUS = "lifecycle_status"
    LIFECYCLE_TRANSITIONED_AT = "lifecycle_transitioned_at"
    LIFECYCLE_TRANSITION_REASON = "lifecycle_transition_reason"
    AGENT_STATUS = "agent_status"
    AGENT_STATUS_REASON = "agent_status_reason"
    AGENT_STATUS_SINCE = "agent_status_since"
    RUNTIME_START_OBSERVED = "runtime_start_observed"
    RUNTIME_ACTIVITY_AT = "runtime_activity_at"
    CREATED_AT = "created_at"
    LAST_ACTIVITY = "last_activity"
    CLOSED_AT = "closed_at"
    OPEN_TOOL_CALLS = "open_tool_calls"
    TMUX_SESSION_NAME = "tmux_session_name"
    NATIVE_LOG_FILE = "native_log_file"
    TUI_LOG_FILE = "tui_log_file"
    TRANSCRIPT_FILES = "transcript_files"
    ADAPTER_METADATA = "adapter_metadata"
    ORIGIN_METADATA = "origin_metadata"
    TURN_NOTIFICATIONS_SENT = "turn_notifications_sent"
    LAST_OUTPUT_RAW = "last_output_raw"
    LAST_MESSAGE_SENT = "last_message_sent"
    RELAY_EXCHANGE = "relay_exchange"
    AGENT_STATUS_VERSION = "agent_status_version"


class InspectionGroup(StrEnum):
    """Groups of the curated view, in reading order."""

    IDENTITY = "identity"
    ORIGIN = "origin"
    ROLE = "role"
    STATE = "state"
    WIRING = "wiring"


# Columns the complete view leaves out: full last-output text and relay exchange content are the
# transcript's, the accepted-input fingerprint is only a comparison key, and the agent-status
# version is an optimistic-concurrency counter.
EXCLUDED_COLUMNS: Final[frozenset[SessionColumn]] = frozenset(
    {
        SessionColumn.LAST_OUTPUT_RAW,
        SessionColumn.LAST_MESSAGE_SENT,
        SessionColumn.RELAY_EXCHANGE,
        SessionColumn.AGENT_STATUS_VERSION,
    }
)

# Columns the record stores as JSON text, presented decoded.
JSON_ENCODED_COLUMNS: Final[frozenset[SessionColumn]] = frozenset(
    {
        SessionColumn.ADAPTER_METADATA,
        SessionColumn.ORIGIN_METADATA,
        SessionColumn.TURN_NOTIFICATIONS_SENT,
        SessionColumn.OPEN_TOOL_CALLS,
        SessionColumn.TRANSCRIPT_FILES,
    }
)

# The record's parent link is its initiator session, so that column reads under both origin and wiring.
CURATED_GROUP_COLUMNS: Final[dict[InspectionGroup, tuple[SessionColumn, ...]]] = {
    InspectionGroup.IDENTITY: (
        SessionColumn.SESSION_ID,
        SessionColumn.NATIVE_SESSION_ID,
        SessionColumn.ACTIVE_AGENT,
        SessionColumn.THINKING_MODE,
        SessionColumn.COMPUTER_NAME,
        SessionColumn.PROJECT_PATH,
        SessionColumn.SUBDIR,
    ),
    InspectionGroup.ORIGIN: (
        SessionColumn.INITIATOR_SESSION_ID,
        SessionColumn.PRINCIPAL,
        SessionColumn.HUMAN_EMAIL,
        SessionColumn.HUMAN_ROLE,
        SessionColumn.COMMAND,
        SessionColumn.WORKING_SLUG,
        SessionColumn.JOB,
        SessionColumn.INITIATOR_COMPUTER,
    ),
    InspectionGroup.ROLE: (
        SessionColumn.ROLE,
        SessionColumn.JOB,
        SessionColumn.COMPANY,
        SessionColumn.VISIBILITY,
    ),
    InspectionGroup.STATE: (
        SessionColumn.LIFECYCLE_STATUS,
        SessionColumn.LIFECYCLE_TRANSITIONED_AT,
        SessionColumn.LIFECYCLE_TRANSITION_REASON,
        SessionColumn.AGENT_STATUS,
        SessionColumn.AGENT_STATUS_REASON,
        SessionColumn.AGENT_STATUS_SINCE,
        SessionColumn.RUNTIME_START_OBSERVED,
        SessionColumn.RUNTIME_ACTIVITY_AT,
        SessionColumn.CREATED_AT,
        SessionColumn.LAST_ACTIVITY,
        SessionColumn.CLOSED_AT,
        SessionColumn.OPEN_TOOL_CALLS,
    ),
    InspectionGroup.WIRING: (
        SessionColumn.TMUX_SESSION_NAME,
        SessionColumn.NATIVE_LOG_FILE,
        SessionColumn.TUI_LOG_FILE,
        SessionColumn.TRANSCRIPT_FILES,
        SessionColumn.INITIATOR_SESSION_ID,
    ),
}


def complete_record(stored: JsonDict) -> JsonDict:
    """Return the stored record without its exclusions and with encoded columns decoded."""
    record: JsonDict = {}
    for column, value in stored.items():
        if column in EXCLUDED_COLUMNS:
            continue
        record[column] = _decoded(value) if column in JSON_ENCODED_COLUMNS else value
    return record


def curated_view(record: JsonDict) -> JsonDict:
    """Project the grouped diagnostic detail from a complete record."""
    view: JsonDict = {}
    for group, columns in CURATED_GROUP_COLUMNS.items():
        view[group.value] = {column.value: record[column] for column in columns if column in record}
    return view


async def inspect_local(caller: CliCaller, session_id: str) -> SessionRecordRead:
    """Read this computer's stored record of one session under the caller's listing reach."""
    selection = build_session_listing_selection(caller, include_closed=False, session_ids=frozenset({session_id}))
    read = await db.read_session_record_for_reach(selection.reach, session_id)
    if isinstance(read, SessionRecordFound):
        return SessionRecordFound(complete_record(read.values))
    return read


async def inspect_relayed(caller: CliCaller, session_id: str, principal: str) -> SessionRecordRead:
    """Extend only the existing reached internal read, leaving diagnostic records and refusals intact."""
    before = await inspect_local(caller, session_id)
    if not isinstance(before, SessionRecordFound):
        return before
    related = await read_origin_github_posting_binding(session_id, principal)
    after = await inspect_local(caller, session_id)
    if not isinstance(after, SessionRecordFound):
        return after
    if before.values != after.values:
        related = GitHubOriginBindingRead(refusal=GitHubOriginBindingRefusal.RECORD_CHANGED)
    return SessionRecordFound(
        {
            **after.values,
            GITHUB_POSTING_RELATED_FIELD: to_json_dict(related.model_dump(mode=_JSON_SERIALIZATION_MODE)),
        }
    )


def _decoded(value: JsonValue) -> JsonValue:
    if not isinstance(value, str):
        return value
    try:
        return to_json_value(json.loads(value))
    except json.JSONDecodeError:
        # The view shows what the record stores; text that is not valid JSON is kept as stored.
        return value
