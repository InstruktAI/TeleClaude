"""Unit tests for simplified OutputPoller."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core.output_poller import IdleDetected, OutputChanged, OutputPoller, ProcessExited


@pytest.mark.unit
class TestOutputPoller:
    """Test OutputPoller core functionality."""

    @pytest.fixture
    def poller(self):
        """Create OutputPoller instance."""
        return OutputPoller()

    def test_extract_exit_code_with_marker(self, poller):
        """Test exit code extraction when marker present."""
        output = "some output\n__EXIT__0__\n"
        exit_code = poller._extract_exit_code(output, has_exit_marker=True)
        assert exit_code == 0

        output = "error output\n__EXIT__1__\n"
        exit_code = poller._extract_exit_code(output, has_exit_marker=True)
        assert exit_code == 1

    def test_extract_exit_code_without_marker(self, poller):
        """Test exit code extraction when no marker."""
        output = "some output\n__EXIT__0__\n"
        exit_code = poller._extract_exit_code(output, has_exit_marker=False)
        assert exit_code is None

    def test_extract_exit_code_no_match(self, poller):
        """Test exit code when no marker in output."""
        output = "some output without marker\n"
        exit_code = poller._extract_exit_code(output, has_exit_marker=True)
        assert exit_code is None

    def test_strip_exit_markers_removes_marker_output(self, poller):
        """Test stripping exit code marker from output."""
        output = "command output\n__EXIT__0__\n"
        result = poller._strip_exit_markers(output)
        assert result == "command output\n"  # Preserves trailing newline

    def test_strip_exit_markers_removes_echo_command(self, poller):
        """Test stripping echo command from shell prompts."""
        output = 'command output; echo "__EXIT__$?__"\nprompt > '
        result = poller._strip_exit_markers(output)
        assert result == "command output\nprompt > "

    def test_strip_exit_markers_handles_both(self, poller):
        """Test stripping both marker and echo command."""
        output = 'some output; echo "__EXIT__$?__"\n__EXIT__0__\nprompt > '
        result = poller._strip_exit_markers(output)
        assert result == "some output\nprompt > "  # Preserves newline after output

    def test_strip_exit_markers_handles_line_wrapped_marker(self, poller):
        """Test stripping marker that wraps across lines (THE BUG FIX)."""
        output = "command output\n__EXIT__0\n__\n"
        result = poller._strip_exit_markers(output)
        # Removes wrapped marker, preserves structure
        assert result == "command output\n"

    def test_strip_exit_markers_handles_line_wrapped_echo_command(self, poller):
        """Test stripping echo command that wraps across lines."""
        output = 'command output; echo "__EXIT__$?\n__"\nprompt > '
        result = poller._strip_exit_markers(output)
        assert result == "command output\nprompt > "

    def test_strip_exit_markers_handles_multiple_wraps(self, poller):
        """Test stripping when both marker and command are wrapped."""
        output = 'some output; echo "__EXIT__\n$?\n__"\n__EXIT__\n0\n__\nprompt > '
        result = poller._strip_exit_markers(output)
        assert result == "some output\nprompt > "  # Preserves newline

    def test_strip_exit_markers_real_world_wrapped_case(self, poller):
        """Test realistic case with wrapped marker (matches original behavior)."""
        output = 'ls -la\nfile1.txt\nfile2.txt\n__EXIT__\n0\n__\n$ '
        result = poller._strip_exit_markers(output)
        # Removes wrapped marker, preserves newline structure
        assert result == 'ls -la\nfile1.txt\nfile2.txt\n$ '

    def test_strip_claude_code_hooks_removes_hook_prefix_lines(self, poller):
        """Test stripping hook success prefix lines."""
        output = "Some output\n⎿ UserPromptSubmit hook succeeded: message\nMore output"
        result = poller._strip_claude_code_hooks(output)
        assert result == "Some output\nMore output"

    def test_strip_claude_code_hooks_removes_single_system_reminder(self, poller):
        """Test stripping single system-reminder block."""
        output = "Before\n<system-reminder>This is a reminder</system-reminder>\nAfter"
        result = poller._strip_claude_code_hooks(output)
        assert result == "Before\nAfter"

    def test_strip_claude_code_hooks_removes_nested_system_reminders(self, poller):
        """Test stripping nested system-reminder blocks (real-world case from Claude Code hooks)."""
        # This is the actual pattern from Claude Code's UserPromptSubmit hook
        output = (
            "Output\n"
            "<system-reminder>\n"
            "⎿ UserPromptSubmit hook succeeded: <system-reminder>Am I required to make any code changes here?</system-reminder>\n"
            "</system-reminder>\n"
            "More output"
        )
        result = poller._strip_claude_code_hooks(output)
        assert result == "Output\nMore output"

    def test_strip_claude_code_hooks_removes_multiline_system_reminder(self, poller):
        """Test stripping multiline system-reminder blocks."""
        output = (
            "Start\n"
            "<system-reminder>\n"
            "Line 1\n"
            "Line 2\n"
            "Line 3\n"
            "</system-reminder>\n"
            "End"
        )
        result = poller._strip_claude_code_hooks(output)
        assert result == "Start\nEnd"

    def test_strip_claude_code_hooks_handles_both_patterns(self, poller):
        """Test stripping both hook lines and system-reminder blocks together."""
        output = (
            "Output here\n"
            "⎿  SessionStart:startup hook succeeded: All good\n"
            "<system-reminder>Reminder text</system-reminder>\n"
            "⎿ UserPromptSubmit hook succeeded: Done\n"
            "Final output"
        )
        result = poller._strip_claude_code_hooks(output)
        assert result == "Output here\nFinal output"

    def test_strip_claude_code_hooks_preserves_clean_output(self, poller):
        """Test that clean output without hooks is unchanged."""
        output = "Normal terminal output\nNo hooks here\nAll clean"
        result = poller._strip_claude_code_hooks(output)
        assert result == output

    def test_strip_exit_markers_includes_claude_hook_filtering(self, poller):
        """Test that _strip_exit_markers also strips Claude Code hooks."""
        output = (
            "command output\n"
            "⎿ UserPromptSubmit hook succeeded: test\n"
            "<system-reminder>Some reminder</system-reminder>\n"
            "__EXIT__0__\n"
        )
        result = poller._strip_exit_markers(output)
        # Should remove both hooks and exit markers
        assert result == "command output\n"


@pytest.mark.asyncio
class TestOutputPollerPoll:
    """Test OutputPoller.poll() async generator."""

    @pytest.fixture
    def poller(self):
        """Create OutputPoller instance."""
        return OutputPoller()

    async def test_session_death_detection(self, poller, tmp_path):
        """Test poll detects session death."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                # Session no longer exists
                mock_terminal.session_exists = AsyncMock(return_value=False)

                # Collect events
                events = []
                async for event in poller.poll("test-123", "test-tmux", output_file, has_exit_marker=False):
                    events.append(event)

                # Verify ProcessExited event with no exit code
                assert len(events) == 1
                assert isinstance(events[0], ProcessExited)
                assert events[0].session_id == "test-123"
                assert events[0].exit_code is None

    async def test_exit_code_detection(self, poller, tmp_path):
        """Test poll detects exit code and stops."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                # Session exists
                mock_terminal.session_exists = AsyncMock(return_value=True)

                # Output changes from command to command+exit marker (triggers exit detection)
                call_count = 0
                async def capture_mock(name):
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        return "command output\n"  # Baseline
                    return "command output\n__EXIT__0__\n"  # Changed output with exit marker

                mock_terminal.capture_pane = capture_mock
                mock_terminal.clear_history = AsyncMock()

                # Collect events
                events = []
                async for event in poller.poll("test-456", "test-tmux", output_file, has_exit_marker=True):
                    events.append(event)

                # Verify we get baseline OutputChanged + ProcessExited
                assert len(events) == 2
                assert isinstance(events[0], OutputChanged)
                assert events[0].session_id == "test-456"
                assert events[0].output == "command output\n"

                assert isinstance(events[1], ProcessExited)
                assert events[1].session_id == "test-456"
                assert events[1].exit_code == 0
                assert events[1].final_output == "command output\n"  # Preserves trailing newline

                # Verify file written
                assert output_file.exists()
                assert output_file.read_text() == "command output\n"  # Preserves trailing newline

    async def test_output_changed_detection(self, poller, tmp_path):
        """Test poll detects output changes."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                call_count = 0

                async def session_exists_mock(name):
                    nonlocal call_count
                    call_count += 1
                    # Exit after 3 iterations
                    return call_count < 3

                mock_terminal.session_exists = session_exists_mock

                # Output changes over time
                outputs = ["output 1\n", "output 2\n", "output 3\n"]
                output_index = 0

                async def capture_mock(name):
                    nonlocal output_index
                    result = outputs[min(output_index, len(outputs) - 1)]
                    output_index += 1
                    return result

                mock_terminal.capture_pane = capture_mock

                # Collect events
                events = []
                async for event in poller.poll("test-789", "test-tmux", output_file, has_exit_marker=False):
                    events.append(event)

                # Verify OutputChanged events for each change
                assert len(events) >= 2  # At least 2 changes before session death
                for event in events[:-1]:
                    assert isinstance(event, OutputChanged)
                # Last event is ProcessExited
                assert isinstance(events[-1], ProcessExited)

    async def test_idle_notification(self, poller, tmp_path):
        """Test poll sends idle notification after threshold."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.config") as mock_config:
            mock_config.polling.idle_notification_seconds = 5

            with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                    iteration_count = 0

                    async def session_exists_mock(name):
                        nonlocal iteration_count
                        iteration_count += 1
                        # Exit after idle threshold reached (5 seconds + 1 for initial + 1 for notification)
                        return iteration_count < 8

                    mock_terminal.session_exists = session_exists_mock

                    # Output never changes (stays at "stuck output")
                    mock_terminal.capture_pane = AsyncMock(return_value="stuck output\n")

                    # Collect events
                    events = []
                    async for event in poller.poll("test-idle", "test-tmux", output_file, has_exit_marker=False):
                        events.append(event)

                    # Find IdleDetected event
                    idle_events = [e for e in events if isinstance(e, IdleDetected)]
                    assert len(idle_events) >= 1
                    assert idle_events[0].session_id == "test-idle"
                    assert idle_events[0].idle_seconds == 5

    async def test_periodic_updates_with_exponential_backoff(self, poller, tmp_path):
        """Test poll sends periodic updates with exponential backoff."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.config") as mock_config:
            mock_config.polling.idle_notification_seconds = 60

            with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                    iteration_count = 0

                    async def session_exists_mock(name):
                        nonlocal iteration_count
                        iteration_count += 1
                        # Run for 20 iterations (need: 1 initial + 5 for first periodic + 10 for second periodic = 16)
                        return iteration_count < 20

                    mock_terminal.session_exists = session_exists_mock

                    # Output doesn't change after first
                    first_call = True

                    async def capture_mock(name):
                        nonlocal first_call
                        if first_call:
                            first_call = False
                            return "initial output\n"
                        return "initial output\n"  # Same output

                    mock_terminal.capture_pane = capture_mock

                    # Collect events
                    events = []
                    async for event in poller.poll("test-periodic", "test-tmux", output_file, has_exit_marker=False):
                        events.append(event)

                    # Verify periodic OutputChanged events sent
                    output_changed_events = [e for e in events if isinstance(e, OutputChanged)]
                    # Should have initial + periodic updates (at intervals 5, 10, etc.)
                    assert len(output_changed_events) >= 2

    async def test_file_write_error_handling(self, poller):
        """Test poll handles file write errors gracefully."""
        # Use non-existent directory to trigger write error
        output_file = Path("/nonexistent/output.txt")

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                # Session dies immediately
                mock_terminal.session_exists = AsyncMock(return_value=False)

                # Should not raise exception, just log warning
                events = []
                async for event in poller.poll("test-err", "test-tmux", output_file, has_exit_marker=False):
                    events.append(event)

                # Verify ProcessExited event still yielded
                assert len(events) == 1
                assert isinstance(events[0], ProcessExited)


