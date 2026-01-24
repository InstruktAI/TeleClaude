"""Unit tests for subprocess timeout helpers in tmux_bridge."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.tmux_bridge import (
    SUBPROCESS_TIMEOUT_DEFAULT,
    SUBPROCESS_TIMEOUT_QUICK,
    SubprocessTimeoutError,
    communicate_with_timeout,
    wait_with_timeout,
)


@pytest.mark.asyncio
async def test_wait_with_timeout_completes_normally():
    """Test wait_with_timeout when process completes within timeout."""
    mock_process = MagicMock()
    mock_process.pid = 12345
    mock_process.wait = AsyncMock(return_value=None)

    # Should not raise
    await wait_with_timeout(mock_process, SUBPROCESS_TIMEOUT_QUICK, "test operation")

    mock_process.wait.assert_called_once()
    mock_process.kill.assert_not_called()


@pytest.mark.asyncio
async def test_wait_with_timeout_kills_on_timeout():
    """Test wait_with_timeout kills process when timeout is exceeded."""
    mock_process = MagicMock()
    mock_process.pid = 12345

    # Simulate hanging process
    async def hang():
        await asyncio.sleep(10)

    mock_process.wait = AsyncMock(side_effect=hang)
    mock_process.kill = MagicMock()

    # After kill, wait should succeed
    wait_calls = 0

    async def wait_impl():
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            await hang()  # First call hangs
        # Second call (after kill) succeeds immediately

    mock_process.wait = AsyncMock(side_effect=wait_impl)

    with pytest.raises(SubprocessTimeoutError) as exc_info:
        await wait_with_timeout(mock_process, 0.1, "test operation")

    # Verify structured attributes
    assert exc_info.value.operation == "test operation"
    assert exc_info.value.timeout == 0.1
    assert exc_info.value.pid == 12345

    # Verify error message
    assert "test operation timed out after 0.1s" in str(exc_info.value)
    mock_process.kill.assert_called_once()
    assert wait_calls == 2  # Once for timeout, once for cleanup


@pytest.mark.asyncio
async def test_wait_with_timeout_handles_process_already_dead():
    """Test wait_with_timeout handles ProcessLookupError gracefully."""
    mock_process = MagicMock()
    mock_process.pid = 12345

    # Simulate hanging process
    async def hang():
        await asyncio.sleep(10)

    mock_process.wait = AsyncMock(side_effect=hang)

    # kill() raises ProcessLookupError if process already terminated
    mock_process.kill = MagicMock(side_effect=ProcessLookupError("No such process"))

    with pytest.raises(SubprocessTimeoutError):
        await wait_with_timeout(mock_process, 0.1, "test operation")

    # Should not propagate ProcessLookupError
    mock_process.kill.assert_called_once()


@pytest.mark.asyncio
async def test_communicate_with_timeout_completes_normally():
    """Test communicate_with_timeout when process completes within timeout."""
    mock_process = MagicMock()
    mock_process.pid = 12345
    mock_process.communicate = AsyncMock(return_value=(b"stdout", b"stderr"))

    stdout, stderr = await communicate_with_timeout(mock_process, None, SUBPROCESS_TIMEOUT_QUICK, "test operation")

    assert stdout == b"stdout"
    assert stderr == b"stderr"
    mock_process.communicate.assert_called_once_with(None)
    mock_process.kill.assert_not_called()


@pytest.mark.asyncio
async def test_communicate_with_timeout_with_input():
    """Test communicate_with_timeout passes input data correctly."""
    mock_process = MagicMock()
    mock_process.pid = 12345
    mock_process.communicate = AsyncMock(return_value=(b"output", b""))

    input_data = b"test input"
    stdout, stderr = await communicate_with_timeout(
        mock_process, input_data, SUBPROCESS_TIMEOUT_QUICK, "test operation"
    )

    assert stdout == b"output"
    assert stderr == b""
    mock_process.communicate.assert_called_once_with(input_data)


@pytest.mark.asyncio
async def test_communicate_with_timeout_kills_on_timeout():
    """Test communicate_with_timeout kills process when timeout is exceeded."""
    mock_process = MagicMock()
    mock_process.pid = 12345

    # Simulate hanging process
    async def hang(input_data=None):
        await asyncio.sleep(10)
        return (b"", b"")

    mock_process.communicate = AsyncMock(side_effect=hang)
    mock_process.kill = MagicMock()

    # After kill, wait should succeed
    wait_called = False

    async def wait_impl():
        nonlocal wait_called
        wait_called = True

    mock_process.wait = AsyncMock(side_effect=wait_impl)

    with pytest.raises(SubprocessTimeoutError) as exc_info:
        await communicate_with_timeout(mock_process, None, 0.1, "test operation")

    # Verify structured attributes
    assert exc_info.value.operation == "test operation"
    assert exc_info.value.timeout == 0.1
    assert exc_info.value.pid == 12345

    # Verify error message
    assert "test operation timed out after 0.1s" in str(exc_info.value)
    mock_process.kill.assert_called_once()
    assert wait_called  # Cleanup wait was called


@pytest.mark.asyncio
async def test_timeout_constants_are_sensible():
    """Test that timeout constants are within expected ranges."""
    assert SUBPROCESS_TIMEOUT_QUICK > 0
    assert SUBPROCESS_TIMEOUT_DEFAULT > SUBPROCESS_TIMEOUT_QUICK
    assert SUBPROCESS_TIMEOUT_QUICK <= 10  # Quick operations should be fast
    assert SUBPROCESS_TIMEOUT_DEFAULT <= 60  # Default should be reasonable
