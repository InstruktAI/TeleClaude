"""Row TypedDicts for db queue tables."""

from typing_extensions import TypedDict


class HookOutboxRow(TypedDict):
    id: int
    session_id: str
    event_type: str
    payload: str
    created_at: str | None
    attempt_count: int


class InboundQueueRow(TypedDict):
    id: int
    session_id: str
    origin: str
    message_type: str
    content: str
    payload_json: str | None
    actor_id: str | None
    actor_name: str | None
    actor_avatar_url: str | None
    status: str
    created_at: str
    attempt_count: int
    next_retry_at: str | None
    last_error: str | None
    source_message_id: str | None
    source_channel_id: str | None


class OperationRow(TypedDict):
    operation_id: str
    kind: str
    caller_session_id: str
    client_request_id: str | None
    cwd: str
    slug: str | None
    state: str
    progress_phase: str | None
    progress_decision: str | None
    progress_reason: str | None
    result_text: str | None
    error_text: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
    heartbeat_at: str | None
    attempt_count: int
