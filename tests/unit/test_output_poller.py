"""Unit tests for simplified OutputPoller."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.output_poller import (
    DirectoryChanged,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)


def make_advancing_time_mock(start_time=1000.0, increment=1.0):
    """Create a time.time() mock that advances by increment on each call.

    Args:
        start_time: Starting timestamp
        increment: Seconds to advance on each call

    Returns:
        Mock function that returns advancing time
    """
    current_time = [start_time]  # Use list for mutable state

    def advancing_time():
        result = current_time[0]
        current_time[0] += increment
        return result

    return advancing_time


@pytest.mark.unit
class TestOutputPoller:
    """Test OutputPoller core functionality."""

    @pytest.fixture
    def poller(self):
        """Create OutputPoller instance."""
        return OutputPoller()

    def test_extract_exit_code_with_marker(self, poller):
        """Test exit code extraction when marker present."""
        marker_id = "abc12345"
        output = f"some output\n__EXIT__{marker_id}__0__\n"
        exit_code = poller._extract_exit_code(output, marker_id=marker_id)
        assert exit_code == 0

        output = f"error output\n__EXIT__{marker_id}__1__\n"
        exit_code = poller._extract_exit_code(output, marker_id=marker_id)
        assert exit_code == 1

    def test_extract_exit_code_without_marker(self, poller):
        """Test exit code extraction when no marker_id provided."""
        output = "some output\n__EXIT__abc12345__0__\n"
        exit_code = poller._extract_exit_code(output, marker_id=None)
        assert exit_code is None

    def test_extract_exit_code_no_match(self, poller):
        """Test exit code when marker_id doesn't match output."""
        marker_id = "abc12345"
        output = "some output without marker\n"
        exit_code = poller._extract_exit_code(output, marker_id=marker_id)
        assert exit_code is None

        # Different marker_id in output - should not match
        output = "some output\n__EXIT__different__0__\n"
        exit_code = poller._extract_exit_code(output, marker_id=marker_id)
        assert exit_code is None


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
            with patch("teleclaude.core.output_poller.db") as mock_db:
                with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                    # Session no longer exists
                    mock_terminal.session_exists = AsyncMock(return_value=False)
                    # Mock db.get_session to return None (session closed)
                    mock_db.get_session = AsyncMock(return_value=None)

                    # Collect events
                    events = []
                    async for event in poller.poll("test-123", "test-tmux", output_file, marker_id=None):
                        events.append(event)

                # Verify ProcessExited event with no exit code
                assert len(events) == 1
                assert isinstance(events[0], ProcessExited)
                assert events[0].session_id == "test-123"
                assert events[0].exit_code is None

    async def test_exit_code_detection(self, poller, tmp_path):
        """Test poll detects exit code and stops."""
        output_file = tmp_path / "output.txt"
        marker_id = "testmrkr"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                # Session exists
                mock_terminal.session_exists = AsyncMock(return_value=True)

                # Output appears immediately with exit marker
                async def capture_mock(name):
                    return f"command output\n__EXIT__{marker_id}__0__\n"

                mock_terminal.capture_pane = capture_mock

                # Collect events
                events = []
                async for event in poller.poll("test-456", "test-tmux", output_file, marker_id=marker_id):
                    events.append(event)

                # Sends OutputChanged first, then ProcessExited
                assert len(events) == 2
                assert isinstance(events[0], OutputChanged)
                assert events[0].output == "command output\n"
                assert isinstance(events[1], ProcessExited)
                assert events[1].session_id == "test-456"
                assert events[1].exit_code == 0
                assert events[1].final_output == "command output\n"  # Current tmux pane

    async def test_exit_code_detection_with_prompt_on_same_line(self, poller, tmp_path):
        """Test exit marker detection when marker and prompt are on same line (after SIGINT)."""
        output_file = tmp_path / "output.txt"
        marker_id = "sigintmk"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                mock_terminal.session_exists = AsyncMock(return_value=True)

                # Realistic output after SIGINT: marker followed by prompt on SAME line
                async def capture_mock(name):
                    return f"^C\n__EXIT__{marker_id}__130__➜  teleclaude git:(main) ✗ "

                mock_terminal.capture_pane = capture_mock

                # Collect events
                events = []
                async for event in poller.poll("test-sigint", "test-tmux", output_file, marker_id=marker_id):
                    events.append(event)

                # Sends OutputChanged first, then ProcessExited
                assert len(events) == 2
                assert isinstance(events[0], OutputChanged)
                assert isinstance(events[1], ProcessExited)
                assert events[1].exit_code == 130  # SIGINT exit code

    async def test_exit_code_detection_with_repeating_headers(self, poller, tmp_path):
        """Test exit marker detection when TUI has repeating headers.

        With hash-based markers, each command has a unique marker_id,
        so repeating headers don't affect detection at all.
        """
        output_file = tmp_path / "output.txt"
        marker_id = "repthdr1"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                mock_terminal.session_exists = AsyncMock(return_value=True)

                iteration = 0

                async def capture_mock(name):
                    nonlocal iteration
                    iteration += 1

                    if iteration == 1:
                        # First poll: initial TUI screen with header
                        return "Sonnet 4.5 · Claude Max\n/Users/test/project\nInitial content\n"
                    else:
                        # Second poll: TUI cleared, shows header again + exit marker
                        return f"Sonnet 4.5 · Claude Max\n/Users/test/project\n__EXIT__{marker_id}__0__\n"

                mock_terminal.capture_pane = capture_mock

                # Collect events
                events = []
                async for event in poller.poll("test-rfind", "test-tmux", output_file, marker_id=marker_id):
                    events.append(event)

                # Should detect exit code
                assert len(events) >= 1
                assert isinstance(events[-1], ProcessExited)
                assert events[-1].exit_code == 0

                # final_output contains CURRENT tmux pane (not accumulated history)
                assert "__EXIT__" not in events[-1].final_output  # Marker stripped
                assert "Sonnet 4.5 · Claude Max" in events[-1].final_output

    async def test_exit_marker_with_echo_command_visible(self, poller, tmp_path):
        """Test that echo command in output doesn't affect marker detection.

        With hash-based markers, the echo command shows __EXIT__{marker_id}__$?__
        while the actual marker is __EXIT__{marker_id}__0__. The exact pattern
        match ensures only the resolved marker is detected.
        """
        output_file = tmp_path / "output.txt"
        marker_id = "echomrkr"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                mock_terminal.session_exists = AsyncMock(return_value=True)

                iteration = 0

                async def capture_mock(name):
                    nonlocal iteration
                    iteration += 1

                    if iteration == 1:
                        # First poll: command with echo visible (marker template, not resolved)
                        return f'$ ls -la; echo "__EXIT__{marker_id}__$?__"\nfile1.txt\nfile2.txt\n'
                    else:
                        # Second poll: echo + ACTUAL resolved marker appears
                        return f'$ ls -la; echo "__EXIT__{marker_id}__$?__"\nfile1.txt\nfile2.txt\n__EXIT__{marker_id}__0__\n'

                mock_terminal.capture_pane = capture_mock

                # Collect events
                events = []
                async for event in poller.poll("test-count", "test-tmux", output_file, marker_id=marker_id):
                    events.append(event)

                # Should detect exit on second poll (when ACTUAL marker appears)
                assert len(events) >= 1
                assert isinstance(events[-1], ProcessExited)
                assert events[-1].exit_code == 0

                # Verify final output has markers stripped
                assert f"__EXIT__{marker_id}__0__" not in events[-1].final_output
                assert "file1.txt" in events[-1].final_output

    async def test_old_markers_in_scrollback_ignored_due_to_different_marker_id(self, poller, tmp_path):
        """Test that old markers from previous commands are ignored due to different marker_id.

        With hash-based markers, each command has a unique marker_id. Old markers
        in scrollback have different marker_ids, so they're naturally ignored.
        """
        output_file = tmp_path / "output.txt"
        current_marker_id = "newcmd01"
        old_marker_id = "oldcmd99"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                    with patch("teleclaude.core.output_poller.db") as mock_db:
                        iteration = 0

                        # Mock db.get_session to avoid AttributeError in watchdog
                        mock_db.get_session = AsyncMock(return_value=None)

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal iteration
                            # Session dies after 3 polls (stops loop)
                            return iteration < 3

                        async def capture_mock(name):
                            nonlocal iteration
                            iteration += 1

                            if iteration == 1:
                                # First poll: OLD marker from PREVIOUS command in scrollback (different marker_id)
                                return f"previous command\n__EXIT__{old_marker_id}__0__\n$ new_command with output\nline1\nline2\n"
                            else:
                                # Later polls: just current command output (no new marker yet)
                                return "$ new_command\nmore output\n"

                        mock_terminal.session_exists = session_exists_mock
                        mock_terminal.capture_pane = capture_mock

                        # Collect events - should NOT exit on first poll due to different marker_id
                        events = []
                        async for event in poller.poll(
                            "test-baseline", "test-tmux", output_file, marker_id=current_marker_id
                        ):
                            events.append(event)

                    # Should NOT detect exit from old marker (different marker_id)
                    # Session dies eventually, so we get ProcessExited with exit_code=None
                    assert len(events) >= 2
                    assert isinstance(events[-1], ProcessExited)
                    assert events[-1].exit_code is None  # Session death, not marker-based exit
                    # At least one OutputChanged before exit
                    assert any(isinstance(e, OutputChanged) for e in events)

    async def test_marker_detection_unaffected_by_screen_clear(self, poller, tmp_path):
        """Test that screen clear doesn't affect marker detection.

        With hash-based markers, we search for exact marker pattern.
        Screen clears don't affect detection - marker either matches or doesn't.
        """
        output_file = tmp_path / "output.txt"
        marker_id = "clrmrkr1"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                mock_terminal.session_exists = AsyncMock(return_value=True)

                iteration = 0

                async def capture_mock(name):
                    nonlocal iteration
                    iteration += 1

                    if iteration == 1:
                        # First poll: some content (no marker yet)
                        return "old_content\ncommand running\n"
                    elif iteration == 2:
                        # Screen clear: content gone
                        return "TUI cleared screen\n"
                    else:
                        # Marker appears after screen clear
                        return f"TUI cleared screen\n__EXIT__{marker_id}__0__\n"

                mock_terminal.capture_pane = capture_mock

                # Collect events
                events = []
                async for event in poller.poll("test-clear", "test-tmux", output_file, marker_id=marker_id):
                    events.append(event)

                # Should detect exit when marker appears (screen clear doesn't matter)
                assert len(events) >= 1
                assert isinstance(events[-1], ProcessExited)
                assert events[-1].exit_code == 0

    async def test_periodic_updates_send_full_file_contents(self, poller, tmp_path):
        """Test that periodic updates always send full file contents, not deltas."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                    with patch("teleclaude.core.output_poller.db") as mock_db:
                        mock_terminal.session_exists = AsyncMock(return_value=True)
                        mock_terminal.get_current_directory = AsyncMock(return_value="/test/dir")
                        mock_db.get_session = AsyncMock(return_value=None)

                        # Output accumulates over time
                        call_count = 0

                        async def capture_mock(name):
                            nonlocal call_count
                            call_count += 1
                            if call_count < 3:
                                return "line 1\n"
                            if call_count < 5:
                                return "line 1\nline 2\n"
                            # Session dies after 5 calls
                            return "line 1\nline 2\n"

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal call_count
                            return call_count < 5

                        mock_terminal.capture_pane = capture_mock
                        mock_terminal.session_exists = session_exists_mock

                        # Collect events
                        events = []
                        async for event in poller.poll("test-consistent", "test-tmux", output_file, marker_id=None):
                            events.append(event)

                    # Find OutputChanged events
                    output_events = [e for e in events if isinstance(e, OutputChanged)]

                    # Each OutputChanged contains current tmux pane (not accumulated file)
                    # Tmux pane naturally accumulates output, so later events have more content
                    assert len(output_events) >= 1
                    # Last output should have both lines (tmux accumulated them)
                    if len(output_events) >= 1:
                        assert "line 1" in output_events[-1].output
                        assert "line 2" in output_events[-1].output

    async def test_output_changed_detection(self, poller, tmp_path):
        """Test poll detects output changes."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.db") as mock_db:
                with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                    with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                        call_count = 0

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal call_count
                            call_count += 1
                            # Exit after 6 iterations (3 poll cycles * 2-second update interval)
                            return call_count < 6

                        mock_terminal.session_exists = session_exists_mock
                        mock_terminal.get_current_directory = AsyncMock(return_value="/test/dir")
                        mock_db.get_session = AsyncMock(return_value=None)

                        # Output accumulates over time
                        outputs = ["output 1\n", "output 1\noutput 2\n"]
                        output_index = 0

                        async def capture_mock(name):
                            nonlocal output_index
                            # Return accumulated output
                            result = outputs[min(output_index // 2, len(outputs) - 1)]
                            output_index += 1
                            return result

                        mock_terminal.capture_pane = capture_mock

                        # Collect events
                        events = []
                        async for event in poller.poll("test-789", "test-tmux", output_file, marker_id=None):
                            events.append(event)

                # Verify OutputChanged events (sent every 2 poll iterations)
                # 6 iterations / 2 = 3 potential updates, but last is ProcessExited
                assert len(events) >= 2  # At least 1-2 OutputChanged + ProcessExited
                for event in events[:-1]:
                    assert isinstance(event, OutputChanged)
                # Last event is ProcessExited
                assert isinstance(events[-1], ProcessExited)

    async def test_periodic_updates_with_exponential_backoff(self, poller, tmp_path):
        """Test poll sends periodic updates with exponential backoff."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.DIRECTORY_CHECK_INTERVAL", 0):  # Disable directory checking
            with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                with patch("teleclaude.core.output_poller.db") as mock_db:
                    with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                        with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                            iteration_count = 0

                            async def session_exists_mock(name, log_missing=True):
                                nonlocal iteration_count
                                iteration_count += 1
                                # Run for 20 iterations (need: 1 initial + 5 for first periodic + 10 for second periodic = 16)
                                return iteration_count < 20

                            mock_terminal.session_exists = session_exists_mock
                            mock_db.get_session = AsyncMock(return_value=None)

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
                            async for event in poller.poll("test-periodic", "test-tmux", output_file, marker_id=None):
                                events.append(event)

                    # Verify periodic OutputChanged events sent
                    output_changed_events = [e for e in events if isinstance(e, OutputChanged)]
                    # Should have initial + periodic updates (at intervals 5, 10, etc.)
                    assert len(output_changed_events) >= 2

    async def test_idle_summary_logging_suppresses_tick_noise(self, poller, tmp_path, caplog):
        """Summarize idle ticks instead of per-tick spam."""
        output_file = tmp_path / "output.txt"

        caplog.set_level(logging.DEBUG, logger="teleclaude.core.output_poller")

        with patch("teleclaude.core.output_poller.DIRECTORY_CHECK_INTERVAL", 0):
            with patch("teleclaude.core.output_poller.IDLE_SUMMARY_INTERVAL_S", 0.5):
                with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                    with patch("teleclaude.core.output_poller.db") as mock_db:
                        with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                            with patch(
                                "teleclaude.core.output_poller.time.time",
                                make_advancing_time_mock(increment=0.2),
                            ):
                                iteration_count = 0

                                async def session_exists_mock(name, log_missing=True):
                                    nonlocal iteration_count
                                    iteration_count += 1
                                    return iteration_count < 8

                                mock_terminal.session_exists = session_exists_mock
                                mock_terminal.capture_pane = AsyncMock(return_value="output\n")
                                mock_db.get_session = AsyncMock(return_value=None)

                                events = []
                                async for event in poller.poll("test-idle", "test-tmux", output_file, marker_id=None):
                                    events.append(event)

        messages = [record.getMessage() for record in caplog.records]
        assert any("idle: unchanged for" in msg for msg in messages)
        assert all("SKIPPING yield" not in msg for msg in messages)
        assert all("Output unchanged" not in msg for msg in messages)

    async def test_file_write_error_handling(self, poller):
        """Test poll handles file write errors gracefully."""
        # Use non-existent directory to trigger write error
        output_file = Path("/nonexistent/output.txt")

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            with patch("teleclaude.core.output_poller.db") as mock_db:
                with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                    # Session dies immediately
                    mock_terminal.session_exists = AsyncMock(return_value=False)
                    # Mock db.get_session to return None
                    mock_db.get_session = AsyncMock(return_value=None)

                    # Should not raise exception, just log warning
                    events = []
                    async for event in poller.poll("test-err", "test-tmux", output_file, marker_id=None):
                        events.append(event)

                # Verify ProcessExited event still yielded
                assert len(events) == 1
                assert isinstance(events[0], ProcessExited)

    async def test_directory_change_detection(self, poller, tmp_path):
        """Test poll detects directory changes and yields DirectoryChanged events."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.DIRECTORY_CHECK_INTERVAL", 3):  # Check every 3 seconds
            with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                with patch("teleclaude.core.output_poller.db") as mock_db:
                    with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                        iteration_count = 0
                        directory_calls = 0

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal iteration_count
                            iteration_count += 1
                            # Run for 10 iterations (3 directory checks at intervals 3, 6, 9)
                            return iteration_count < 10

                        mock_terminal.session_exists = session_exists_mock
                        mock_db.get_session = AsyncMock(return_value=None)
                        mock_terminal.capture_pane = AsyncMock(return_value="output\n")

                        # Directory changes on second check
                        async def get_current_directory_mock(name):
                            nonlocal directory_calls
                            directory_calls += 1
                            if directory_calls == 1:
                                return "/home/user/projects"
                            return "/home/user/projects/teleclaude"

                        mock_terminal.get_current_directory = get_current_directory_mock

                        # Collect events
                        events = []
                        async for event in poller.poll("test-dir", "test-tmux", output_file, marker_id=None):
                            events.append(event)

                        # Find DirectoryChanged event
                        dir_events = [e for e in events if isinstance(e, DirectoryChanged)]
                        assert len(dir_events) >= 1
                        assert dir_events[0].session_id == "test-dir"
                        assert dir_events[0].old_path == "/home/user/projects"
                        assert dir_events[0].new_path == "/home/user/projects/teleclaude"

    async def test_directory_check_disabled(self, poller, tmp_path):
        """Test poll skips directory checks when interval is 0."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.DIRECTORY_CHECK_INTERVAL", 0):  # Disable directory checking
            with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                with patch("teleclaude.core.output_poller.db") as mock_db:
                    with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                        iteration_count = 0

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal iteration_count
                            iteration_count += 1
                            return iteration_count < 5

                        mock_terminal.session_exists = session_exists_mock
                        mock_db.get_session = AsyncMock(return_value=None)
                        mock_terminal.capture_pane = AsyncMock(return_value="output\n")
                        mock_terminal.get_current_directory = AsyncMock(return_value="/home/user")

                        # Collect events
                        events = []
                        async for event in poller.poll("test-disabled", "test-tmux", output_file, marker_id=None):
                            events.append(event)

                        # Verify no DirectoryChanged events
                        dir_events = [e for e in events if isinstance(e, DirectoryChanged)]
                        assert len(dir_events) == 0
                        # Verify get_current_directory never called
                        mock_terminal.get_current_directory.assert_not_called()
