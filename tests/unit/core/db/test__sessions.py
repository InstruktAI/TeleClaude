# pylint: disable=too-many-locals,import-outside-toplevel
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import SessionField

pytestmark = pytest.mark.asyncio


def _section(data: dict[str, object], key: str) -> dict[str, Any]:  # guard: loose-dict - JSON section extract
    """Extract a platform section from origin_metadata, narrowing the type."""
    val = data[key]
    assert isinstance(val, dict)
    return cast(dict[str, Any], val)  # guard: loose-dict - runtime-checked above


async def _create_headless_via_command(
    db: Db,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    session_id: str,
    title: str,
    active_agent: str | None,
    native_session_id: str | None,
    native_log_file: str | None,
    subdir: str | None,
) -> str:
    from teleclaude.core.command_handlers import _session
    from teleclaude.core.models import SessionLaunchIntent, SessionLaunchKind
    from teleclaude.core.models._adapter import TerminalOriginMetadata
    from teleclaude.types.commands import CreateSessionCommand

    project_path = tmp_path / "project"
    project_path.mkdir(exist_ok=True)
    help_desk = tmp_path / "help-desk"

    resolver = SimpleNamespace(
        resolve=lambda _origin, _metadata: SimpleNamespace(
            person_email="admin@example.com",
            person_role="admin",
            platform="terminal",
            platform_user_id="admin@example.com",
        )
    )
    monkeypatch.setattr(_session, "db", db)
    monkeypatch.setattr(
        _session,
        "config",
        SimpleNamespace(computer=SimpleNamespace(name="builder-mac", help_desk_dir=str(help_desk))),
    )
    monkeypatch.setattr(_session, "get_identity_resolver", lambda: resolver)

    cmd = CreateSessionCommand(
        session_id=session_id,
        headless=True,
        native_session_id=native_session_id,
        native_log_file=native_log_file,
        project_path=str(project_path),
        title=title,
        subdir=subdir,
        origin="terminal",
        origin_metadata=TerminalOriginMetadata(email="admin@example.com"),
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            agent=active_agent,
            native_session_id=native_session_id,
        ),
    )
    result = await _session.create_session(cmd, MagicMock())
    return str(result["session_id"])


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


async def test_create_session_persists_detached_true(db: Db) -> None:
    session = await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-detached",
        last_input_origin="telegram",
        title="Detached",
        session_id="sess-detached",
        detached=True,
        emit_session_started=False,
    )

    stored = await db.get_session(session.session_id)

    assert session.detached is True
    assert stored is not None
    assert stored.detached is True


async def test_create_session_defaults_detached_to_false(db: Db) -> None:
    session = await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-attached",
        last_input_origin="telegram",
        title="Attached",
        session_id="sess-attached",
        emit_session_started=False,
    )

    stored = await db.get_session(session.session_id)

    assert session.detached is False
    assert stored is not None
    assert stored.detached is False


