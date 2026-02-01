"""Integration test for polling lifecycle with in-memory guard."""

import asyncio
import uuid

import pytest

from teleclaude.core import polling_coordinator
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import ProcessExited


@pytest.mark.asyncio
async def test_polling_registry_clears_after_exit(daemon_with_mocked_telegram):
    """Polling registry should clear after poller completes."""
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    # Create test session
    session_id = str(uuid.uuid4())
    tmux_session_name = f"test-{session_id[:8]}"

    await test_db.create_session(
        session_id=session_id,
        tmux_session_name=tmux_session_name,
        last_input_origin=InputOrigin.API.value,
        title="Test Session",
        computer_name="test-computer",
        adapter_metadata={},
    )

    # Mock poller that exits immediately
    completed = asyncio.Event()

    async def mock_poll(*_args, **_kwargs):
        yield ProcessExited(
            session_id=session_id,
            final_output="done",
            exit_code=0,
            started_at=1000.0,
        )
        completed.set()

    output_poller = type("Poller", (), {"poll": mock_poll})()

    # Schedule polling
    scheduled = await polling_coordinator.schedule_polling(
        session_id=session_id,
        tmux_session_name=tmux_session_name,
        output_poller=output_poller,
        adapter_client=daemon.client,
        get_output_file=daemon._get_output_file_path,
    )
    assert scheduled is True
    assert await polling_coordinator.is_polling(session_id) is True

    await completed.wait()
    # Allow unregister to run
    await asyncio.sleep(0.01)
    assert await polling_coordinator.is_polling(session_id) is False


@pytest.mark.asyncio
async def test_polling_guard_prevents_duplicate_polling(daemon_with_mocked_telegram):
    """Test that polling guard prevents duplicate polling instances."""
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    session_id = str(uuid.uuid4())
    await test_db.create_session(
        session_id=session_id,
        tmux_session_name=f"test-{session_id[:8]}",
        last_input_origin=InputOrigin.API.value,
        title="Test Session",
        computer_name="test-computer",
        adapter_metadata={},
    )

    block = asyncio.Event()

    async def mock_poll(*_args, **_kwargs):
        await block.wait()
        if False:  # pragma: no cover - generator shape
            yield

    output_poller = type("Poller", (), {"poll": mock_poll})()

    scheduled = await polling_coordinator.schedule_polling(
        session_id=session_id,
        tmux_session_name=f"test-{session_id[:8]}",
        output_poller=output_poller,
        adapter_client=daemon.client,
        get_output_file=daemon._get_output_file_path,
    )
    assert scheduled is True

    scheduled_again = await polling_coordinator.schedule_polling(
        session_id=session_id,
        tmux_session_name=f"test-{session_id[:8]}",
        output_poller=output_poller,
        adapter_client=daemon.client,
        get_output_file=daemon._get_output_file_path,
    )
    assert scheduled_again is False

    block.set()
    await asyncio.sleep(0.01)
