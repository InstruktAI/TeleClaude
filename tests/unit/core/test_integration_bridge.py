"""Unit tests for integration_bridge.spawn_integrator_session and Db session column round-trips.

Covers spawn_integrator_session guard (already running) and spawn branches,
plus Db._to_core_session system_role/job column reads.
"""

# pylint: disable=import-outside-toplevel,missing-function-docstring,protected-access

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.constants import ROLE_INTEGRATOR, JobRole

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_spawn_integrator_session_spawns_when_none_running():
    """Spawn branch: when no integrator is active, the edge API is used to run /next-integrate."""
    captured = SimpleNamespace(
        connected=False,
        closed=False,
        command=None,
        project_path=None,
        detach=None,
    )

    async def _connect() -> None:
        captured.connected = True

    async def _close() -> None:
        captured.closed = True

    async def _run_session(**kwargs: object) -> dict[str, str]:
        captured.command = str(kwargs["command"])
        captured.project_path = str(kwargs["project_path"])
        captured.detach = bool(kwargs["detach"])
        return {"session_id": "new", "tmux_session_name": "tmux-new"}

    def _fake_api_client() -> SimpleNamespace:
        return SimpleNamespace(connect=_connect, close=_close, run_session=_run_session)

    non_integrator = MagicMock()
    non_integrator.job = "builder"
    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(return_value=[non_integrator])
    mock_svc = MagicMock()
    mock_svc.run_slash_command = AsyncMock(side_effect=AssertionError("spawn must not call run_slash_command"))

    with (
        patch("teleclaude.core.db.db", mock_db),
        patch("teleclaude.core.command_registry.get_command_service", return_value=mock_svc),
        patch("teleclaude.cli.api_client.TelecAPIClient", _fake_api_client),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        from teleclaude.core.integration_bridge import spawn_integrator_session

        result = await spawn_integrator_session("my-slug", "my-branch", "abc123")

    assert result is not None
    assert result.get("status") == "spawned"
    assert result.get("slug") == "my-slug"
    assert captured.connected is True
    assert captured.closed is True
    assert captured.command == "/next-integrate"
    assert captured.project_path == "/project"
    assert captured.detach is True
    mock_svc.run_slash_command.assert_not_called()


async def test_spawn_integrator_session_db_error_falls_through_to_spawn():
    """If db.list_sessions raises, proceed to spawn (optimistic fallback)."""

    async def _run_session(**_kwargs: object) -> dict[str, str]:
        return {"session_id": "new", "tmux_session_name": "tmux-new"}

    def _fake_api_client() -> SimpleNamespace:
        return SimpleNamespace(connect=AsyncMock(), close=AsyncMock(), run_session=_run_session)

    mock_db = MagicMock()
    mock_db.list_sessions = AsyncMock(side_effect=RuntimeError("DB unavailable"))

    with (
        patch("teleclaude.core.db.db", mock_db),
        patch("teleclaude.cli.api_client.TelecAPIClient", _fake_api_client),
        patch.dict("os.environ", {"TELECLAUDE_PROJECT_PATH": "/project"}),
    ):
        from teleclaude.core.integration_bridge import spawn_integrator_session

        result = await spawn_integrator_session("my-slug", "my-branch", "abc123")

    assert result is not None
    assert result.get("status") == "spawned"
