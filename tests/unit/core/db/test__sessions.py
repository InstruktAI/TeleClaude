from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import SessionAdapterMetadata, SessionField, SessionMetadata, TelegramAdapterMetadata

pytestmark = pytest.mark.asyncio


async def test_create_session_uses_default_title_and_emits_started_event(db: Db) -> None:
    with patch("teleclaude.core.db._sessions.event_bus.emit") as mock_emit:
        session = await db.create_session(
            computer_name="builder-mac",
            tmux_session_name="tmux-001",
            last_input_origin="telegram",
            title="",
            emit_session_started=True,
        )

    stored = await db.get_session(session.session_id)

    assert session.title == "[builder-mac] Untitled"
    assert stored is not None
    assert stored.title == "[builder-mac] Untitled"
    assert mock_emit.call_count == 1
    assert mock_emit.call_args.args[0] == TeleClaudeEvents.SESSION_STARTED
    assert mock_emit.call_args.args[1].session_id == session.session_id


async def test_create_headless_session_persists_headless_without_emitting_started_event(db: Db) -> None:
    with patch("teleclaude.core.db._sessions.event_bus.emit") as mock_emit:
        session = await db.create_headless_session(
            session_id="headless-001",
            computer_name="builder-mac",
            last_input_origin="api",
            title="Headless",
            active_agent="codex",
            native_session_id="native-123",
            native_log_file="/tmp/native.log",
            project_path="/repo",
            subdir="worktree",
            human_role="admin",
        )

    stored = await db.get_session("headless-001")

    assert session.tmux_session_name == ""
    assert stored is not None
    assert stored.lifecycle_status == "headless"
    assert stored.native_session_id == "native-123"
    assert mock_emit.call_count == 0


async def test_session_queries_apply_lifecycle_filters_and_counts(db: Db) -> None:
    active = await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-active",
        last_input_origin="telegram",
        title="Active",
        session_id="sess-active",
        emit_session_started=False,
    )
    initializing = await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-init",
        last_input_origin="telegram",
        title="Initializing",
        session_id="sess-init",
        lifecycle_status="initializing",
        emit_session_started=False,
    )
    headless = await db.create_headless_session(
        session_id="sess-headless",
        computer_name="builder-mac",
        last_input_origin="api",
        title="Headless",
        active_agent="codex",
        native_session_id="native-1",
        native_log_file="/tmp/native.log",
        project_path="/repo",
        subdir=None,
        human_role="admin",
    )
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-closed",
        last_input_origin="telegram",
        title="Closed",
        session_id="sess-closed",
        emit_session_started=False,
    )
    await db.close_session("sess-closed")

    await db.update_session(active.session_id, last_activity=datetime.now(UTC) + timedelta(minutes=3))
    await db.update_session(initializing.session_id, last_activity=datetime.now(UTC) + timedelta(minutes=2))
    await db.update_session(headless.session_id, last_activity=datetime.now(UTC) + timedelta(minutes=1))

    default_sessions = await db.list_sessions()
    with_initializing = await db.list_sessions(include_initializing=True)
    with_headless = await db.list_sessions(include_headless=True)
    with_closed = await db.list_sessions(include_closed=True)
    by_field_default = await db.get_session_by_field("native_session_id", "native-1")
    by_field_initializing = await db.get_session_by_field("session_id", "sess-init", include_initializing=True)
    count_all = await db.count_sessions()
    count_builder = await db.count_sessions(computer_name="builder-mac")
    all_sessions = await db.get_all_sessions()
    active_sessions = await db.get_active_sessions()

    assert [session.session_id for session in default_sessions] == ["sess-active"]
    assert [session.session_id for session in with_initializing] == ["sess-active", "sess-init"]
    assert [session.session_id for session in with_headless] == ["sess-active", "sess-headless"]
    assert [session.session_id for session in with_closed] == ["sess-active", "sess-init", "sess-closed"]
    assert by_field_default is None
    assert by_field_initializing is not None
    assert by_field_initializing.session_id == "sess-init"
    assert count_all == 4
    assert count_builder == 4
    assert [session.session_id for session in all_sessions] == [
        "sess-active",
        "sess-init",
        "sess-headless",
        "sess-closed",
    ]
    assert [session.session_id for session in active_sessions] == ["sess-active"]


