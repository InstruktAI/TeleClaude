"""Unit tests for integration_bridge.spawn_integrator_session and Db session column round-trips.

Covers spawn_integrator_session guard (already running) and spawn branches,
plus Db._to_core_session system_role/job column reads.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.constants import ROLE_INTEGRATOR, JobRole
from teleclaude.core.db import Db
from teleclaude.core.integration_bridge import spawn_integrator_session
from teleclaude.core.models import SessionLaunchKind

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
    session = Db._to_core_session(_db_row())
    assert session.system_role is None
    assert session.job is None


def test_to_core_session_reads_role_columns():
    session = Db._to_core_session(_db_row(system_role=ROLE_INTEGRATOR, job=JobRole.INTEGRATOR.value))
    assert session.system_role == ROLE_INTEGRATOR
    assert session.job == JobRole.INTEGRATOR.value


# ---------------------------------------------------------------------------
# spawn_integrator_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_rejects_missing_caller_identity():
    """Missing caller_session_id raises ValueError when no integrator is running."""
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[])

    with patch("teleclaude.core.integration_bridge.db", mock_db):
        with pytest.raises(ValueError, match="missing caller session identity"):
            await spawn_integrator_session("my-slug", "my-branch", "abc123", "")


@pytest.mark.asyncio
async def test_spawn_rejects_unknown_caller_identity():
    """Sentinel caller IDs must not be persisted as real session lineage."""
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[])

    with patch("teleclaude.core.integration_bridge.db", mock_db):
        with pytest.raises(ValueError, match="missing caller session identity"):
            await spawn_integrator_session("my-slug", "my-branch", "abc123", "unknown")


@pytest.mark.asyncio
async def test_spawn_skips_running_integrator():
    """If an integrator session is already running, leave it undisturbed."""
    running = MagicMock()
    running.session_id = "dead-beef-1234"
    running.job = JobRole.INTEGRATOR
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[running])
    mock_svc = MagicMock()
    mock_svc.process_message = AsyncMock()
    mock_svc.create_session = AsyncMock()

    with (
        patch("teleclaude.core.integration_bridge.db", mock_db),
        patch("teleclaude.core.integration_bridge.get_command_service", return_value=mock_svc),
    ):
        result = await spawn_integrator_session("my-slug", "my-branch", "abc123def456", "caller-sess")

    assert result is None
    mock_svc.process_message.assert_not_awaited()
    mock_svc.create_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_spawn_skips_running_integrator_without_caller_identity():
    """An active integrator suppresses both spawning and caller identity validation."""
    running = MagicMock()
    running.session_id = "dead-beef-1234"
    running.job = JobRole.INTEGRATOR
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[running])
    mock_svc = MagicMock()
    mock_svc.process_message = AsyncMock()

    with (
        patch("teleclaude.core.integration_bridge.db", mock_db),
        patch("teleclaude.core.integration_bridge.get_command_service", return_value=mock_svc),
    ):
        result = await spawn_integrator_session("my-slug", "my-branch", "abc123def456", "")

    assert result is None
    mock_svc.process_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_spawn_skips_running_integrator_without_command_service():
    """Skipping an active integrator does not need the command service."""
    running = MagicMock()
    running.session_id = "dead-beef-1234"
    running.job = JobRole.INTEGRATOR
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[running])

    with (
        patch("teleclaude.core.integration_bridge.db", mock_db),
        patch("teleclaude.core.integration_bridge.get_command_service", side_effect=AssertionError),
    ):
        result = await spawn_integrator_session("my-slug", "my-branch", "abc123", "caller-sess")

    assert result is None


@pytest.mark.asyncio
async def test_spawn_creates_session_with_identity():
    """When no integrator is active, create session via command service with caller identity."""
    non_integrator = MagicMock()
    non_integrator.job = "builder"
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[non_integrator])
    mock_svc = MagicMock()
    mock_svc.create_session = AsyncMock(
        return_value={"session_id": "new-int", "tmux_session_name": "tmux-int"},
    )

    with (
        patch("teleclaude.core.integration_bridge.db", mock_db),
        patch("teleclaude.core.integration_bridge.get_command_service", return_value=mock_svc),
        patch("teleclaude.core.agents.get_default_agent", return_value="claude"),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        result = await spawn_integrator_session("my-slug", "my-branch", "abc123", "orchestrator-sess-1")

    assert result is not None
    assert result.get("status") == "spawned"
    assert result.get("slug") == "my-slug"

    mock_svc.create_session.assert_awaited_once()
    cmd = mock_svc.create_session.call_args[0][0]
    assert cmd.system_role == ROLE_INTEGRATOR
    assert cmd.job == JobRole.INTEGRATOR.value
    assert cmd.initiator_session_id == "orchestrator-sess-1"
    assert cmd.skip_listener_registration is True
    assert cmd.project_path == "/project"
    assert cmd.launch_intent is not None
    assert cmd.launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
    assert cmd.launch_intent.message == "/next-integrate"


@pytest.mark.asyncio
async def test_spawn_failure_raises():
    """Spawn failure propagates — no silent error swallowing."""
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[])
    mock_svc = MagicMock()
    mock_svc.create_session = AsyncMock(side_effect=RuntimeError("tmux creation failed"))

    with (
        patch("teleclaude.core.integration_bridge.db", mock_db),
        patch("teleclaude.core.integration_bridge.get_command_service", return_value=mock_svc),
        patch("teleclaude.core.agents.get_default_agent", return_value="claude"),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        with pytest.raises(RuntimeError, match="tmux creation failed"):
            await spawn_integrator_session("my-slug", "my-branch", "abc123", "caller-sess")


@pytest.mark.asyncio
async def test_spawn_db_error_raises():
    """If db.list_sessions raises, fail fast instead of risking a duplicate spawn."""
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(side_effect=RuntimeError("DB unavailable"))
    mock_svc = MagicMock()
    mock_svc.create_session = AsyncMock()

    with (
        patch("teleclaude.core.integration_bridge.db", mock_db),
        patch("teleclaude.core.integration_bridge.get_command_service", return_value=mock_svc),
        patch("teleclaude.core.agents.get_default_agent", return_value="claude"),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        with pytest.raises(RuntimeError, match="DB unavailable"):
            await spawn_integrator_session("my-slug", "my-branch", "abc123", "caller-sess")

    mock_svc.create_session.assert_not_awaited()
