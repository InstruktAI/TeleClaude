#!/usr/bin/env python3
"""Test core TeleClaude components: SessionManager and TerminalBridge."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude import config as config_module
from teleclaude.core import terminal_bridge
from teleclaude.core.session_manager import SessionManager


@pytest.mark.asyncio
async def test_session_manager_crud():
    """Test SessionManager CRUD operations."""
    db_path = "/tmp/teleclaude_test_core.db"

    # Clean up old test database
    Path(db_path).unlink(missing_ok=True)

    session_mgr = SessionManager(db_path)

    try:
        # Initialize
        await session_mgr.initialize()

        # Create session
        session = await session_mgr.create_session(
            computer_name="TestMac",
            tmux_session_name="test-session-crud",
            adapter_type="telegram",
            title="Test Session",
            terminal_size="80x24",
            working_directory="~"
        )

        assert session.session_id is not None
        assert session.title == "Test Session"
        assert session.closed is False

        # Get session
        retrieved = await session_mgr.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id
        assert retrieved.title == session.title

        # List sessions
        sessions = await session_mgr.list_sessions()
        assert len(sessions) >= 1
        assert any(s.session_id == session.session_id for s in sessions)

        # Update session
        await session_mgr.update_session(session.session_id, title="Updated Title")
        updated = await session_mgr.get_session(session.session_id)
        assert updated.title == "Updated Title"

        # Update activity and count
        await session_mgr.update_last_activity(session.session_id)
        count = await session_mgr.increment_command_count(session.session_id)
        assert count == 1

        # Delete session
        await session_mgr.delete_session(session.session_id)
        deleted = await session_mgr.get_session(session.session_id)
        assert deleted is None

    finally:
        await session_mgr.close()


@pytest.mark.asyncio
async def test_terminal_bridge_tmux_operations():
    """Test TerminalBridge tmux operations."""
    session_name = "test-terminal-bridge"

    # Initialize config (required for terminal_bridge functions)
    # Reset config first, then initialize via TeleClaudeDaemon
    base_dir = Path(__file__).parent
    config_module._config = None
    from teleclaude.daemon import TeleClaudeDaemon
    daemon = TeleClaudeDaemon(
        str(base_dir / "config.yml"),
        str(base_dir / ".env")
    )

    try:
        # Create tmux session
        success = await terminal_bridge.create_tmux_session(
            name=session_name,
            shell="/bin/sh",
            working_dir="/tmp",
            cols=80,
            rows=24
        )
        assert success, "Should create tmux session"

        # Check if exists
        exists = await terminal_bridge.session_exists(session_name)
        assert exists, "Session should exist"

        # Send command
        await terminal_bridge.send_keys(session_name, "echo 'Hello TeleClaude'")
        await asyncio.sleep(0.2)

        # Capture output
        output = await terminal_bridge.capture_pane(session_name)
        assert output is not None
        assert "Hello TeleClaude" in output or "echo" in output

    finally:
        # Cleanup: kill session
        await terminal_bridge.kill_session(session_name)
        exists_after = await terminal_bridge.session_exists(session_name)
        assert not exists_after, "Session should be killed"


@pytest.mark.asyncio
async def test_session_manager_with_metadata():
    """Test SessionManager adapter metadata queries."""
    db_path = "/tmp/teleclaude_test_metadata.db"
    session_mgr = SessionManager(db_path)

    try:
        await session_mgr.initialize()

        # Create session with metadata
        session = await session_mgr.create_session(
            computer_name="TestMac",
            tmux_session_name="test-metadata",
            adapter_type="telegram",
            adapter_metadata={"topic_id": 123, "user_id": 456},
            title="Metadata Test"
        )

        # Query by metadata
        results = await session_mgr.get_sessions_by_adapter_metadata(
            "telegram", "topic_id", 123
        )
        assert len(results) == 1
        assert results[0].session_id == session.session_id

        # Cleanup
        await session_mgr.delete_session(session.session_id)

    finally:
        await session_mgr.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