async def test_update_session_persists_adapter_metadata_auto_timestamps_and_emits_updated_event(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="Mutable",
        session_id="sess-001",
        emit_session_started=False,
    )
    with patch("teleclaude.core.db._sessions.event_bus.emit") as mock_emit:
        await db.update_session(
            "sess-001",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(output_suppressed=True)),
            last_message_sent="hello",
            last_output_raw="summary",
            invalid_field="ignored",
        )

    session = await db.get_session("sess-001")

    assert session is not None
    assert session.adapter_metadata.get_ui().get_telegram().output_suppressed is True
    assert session.last_message_sent == "hello"
    assert session.last_message_sent_at is not None
    assert session.last_output_raw == "summary"
    assert session.last_output_at is not None
    assert mock_emit.call_count == 1
    assert mock_emit.call_args.args[0] == TeleClaudeEvents.SESSION_UPDATED
    assert mock_emit.call_args.args[1].session_id == "sess-001"
    assert set(mock_emit.call_args.args[1].updated_fields) >= {
        SessionField.ADAPTER_METADATA.value,
        SessionField.LAST_MESSAGE_SENT.value,
        SessionField.LAST_MESSAGE_SENT_AT.value,
        SessionField.LAST_OUTPUT_RAW.value,
        SessionField.LAST_OUTPUT_AT.value,
    }


async def test_digest_only_and_redundant_session_updates_skip_event_emission(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="Stable",
        session_id="sess-001",
        emit_session_started=False,
    )
    with patch("teleclaude.core.db._sessions.event_bus.emit") as mock_emit:
        await db.update_session("sess-001", last_output_digest="digest-1")
        await db.update_session("sess-001", title="Stable")

    session = await db.get_session("sess-001")

    assert session is not None
    assert session.last_output_digest == "digest-1"
    assert mock_emit.call_count == 0


async def test_close_session_is_idempotent_and_delete_session_emits_close_for_existing_row(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-close",
        last_input_origin="telegram",
        title="Closable",
        session_id="sess-close",
        emit_session_started=False,
    )
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-delete",
        last_input_origin="telegram",
        title="Deletable",
        session_id="sess-delete",
        emit_session_started=False,
    )
    with patch("teleclaude.core.db._sessions.event_bus.emit") as mock_emit:
        await db.close_session("sess-close")
        await db.close_session("sess-close")
        await db.delete_session("sess-delete")

    closed = await db.get_session("sess-close")
    deleted = await db.get_session("sess-delete")
    close_events = [call for call in mock_emit.call_args_list if call.args[0] == TeleClaudeEvents.SESSION_CLOSED]

    assert closed is not None
    assert closed.lifecycle_status == "closed"
    assert closed.closed_at is not None
    assert deleted is None
    assert [call.args[1].session_id for call in close_events] == ["sess-close", "sess-delete"]


async def test_pending_deletions_output_message_and_notification_helpers_round_trip(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="Helpers",
        session_id="sess-001",
        emit_session_started=False,
    )
    await db.add_pending_deletion("sess-001", "msg-1")
    await db.add_pending_deletion("sess-001", "msg-2", deletion_type="feedback")
    await db.set_output_message_id("sess-001", "out-1")
    await db.set_notification_flag("sess-001", True)

    user_pending = await db.get_pending_deletions("sess-001")
    feedback_pending = await db.get_pending_deletions("sess-001", deletion_type="feedback")
    output_message_id = await db.get_output_message_id("sess-001")
    field_value = await db.get_session_field("sess-001", "output_message_id")
    invalid_field = await db.get_session_field("sess-001", "not_a_field")
    notification_before_clear = await db.get_notification_flag("sess-001")

    await db.clear_pending_deletions("sess-001")
    await db.clear_pending_deletions("sess-001", deletion_type="feedback")
    await db.clear_notification_flag("sess-001")
    notification_after_clear = await db.get_notification_flag("sess-001")

    assert user_pending == ["msg-1"]
    assert feedback_pending == ["msg-2"]
    assert output_message_id == "out-1"
    assert field_value == "out-1"
    assert invalid_field is None
    assert notification_before_clear is True
    assert notification_after_clear is False
    assert await db.get_pending_deletions("sess-001") == []
    assert await db.get_pending_deletions("sess-001", deletion_type="feedback") == []


async def test_adapter_metadata_and_title_pattern_queries_apply_current_filters(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-active",
        last_input_origin="telegram",
        title="Task Active",
        session_id="sess-active",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=42)),
        session_metadata=SessionMetadata(system_role="worker", job="chartest"),
        emit_session_started=False,
    )
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-closed",
        last_input_origin="telegram",
        title="Task Closed",
        session_id="sess-closed",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=42)),
        emit_session_started=False,
    )
    await db.close_session("sess-closed")
    await db.create_headless_session(
        session_id="sess-headless",
        computer_name="builder-mac",
        last_input_origin="api",
        title="Task Headless",
        active_agent="codex",
        native_session_id="native-1",
        native_log_file="/tmp/native.log",
        project_path="/repo",
        subdir=None,
        human_role="admin",
    )

    adapter_matches = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", 42)
    title_matches = await db.get_sessions_by_title_pattern("Task")

    assert [session.session_id for session in adapter_matches] == ["sess-active"]
    assert [session.session_id for session in title_matches] == ["sess-active"]
