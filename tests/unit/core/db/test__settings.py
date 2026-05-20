from __future__ import annotations

import pytest

from teleclaude.core.db import Db
from teleclaude.core.voice_assignment import VoiceConfig

pytestmark = pytest.mark.asyncio


async def test_system_setting_round_trips_through_upsert(db: Db) -> None:
    assert await db.get_system_setting("theme") is None

    await db.set_system_setting("theme", "light")
    await db.set_system_setting("theme", "dark")

    assert await db.get_system_setting("theme") == "dark"


async def test_assign_voice_and_get_voice_return_latest_assignment(db: Db) -> None:
    await db.assign_voice("sess-001", VoiceConfig(service_name="openai", voice="alloy"))
    await db.assign_voice("sess-001", VoiceConfig(service_name="openai", voice="verse"))

    voice = await db.get_voice("sess-001")

    assert voice == VoiceConfig(service_name="openai", voice="verse")


async def test_get_voices_in_use_only_counts_non_closed_sessions(db: Db, cluster_event_bus: None) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-active",
        last_input_origin="telegram",
        title="Active",
        session_id="sess-active",
        emit_session_started=False,
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
    await db.assign_voice("sess-active", VoiceConfig(service_name="openai", voice="alloy"))
    await db.assign_voice("sess-closed", VoiceConfig(service_name="openai", voice="nova"))
    await db.assign_voice("orphan", VoiceConfig(service_name="macos", voice="Samantha"))

    voices = await db.get_voices_in_use()

    assert voices == {("openai", "alloy")}


async def test_cleanup_stale_voice_assignments_keeps_open_teleclaude_and_native_session_rows(
    db: Db,
    cluster_event_bus: None,
) -> None:
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-active",
        last_input_origin="api",
        title="Active",
        session_id="sess-active",
        native_session_id="native-active",
        emit_session_started=False,
    )
    await db.create_session(
        computer_name="builder-mac",
        tmux_session_name="tmux-closed",
        last_input_origin="api",
        title="Closed",
        session_id="sess-closed",
        native_session_id="native-closed",
        emit_session_started=False,
    )
    await db.close_session("sess-closed")
    await db.assign_voice("sess-active", VoiceConfig(service_name="openai", voice="alloy"))
    await db.assign_voice("native-active", VoiceConfig(service_name="openai", voice="verse"))
    await db.assign_voice("sess-closed", VoiceConfig(service_name="macos", voice="Samantha"))
    await db.assign_voice("orphan", VoiceConfig(service_name="macos", voice="Alex"))

    deleted = await db.cleanup_stale_voice_assignments()

    assert deleted == 2
    assert await db.get_voice("sess-active") == VoiceConfig(service_name="openai", voice="alloy")
    assert await db.get_voice("native-active") == VoiceConfig(service_name="openai", voice="verse")
    assert await db.get_voice("sess-closed") is None
    assert await db.get_voice("orphan") is None
