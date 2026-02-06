#!/usr/bin/env python3
"""E2E tests for command execution with mocked commands (short-lived and long-running)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.constants import MAIN_MODULE
from teleclaude.core import tmux_bridge
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand


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
    await daemon.command_service.process_message(
        ProcessMessageCommand(session_id=session.session_id, text="any command here", origin=InputOrigin.TELEGRAM.value)
    )

    # Wait for output to be captured and broadcast to the UI adapter
    output_sent = False
    for _ in range(90):
        for call in telegram.send_output_update.call_args_list:
            if len(call.args) > 1 and "Command executed" in call.args[1]:
                output_sent = True
                break
        if output_sent:
            break
        await asyncio.sleep(0.1)

    # Verify command was executed in tmux
    output = await tmux_bridge.capture_pane(session.tmux_session_name)
    assert output is not None, "Should have tmux output"
    assert "Command executed" in output, f"Should see mocked command output, got: {output[:300]}"

    assert output_sent, "Expected send_output_update to include command output"


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
    await daemon.command_service.process_message(
        ProcessMessageCommand(session_id=session.session_id, text="any command", origin=InputOrigin.TELEGRAM.value)
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

        # Wait for response to be captured and broadcast to the UI adapter
        output_sent = False
        for _ in range(90):
            for call in telegram.send_output_update.call_args_list:
                if len(call.args) > 1 and "Echo: test message" in call.args[1]:
                    output_sent = True
                    break
            if output_sent:
                break
            await asyncio.sleep(0.1)

        # Verify terminal has both initial output and response
        output = await tmux_bridge.capture_pane(session.tmux_session_name)
        assert "Echo: test message" in output, f"Should see response to input, got: {output[:500]}"

        assert output_sent, "Expected send_output_update to include echo response"
    finally:
        # CRITICAL: Reset mock mode to prevent subsequent tests from running real commands
        daemon.mock_command_mode = "short"


@pytest.mark.asyncio
@pytest.mark.timeout(12)
async def test_command_failure_reports_error(daemon_with_mocked_telegram):
    """Failed tmux send should notify user with error message."""
    daemon = daemon_with_mocked_telegram

    create_cmd = CreateSessionCommand(
        project_path="/tmp",
        origin=InputOrigin.TELEGRAM.value,
        title="Failure Test",
    )
    await daemon.command_service.create_session(create_cmd)
    session = (await daemon.db.list_sessions(include_initializing=True))[0]

    # Capture error message sent to user
    recorded: list[str] = []

    async def record_send(session_obj, text: str, **_kwargs: object) -> str:
        recorded.append(text)
        return "msg-err"

    daemon.client.send_message = record_send  # type: ignore[assignment]

    with patch("teleclaude.core.command_handlers.tmux_io.process_text", new=AsyncMock(return_value=False)):
        await daemon.command_service.process_message(
            ProcessMessageCommand(
                session_id=session.session_id,
                text="fail me",
                origin=InputOrigin.TELEGRAM.value,
            )
        )

    assert any("Failed to send command to tmux" in msg for msg in recorded)


if __name__ == MAIN_MODULE:
    pytest.main([__file__, "-v"])
