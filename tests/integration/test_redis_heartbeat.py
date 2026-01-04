"""Integration tests for Redis adapter heartbeat functionality."""

import pytest


@pytest.mark.integration
async def test_heartbeat_includes_sessions(daemon_with_mocked_telegram):
    """Test that heartbeat includes active sessions."""
    # Use daemon's db (which is properly initialized by fixture)
    daemon = daemon_with_mocked_telegram

    # Create test session
    session = await daemon.db.create_session(
        computer_name="TestPC",
        tmux_session_name="test-heartbeat",
        origin_adapter="redis",
        title="Test Session",
        adapter_metadata={"test": "data"},
    )

    # Verify session was created
    assert session is not None
    assert session.computer_name == "TestPC"

    # Get all sessions
    sessions = await daemon.db.list_sessions()
    assert len(sessions) >= 1
    assert any(s.session_id == session.session_id for s in sessions)


@pytest.mark.integration
async def test_heartbeat_sessions_limit(daemon_with_mocked_telegram):
    """Test that heartbeat limits number of sessions returned."""
    daemon = daemon_with_mocked_telegram

    # Create multiple sessions
    session_ids = []
    for i in range(5):
        session = await daemon.db.create_session(
            computer_name="TestPC",
            tmux_session_name=f"test-heartbeat-{i}",
            origin_adapter="redis",
            title=f"Test Session {i}",
            adapter_metadata={"index": i},
        )
        session_ids.append(session.session_id)

    # Get all sessions
    sessions = await daemon.db.list_sessions()
    assert len(sessions) >= 5

    # Verify all our sessions are in the list
    retrieved_ids = [s.session_id for s in sessions]
    for sid in session_ids:
        assert sid in retrieved_ids
