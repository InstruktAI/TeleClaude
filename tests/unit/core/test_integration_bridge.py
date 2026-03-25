"""Unit tests for integration_bridge.spawn_integrator_session,
CommandService.run_slash_command, and Db session column round-trips.

Covers the code paths introduced in the fix-integrator-spawn-broken-integration-brid fix:
- spawn_integrator_session guard (already running) and spawn branches
- CommandService.run_slash_command system_role/job and auto_command construction
- Db._to_core_session system_role/job column read
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from teleclaude.constants import ROLE_INTEGRATOR, JobRole, SlashCommand

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_row(system_role: str | None = None, job: str | None = None) -> MagicMock:
    """Minimal db_models.Session stub for _to_core_session tests."""
    row = MagicMock()
    row.session_id = "test-session-1"
    row.computer_name = "local"
    row.tmux_session_name = None
    row.title = ""
    row.last_input_origin = None
    row.origin_metadata = None
    row.system_role = system_role
    row.job = job
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
# Db._to_core_session — system_role/job column deserialization
# ---------------------------------------------------------------------------


def test_to_core_session_no_role_yields_none():
    from teleclaude.core.db import Db

    session = Db._to_core_session(_db_row())
    assert session.system_role is None
    assert session.job is None


def test_to_core_session_reads_role_columns():
    from teleclaude.core.db import Db

    session = Db._to_core_session(_db_row(system_role=ROLE_INTEGRATOR, job=JobRole.INTEGRATOR.value))
    assert session.system_role == ROLE_INTEGRATOR
    assert session.job == JobRole.INTEGRATOR.value


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

    assert metadata.system_role == ROLE_INTEGRATOR
    assert metadata.job == JobRole.INTEGRATOR.value
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
    """A SlashCommand absent from COMMAND_ROLE_MAP must produce None system_role/job."""
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
    assert metadata.system_role is None
    assert metadata.job is None


# ---------------------------------------------------------------------------
# spawn_integrator_session
# ---------------------------------------------------------------------------


async def test_spawn_integrator_session_notifies_running_session():
    """Guard branch: if an integrator session is already running, send it a ProcessMessageCommand."""
    running = MagicMock()
    running.session_id = "dead-beef-1234"
    running.job = JobRole.INTEGRATOR
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[running])
    mock_svc = MagicMock()
    mock_svc.process_message = AsyncMock()

    with (
        patch("teleclaude.core.db.db", mock_db),
        patch("teleclaude.core.command_registry.get_command_service", return_value=mock_svc),
    ):
        from teleclaude.core.integration_bridge import spawn_integrator_session

        result = await spawn_integrator_session("my-slug", "my-branch", "abc123def456")

    assert result is None
    mock_svc.run_slash_command.assert_not_called()
    mock_svc.process_message.assert_awaited_once()
    cmd = mock_svc.process_message.call_args[0][0]
    assert cmd.session_id == "dead-beef-1234"


async def test_spawn_integrator_session_notify_failure_returns_none():
    """If process_message raises, return None — exception is swallowed, candidate stays queued."""
    running = MagicMock()
    running.session_id = "dead-beef-1234"
    running.job = JobRole.INTEGRATOR
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[running])
    mock_svc = MagicMock()
    mock_svc.process_message = AsyncMock(side_effect=RuntimeError("session gone"))

    with (
        patch("teleclaude.core.db.db", mock_db),
        patch("teleclaude.core.command_registry.get_command_service", return_value=mock_svc),
    ):
        from teleclaude.core.integration_bridge import spawn_integrator_session

        result = await spawn_integrator_session("my-slug", "my-branch", "abc123")

    assert result is None


async def test_spawn_integrator_session_spawns_when_none_running():
    """Spawn branch: when no integrator is active, run_slash_command is called."""
    non_integrator = MagicMock()
    non_integrator.job = "builder"
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
    assert result.get("status") == "spawned"
    assert result.get("slug") == "my-slug"
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
    assert result.get("status") == "spawned"
