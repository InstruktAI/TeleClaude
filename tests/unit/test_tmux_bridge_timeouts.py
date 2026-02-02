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
    killed = {"value": False}

    def record_kill() -> None:
        killed["value"] = True

    mock_process.kill = record_kill

    # Should not raise
    await wait_with_timeout(mock_process, SUBPROCESS_TIMEOUT_QUICK, "test operation")

    assert killed["value"] is False


@pytest.mark.asyncio
async def test_wait_with_timeout_kills_on_timeout():
    """Test wait_with_timeout kills process when timeout is exceeded."""
    mock_process = MagicMock()
    mock_process.pid = 12345

    # Simulate hanging process
    async def hang():
        await asyncio.Future()

    mock_process.wait = AsyncMock(side_effect=hang)
    killed = {"value": False}

    def record_kill() -> None:
        killed["value"] = True

    mock_process.kill = record_kill

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
    assert killed["value"] is True
    assert wait_calls == 2  # Once for timeout, once for cleanup


@pytest.mark.asyncio
async def test_wait_with_timeout_handles_process_already_dead():
    """Test wait_with_timeout handles ProcessLookupError gracefully."""
    mock_process = MagicMock()
    mock_process.pid = 12345

    # Simulate hanging process
    async def hang():
        await asyncio.Future()

    mock_process.wait = AsyncMock(side_effect=hang)

    # kill() raises ProcessLookupError if process already terminated
    kill_attempted = {"value": False}

    def raise_lookup() -> None:
        kill_attempted["value"] = True
        raise ProcessLookupError("No such process")

    mock_process.kill = raise_lookup

    with pytest.raises(SubprocessTimeoutError):
        await wait_with_timeout(mock_process, 0.1, "test operation")

    # Should not propagate ProcessLookupError
    assert kill_attempted["value"] is True


@pytest.mark.asyncio
async def test_communicate_with_timeout_completes_normally():
    """Test communicate_with_timeout when process completes within timeout."""
    mock_process = MagicMock()
    mock_process.pid = 12345
    mock_process.communicate = AsyncMock(return_value=(b"stdout", b"stderr"))
    killed = {"value": False}

    def record_kill() -> None:
        killed["value"] = True

    mock_process.kill = record_kill

    stdout, stderr = await communicate_with_timeout(mock_process, None, SUBPROCESS_TIMEOUT_QUICK, "test operation")

    assert stdout == b"stdout"
    assert stderr == b"stderr"
    assert mock_process.communicate.called
    assert killed["value"] is False


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
    assert mock_process.communicate.call_args == ((input_data,), {})


@pytest.mark.asyncio
async def test_communicate_with_timeout_kills_on_timeout():
    """Test communicate_with_timeout kills process when timeout is exceeded."""
    mock_process = MagicMock()
    mock_process.pid = 12345

    # Simulate hanging process
    async def hang(input_data=None):
        await asyncio.Future()
        return (b"", b"")

    mock_process.communicate = AsyncMock(side_effect=hang)
    killed = {"value": False}

    def record_kill() -> None:
        killed["value"] = True

    mock_process.kill = record_kill

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
    assert killed["value"] is True
    assert wait_called  # Cleanup wait was called


@pytest.mark.asyncio
async def test_timeout_constants_are_sensible():
    """Test that timeout constants are within expected ranges."""
    assert SUBPROCESS_TIMEOUT_QUICK > 0
    assert SUBPROCESS_TIMEOUT_DEFAULT > SUBPROCESS_TIMEOUT_QUICK
    assert SUBPROCESS_TIMEOUT_QUICK <= 10  # Quick operations should be fast
    assert SUBPROCESS_TIMEOUT_DEFAULT <= 60  # Default should be reasonable