async def test_headless_command_path_persists_headless_without_emitting_started_event(
    db: Db,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with patch("teleclaude.core.db._sessions.event_bus.emit") as mock_emit:
        created_session_id = await _create_headless_via_command(
            db,
            monkeypatch,
            tmp_path,
            session_id="headless-001",
            title="Headless",
            active_agent="codex",
            native_session_id="native-123",
            native_log_file="/tmp/native.log",
            subdir=None,
        )
        session = await db.get_session(created_session_id)
        assert session is not None

    stored = await db.get_session("headless-001")

    assert session.tmux_session_name == ""
    assert stored is not None
    assert stored.lifecycle_status == "headless"
    assert stored.native_session_id == "native-123"
    assert mock_emit.call_count == 0


async def test_session_queries_apply_lifecycle_filters_and_counts(
    db: Db,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
    headless_session_id = await _create_headless_via_command(
        db,
        monkeypatch,
        tmp_path,
        session_id="sess-headless",
        title="Headless",
        active_agent="codex",
        native_session_id="native-1",
        native_log_file="/tmp/native.log",
        subdir=None,
    )
    headless = await db.get_session(headless_session_id)
    assert headless is not None
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


async def test_update_session_persists_fields_auto_timestamps_and_emits_updated_event(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="Mutable",
        session_id="sess-001",
        emit_session_started=False,
    )
    stop_at = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
    with patch("teleclaude.core.db._sessions.event_bus.emit") as mock_emit:
        await db.update_session(
            "sess-001",
            last_message_sent="hello",
            last_output_raw="summary",
            last_agent_stop_at=stop_at.isoformat(),
            invalid_field="ignored",
        )

    session = await db.get_session("sess-001")

    assert session is not None
    assert session.last_message_sent == "hello"
    assert session.last_message_sent_at is not None
    assert session.last_output_raw == "summary"
    assert session.last_output_at is not None
    assert session.last_agent_stop_at == stop_at
    assert mock_emit.call_count == 1
    assert mock_emit.call_args.args[0] == TeleClaudeEvents.SESSION_UPDATED
    assert mock_emit.call_args.args[1].session_id == "sess-001"
    assert set(mock_emit.call_args.args[1].updated_fields) >= {
        SessionField.LAST_MESSAGE_SENT.value,
        SessionField.LAST_MESSAGE_SENT_AT.value,
        SessionField.LAST_OUTPUT_RAW.value,
        SessionField.LAST_OUTPUT_AT.value,
        SessionField.LAST_AGENT_STOP_AT.value,
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


async def test_update_origin_metadata_creates_section_for_new_platform(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="Origin Test",
        session_id="sess-origin",
        emit_session_started=False,
    )
    await db.update_origin_metadata("sess-origin", "telegram", {"topic_id": 42, "user_id": 99})
    session = await db.get_session("sess-origin")

    assert session is not None
    data = session.origin_metadata
    tg = _section(data, "telegram")
    assert tg["topic_id"] == 42
    assert tg["user_id"] == 99


async def test_update_origin_metadata_preserves_other_platform_sections(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="Multi Platform",
        session_id="sess-multi",
        emit_session_started=False,
    )
    await db.update_origin_metadata("sess-multi", "telegram", {"topic_id": 42})
    await db.update_origin_metadata("sess-multi", "discord", {"guild_id": 100})
    session = await db.get_session("sess-multi")

    assert session is not None
    data = session.origin_metadata
    assert _section(data, "telegram")["topic_id"] == 42
    assert _section(data, "discord")["guild_id"] == 100


async def test_update_origin_metadata_merges_within_platform_section(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="Merge Test",
        session_id="sess-merge",
        emit_session_started=False,
    )
    await db.update_origin_metadata("sess-merge", "telegram", {"topic_id": 42})
    await db.update_origin_metadata("sess-merge", "telegram", {"user_id": 99})
    session = await db.get_session("sess-merge")

    assert session is not None
    data = session.origin_metadata
    tg = _section(data, "telegram")
    assert tg["topic_id"] == 42
    assert tg["user_id"] == 99


async def test_update_origin_metadata_none_removes_existing_platform_keys(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="Delete Keys Test",
        session_id="sess-delete-keys",
        emit_session_started=False,
    )
    await db.update_origin_metadata(
        "sess-delete-keys",
        "telegram",
        {"topic_id": 42, "output_message_id": "out-1", "char_offset": 7},
    )
    await db.update_origin_metadata(
        "sess-delete-keys",
        "telegram",
        {"topic_id": None, "output_message_id": None, "char_offset": 0},
    )
    session = await db.get_session("sess-delete-keys")

    assert session is not None
    tg = _section(session.origin_metadata, "telegram")
    assert "topic_id" not in tg
    assert "output_message_id" not in tg
    assert tg["char_offset"] == 0


async def test_update_origin_metadata_on_no_prior_metadata(db: Db) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title="No Prior",
        session_id="sess-empty",
        emit_session_started=False,
    )
    session_before = await db.get_session("sess-empty")
    assert session_before is not None
    tg_before = session_before.origin_metadata.get("telegram")
    assert not isinstance(tg_before, dict) or "topic_id" not in tg_before

    await db.update_origin_metadata("sess-empty", "telegram", {"topic_id": 1})
    session = await db.get_session("sess-empty")

    assert session is not None
    data = session.origin_metadata
    assert _section(data, "telegram")["topic_id"] == 1


async def test_adapter_metadata_and_title_pattern_queries_apply_current_filters(
    db: Db,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-active",
        last_input_origin="telegram",
        title="Task Active",
        session_id="sess-active",
        system_role="worker",
        job="chartest",
        emit_session_started=False,
    )
    await db.update_session("sess-active", origin_metadata='{"telegram": {"topic_id": 42}}')
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-closed",
        last_input_origin="telegram",
        title="Task Closed",
        session_id="sess-closed",
        emit_session_started=False,
    )
    await db.update_session("sess-closed", origin_metadata='{"telegram": {"topic_id": 42}}')
    await db.close_session("sess-closed")
    await _create_headless_via_command(
        db,
        monkeypatch,
        tmp_path,
        session_id="sess-headless",
        title="Task Headless",
        active_agent="codex",
        native_session_id="native-1",
        native_log_file="/tmp/native.log",
        subdir=None,
    )

    adapter_matches = await db.get_sessions_by_origin_metadata("telegram", "topic_id", 42)
    title_matches = await db.get_sessions_by_title_pattern("Task")

    assert [session.session_id for session in adapter_matches] == ["sess-active"]
    assert [session.session_id for session in title_matches] == ["sess-active"]
