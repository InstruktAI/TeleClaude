from __future__ import annotations

from teleclaude.core.db._rows import HookOutboxRow, InboundQueueRow, OperationRow


def test_hook_outbox_row_declares_the_expected_required_keys() -> None:
    assert HookOutboxRow.__required_keys__ == {
        "id",
        "session_id",
        "event_type",
        "payload",
        "created_at",
        "attempt_count",
    }


def test_inbound_queue_row_declares_the_expected_required_keys() -> None:
    assert InboundQueueRow.__required_keys__ == {
        "id",
        "session_id",
        "origin",
        "message_type",
        "content",
        "payload_json",
        "actor_id",
        "actor_name",
        "actor_avatar_url",
        "status",
        "created_at",
        "attempt_count",
        "next_retry_at",
        "last_error",
        "source_message_id",
        "source_channel_id",
    }


def test_operation_row_declares_the_expected_required_keys() -> None:
    assert OperationRow.__required_keys__ == {
        "operation_id",
        "kind",
        "caller_session_id",
        "client_request_id",
        "cwd",
        "slug",
        "state",
        "progress_phase",
        "progress_decision",
        "progress_reason",
        "result_text",
        "error_text",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "heartbeat_at",
        "attempt_count",
    }
