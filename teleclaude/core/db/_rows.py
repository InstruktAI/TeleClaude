"""Row TypedDicts for db queue tables."""

from typing import TypedDict


class HookOutboxRow(TypedDict):
    """Typed view of a hook outbox row fetched for delivery."""

    id: int
    session_id: str
    event_type: str
    payload: str
    created_at: str | None
    attempt_count: int


class InboundQueueRow(TypedDict):
    """Typed view of an inbound queue row fetched for delivery."""

    id: int
    session_id: str
    origin: str
    message_type: str
    text_kind: str
    source_feature: str
    occurrence_key: str | None
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
    was_held: bool
    hold_notice_pending: bool
    hold_notice_attempt_count: int
    hold_notice_next_retry_at: str | None
    hold_notice_error: str | None
    source_message_id: str | None
    source_channel_id: str | None
    caller_session_id: str | None
    caller_author_kind: str | None
    caller_author_display: str | None
    caller_agent_runtime: str | None
    caller_thinking_mode: str | None
    caller_machine_role: str | None
    caller_job_role: str | None
    caller_origin_prefix_len: int | None
    caller_origin_suffix_len: int | None
    binding_disposition: str | None
    reflection_claimed_at: str | None
    locked_at: str | None
    accepted_input_at: str | None
    accepted_runtime_turn_id: str | None


class OperationRow(TypedDict):
    """Typed view of a durable operation row."""

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
