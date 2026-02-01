#!/usr/bin/env python3
"""E2E tests for command execution with mocked commands (short-lived and long-running)."""

import asyncio

import pytest

from teleclaude.constants import MAIN_MODULE
from teleclaude.core import tmux_bridge
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CreateSessionCommand, SendMessageCommand


@pytest.mark.asyncio
@pytest.mark.timeout(12)
async def test_short_lived_command(daemon_with_mocked_telegram):
    """Test short-lived command execution flow.

    Verifies:
    1. Command executes quickly (mocked with echo)
    2. Output is captured and sent to Telegram
    3. Command completes immediately
    """
    daemon = daemon_with_mocked_telegram

    # Default mode is "short" - no need to set it
    assert daemon.mock_command_mode == "short"

    # Create a test session
    project_path = "/tmp"
    create_cmd = CreateSessionCommand(project_path=project_path, origin=InputOrigin.TELEGRAM.value, title="Short Test")
    await daemon.command_service.create_session(create_cmd)

    sessions = await daemon.db.list_sessions(include_initializing=True)
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mocks to track only this test's calls
    telegram = daemon.client.adapters["telegram"]
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()
    telegram.send_output_update.reset_mock()

    # Send any command - it will be mocked with short echo
    await daemon.command_service.send_message(
        SendMessageCommand(session_id=session.session_id, text="any command here", origin=InputOrigin.TELEGRAM.value)
    )

    # Wait for command to execute and polling to send output
    # Poll loop: 1s initial delay + 3s base update interval
    await asyncio.sleep(4.5)

    # Verify command was executed in tmux
    output = await tmux_bridge.capture_pane(session.tmux_session_name)
    assert output is not None, "Should have tmux output"
    assert "Command executed" in output, f"Should see mocked command output, got: {output[:300]}"

    # Verify output was sent to Telegram via send_output_update (used by polling coordinator)
    assert telegram.send_output_update.call_count >= 1, (
        f"Should have sent output to Telegram via send_output_update. "
        f"send_output_update calls: {telegram.send_output_update.call_count}"
    )


@pytest.mark.asyncio
@pytest.mark.timeout(12)
async def test_long_running_command(daemon_with_mocked_telegram):
    """Test long-running interactive command flow.

    Verifies:
    1. Long-running process starts and waits for input
    2. Initial output is captured
    3. Bidirectional communication works (send input, get response)
    4. Output polling captures all interactions
    """
    daemon = daemon_with_mocked_telegram

    # Set mode to long-running for this test
    daemon.mock_command_mode = "long"

    # Create a test session
    project_path = "/tmp"
    create_cmd = CreateSessionCommand(project_path=project_path, origin=InputOrigin.TELEGRAM.value, title="Long Test")
    await daemon.command_service.create_session(create_cmd)

    sessions = await daemon.db.list_sessions(include_initializing=True)
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mocks to track only this test's calls
    telegram = daemon.client.adapters["telegram"]
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()
    telegram.send_output_update.reset_mock()

    # Send any command - it will be mocked with long-running Python process
    await daemon.command_service.send_message(
        SendMessageCommand(session_id=session.session_id, text="any command", origin=InputOrigin.TELEGRAM.value)
    )

    # Wait for process to start and produce initial output
    # Allow extra slack under parallel test load.
    output = ""
    for _ in range(90):
        output = await tmux_bridge.capture_pane(session.tmux_session_name) or ""
        if "Ready" in output:
            break
        await asyncio.sleep(0.1)

    # Verify initial output
    assert output, "Should have tmux output"
    assert "Ready" in output, f"Should see initial output, got: {output[:500]}"

    # For the second send (sending input to running process), temporarily disable mock
    daemon.mock_command_mode = "passthrough"

    try:
        # Send input to the interactive process
        await tmux_bridge.send_keys(session.tmux_session_name, "test message")

        # Wait for response and polling to send output to Telegram
        # Poll loop: 1s initial delay + 3s base update interval
        await asyncio.sleep(4.5)

        # Verify terminal has both initial output and response
        output = await tmux_bridge.capture_pane(session.tmux_session_name)
        assert "Echo: test message" in output, f"Should see response to input, got: {output[:500]}"

        # Verify output was sent to Telegram via send_output_update (used by polling coordinator)
        assert telegram.send_output_update.call_count >= 1, (
            f"Should have sent output to Telegram via send_output_update. "
            f"send_output_update calls: {telegram.send_output_update.call_count}"
        )
    finally:
        # CRITICAL: Reset mock mode to prevent subsequent tests from running real commands
        daemon.mock_command_mode = "short"


if __name__ == MAIN_MODULE:
    pytest.main([__file__, "-v"])
