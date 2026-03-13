"""Unit tests for integration_bridge.spawn_integrator_session,
CommandService.run_slash_command, and Db SessionMetadata serialization.

Covers the code paths introduced in the fix-integrator-spawn-broken-integration-brid fix:
- spawn_integrator_session guard (already running) and spawn branches
- CommandService.run_slash_command SessionMetadata and auto_command construction
- Db._serialize_session_metadata and Db._to_core_session round-trip
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from teleclaude.constants import ROLE_INTEGRATOR, JobRole, SlashCommand
from teleclaude.core.models import SessionMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_row(session_metadata: str | None = None) -> MagicMock:
    """Minimal db_models.Session stub for _to_core_session tests."""
    row = MagicMock()
    row.session_id = "test-session-1"
    row.computer_name = "local"
    row.tmux_session_name = None
    row.title = ""
    row.last_input_origin = None
    row.adapter_metadata = None
    row.session_metadata = session_metadata
    # datetime fields — all None so _coerce_datetime returns None
    row.created_at = None
    row.last_activity = None
    row.closed_at = None
    row.last_message_sent_at = None
    row.last_output_at = None
    row.last_tool_done_at = None
    row.last_tool_use_at = None
    row.last_checkpoint_at = None
    row.last_memory_extraction_at = None
    row.help_desk_processed_at = None
    row.relay_started_at = None
    # bool fields — explicit values to avoid MagicMock truthiness surprises
    row.initiated_by_ai = None
    row.notification_sent = None
    row.tui_capture_started = None
    # int field — None triggers the else branch in _to_core_session
    row.char_offset = None
    row.lifecycle_status = "active"
    row.transcript_files = "[]"
    return row


# ---------------------------------------------------------------------------
# Db._serialize_session_metadata
# ---------------------------------------------------------------------------


def test_serialize_session_metadata_none():
    from teleclaude.core.db import Db

    assert Db._serialize_session_metadata(None) is None


def test_serialize_session_metadata_produces_valid_json():
    from teleclaude.core.db import Db

    meta = SessionMetadata(system_role=ROLE_INTEGRATOR, job=JobRole.INTEGRATOR.value)
    result = Db._serialize_session_metadata(meta)
    assert result is not None
    parsed = json.loads(result)
    assert parsed["system_role"] == ROLE_INTEGRATOR
    assert parsed["job"] == JobRole.INTEGRATOR.value


# ---------------------------------------------------------------------------
# Db._to_core_session — session_metadata deserialization
# ---------------------------------------------------------------------------


def test_to_core_session_no_metadata_yields_none():
    from teleclaude.core.db import Db

    session = Db._to_core_session(_db_row())
    assert session.session_metadata is None


def test_to_core_session_valid_metadata_round_trip():
    from teleclaude.core.db import Db

    raw = json.dumps({"system_role": ROLE_INTEGRATOR, "job": JobRole.INTEGRATOR.value})
    session = Db._to_core_session(_db_row(raw))
    assert session.session_metadata is not None
    assert session.session_metadata.system_role == ROLE_INTEGRATOR
    assert session.session_metadata.job == JobRole.INTEGRATOR.value


def test_to_core_session_unknown_keys_are_ignored():
    """Extra keys in the JSON must not raise — only known keys flow through."""
    from teleclaude.core.db import Db

    raw = json.dumps({"system_role": "worker", "job": "builder", "unexpected_key": "noise"})
    session = Db._to_core_session(_db_row(raw))
    assert session.session_metadata is not None
    assert session.session_metadata.system_role == "worker"
    assert session.session_metadata.job == "builder"


def test_to_core_session_bad_json_yields_none():
    """Malformed JSON must not raise — session_metadata must fall back to None."""
    from teleclaude.core.db import Db

    session = Db._to_core_session(_db_row("not-valid-json{{{"))
    assert session.session_metadata is None


def test_session_metadata_full_round_trip():
    """serialize → deserialize must reproduce the original SessionMetadata."""
    from teleclaude.core.db import Db

    original = SessionMetadata(system_role=ROLE_INTEGRATOR, job=JobRole.INTEGRATOR.value)
    serialized = Db._serialize_session_metadata(original)
    assert serialized is not None
    session = Db._to_core_session(_db_row(serialized))
    assert session.session_metadata == original


# ---------------------------------------------------------------------------
# CommandService.run_slash_command
# ---------------------------------------------------------------------------


async def test_run_slash_command_builds_integrator_metadata():
    """NEXT_INTEGRATE must produce the correct system_role, job, and auto_command."""
    from teleclaude.core.command_service import CommandService

    svc = object.__new__(CommandService)  # bypass heavy __init__
    svc.create_session = AsyncMock(return_value={"session_id": "x"})

    with patch("teleclaude.core.command_mapper.CommandMapper.map_api_input") as mock_map:
        mock_map.return_value = MagicMock()
        await svc.run_slash_command(SlashCommand.NEXT_INTEGRATE, "/my/project")

    positional = mock_map.call_args[0]
    metadata = positional[2]  # MessageMetadata is the third positional arg

    assert metadata.session_metadata is not None
    assert metadata.session_metadata.system_role == ROLE_INTEGRATOR
    assert metadata.session_metadata.job == JobRole.INTEGRATOR.value
    assert "agent_then_message claude slow" in metadata.auto_command
    assert "/next-integrate" in metadata.auto_command


async def test_run_slash_command_detach_forwarded_as_skip_listener():
    """detach=True must set skip_listener_registration=True in the create params."""
    from teleclaude.core.command_service import CommandService

    svc = object.__new__(CommandService)
    svc.create_session = AsyncMock(return_value={"session_id": "x"})

    with patch("teleclaude.core.command_mapper.CommandMapper.map_api_input") as mock_map:
        mock_map.return_value = MagicMock()
        await svc.run_slash_command(SlashCommand.NEXT_INTEGRATE, "/p", detach=True)

    positional = mock_map.call_args[0]
    params = positional[1]
    assert params["skip_listener_registration"] is True


async def test_run_slash_command_unmapped_command_produces_no_metadata():
    """A SlashCommand absent from COMMAND_ROLE_MAP must produce None session_metadata."""
    from teleclaude.core.command_service import CommandService

    svc = object.__new__(CommandService)
    svc.create_session = AsyncMock(return_value={"session_id": "x"})

    fake_cmd = MagicMock()
    fake_cmd.value = "nonexistent-command"

    with patch("teleclaude.core.command_mapper.CommandMapper.map_api_input") as mock_map:
        mock_map.return_value = MagicMock()
        await svc.run_slash_command(fake_cmd, "/p")

    positional = mock_map.call_args[0]
    metadata = positional[2]
    assert metadata.session_metadata is None


# ---------------------------------------------------------------------------
# spawn_integrator_session
# ---------------------------------------------------------------------------


async def test_spawn_integrator_session_guard_returns_none_when_active():
    """Guard branch: if an integrator session is already running, return None."""
    running = MagicMock()
    running.session_metadata = SessionMetadata(system_role=ROLE_INTEGRATOR, job=JobRole.INTEGRATOR.value)
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[running])
    mock_svc = MagicMock()

    with (
        patch("teleclaude.core.db.db", mock_db),
        patch("teleclaude.core.command_registry.get_command_service", return_value=mock_svc),
    ):
        from teleclaude.core.integration_bridge import spawn_integrator_session

        result = await spawn_integrator_session("my-slug", "my-branch", "abc123")

    assert result is None
    mock_svc.run_slash_command.assert_not_called()


async def test_spawn_integrator_session_spawns_when_none_running():
    """Spawn branch: when no integrator is active, run_slash_command is called."""
    non_integrator = MagicMock()
    non_integrator.session_metadata = SessionMetadata(system_role="worker", job="builder")
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[non_integrator])
    mock_svc = MagicMock()
    mock_svc.run_slash_command = AsyncMock(return_value={"session_id": "new"})

    with (
        patch("teleclaude.core.db.db", mock_db),
        patch("teleclaude.core.command_registry.get_command_service", return_value=mock_svc),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        from teleclaude.core.integration_bridge import spawn_integrator_session

        result = await spawn_integrator_session("my-slug", "my-branch", "abc123")

    assert result is not None
    assert result["status"] == "spawned"
    assert result["slug"] == "my-slug"
    mock_svc.run_slash_command.assert_called_once()


async def test_spawn_integrator_session_db_error_falls_through_to_spawn():
    """If db.list_sessions raises, proceed to spawn (optimistic fallback)."""
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(side_effect=RuntimeError("DB unavailable"))
    mock_svc = MagicMock()
    mock_svc.run_slash_command = AsyncMock(return_value={"session_id": "new"})

    with (
        patch("teleclaude.core.db.db", mock_db),
        patch("teleclaude.core.command_registry.get_command_service", return_value=mock_svc),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        from teleclaude.core.integration_bridge import spawn_integrator_session

        result = await spawn_integrator_session("my-slug", "my-branch", "abc123")

    assert result is not None
    assert result["status"] == "spawned"
