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


class _StubTerminalReader:
    def __init__(self, outputs: list[str | None]) -> None:
        self._outputs = outputs
        self._index = 0
        self.last_output = ""

    def read(self) -> str:
        if self._index >= len(self._outputs):
            return self.last_output
        value = self._outputs[self._index]
        self._index += 1
        if value is None:
            return self.last_output
        self.last_output = value
        return value


def _patch_reader(outputs: list[str | None]):
    reader = _StubTerminalReader(outputs)
    return patch(
        "teleclaude.core.output_poller.terminal_bridge.capture_pane",
        new=AsyncMock(side_effect=lambda _name, lines=None: reader.read()),
    )


def _init_terminal_mock(mock_terminal) -> None:
    mock_terminal.is_pane_dead = AsyncMock(return_value=False)


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
            _init_terminal_mock(mock_terminal)
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with _patch_reader([]):
                    # Session no longer exists
                    mock_terminal.session_exists = AsyncMock(return_value=False)

                    # Collect events
                    events = []
                    async for event in poller.poll("test-123", "test-tmux", output_file):
                        events.append(event)

                # Verify ProcessExited event with no exit code
                assert len(events) == 1
                assert isinstance(events[0], ProcessExited)
                assert events[0].session_id == "test-123"
                assert events[0].exit_code is None

    async def test_shell_return_keeps_polling(self, poller, tmp_path):
        """Shell return should not terminate polling."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            _init_terminal_mock(mock_terminal)
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                    with _patch_reader(["command output\n"]):
                        mock_terminal.session_exists = AsyncMock(side_effect=[True, True, False])
                        mock_terminal.is_process_running = AsyncMock(side_effect=[True, False, False])
                        mock_terminal.is_pane_dead = AsyncMock(return_value=False)

                        events = []
                        async for event in poller.poll("test-456", "test-tmux", output_file):
                            events.append(event)

                assert len(events) >= 1
                assert any(isinstance(e, OutputChanged) for e in events)
                assert not any(isinstance(e, ProcessExited) and e.exit_code == 0 for e in events)

    async def test_shell_exit_emits_process_exited_without_code(self, poller, tmp_path):
        """Shell exit should emit ProcessExited with exit_code None."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            _init_terminal_mock(mock_terminal)
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                    with _patch_reader(["command output\n"]):
                        mock_terminal.session_exists = AsyncMock(return_value=True)
                        mock_terminal.is_process_running = AsyncMock(side_effect=[True, False])
                        mock_terminal.is_pane_dead = AsyncMock(return_value=True)

                        events = []
                        async for event in poller.poll("test-457", "test-tmux", output_file):
                            events.append(event)

                assert len(events) >= 1
                assert isinstance(events[-1], ProcessExited)
                assert events[-1].exit_code is None
                assert "command output" in events[-1].final_output

    async def test_periodic_updates_send_full_file_contents(self, poller, tmp_path):
        """Test that periodic updates always send full file contents, not deltas."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            _init_terminal_mock(mock_terminal)
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                    with _patch_reader(["line 1\n", "line 1\nline 2\n", None]):
                        call_count = 0

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal call_count
                            call_count += 1
                            return call_count < 4

                        mock_terminal.session_exists = session_exists_mock
                        mock_terminal.get_current_directory = AsyncMock(return_value="/test/dir")
                        mock_terminal.is_process_running = AsyncMock(return_value=True)

                        # Collect events
                        events = []
                        async for event in poller.poll("test-consistent", "test-tmux", output_file):
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
            _init_terminal_mock(mock_terminal)
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                    with _patch_reader(["output 1\n", "output 1\noutput 2\n", None]):
                        call_count = 0

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal call_count
                            call_count += 1
                            # Exit after 6 iterations (3 poll cycles * 2-second update interval)
                            return call_count < 6

                        mock_terminal.session_exists = session_exists_mock
                        mock_terminal.get_current_directory = AsyncMock(return_value="/test/dir")
                        mock_terminal.is_process_running = AsyncMock(return_value=True)

                        # Collect events
                        events = []
                        async for event in poller.poll("test-789", "test-tmux", output_file):
                            events.append(event)

                # Verify OutputChanged events (sent every 2 poll iterations)
                # 6 iterations / 2 = 3 potential updates, but last is ProcessExited
                assert len(events) >= 2  # At least 1-2 OutputChanged + ProcessExited
                for event in events[:-1]:
                    assert isinstance(event, OutputChanged)
                # Last event is ProcessExited
                assert isinstance(events[-1], ProcessExited)

    async def test_output_change_emits_after_interval_even_if_stable(self, poller, tmp_path):
        """Output changes should emit after interval even if output stops changing."""
        output_file = tmp_path / "output.txt"

        def time_mock():
            call_count = 0

            def _time():
                nonlocal call_count
                call_count += 1
                if call_count < 10:
                    return 1000.0 + (call_count * 0.2)
                return 1004.0 + (call_count - 10) * 0.1

            return _time

        with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
            _init_terminal_mock(mock_terminal)
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with patch("teleclaude.core.output_poller.time.time", new=time_mock()):
                    with _patch_reader(["output 1\n"]):
                        call_count = 0

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal call_count
                            call_count += 1
                            return call_count < 3

                        mock_terminal.session_exists = session_exists_mock
                        mock_terminal.get_current_directory = AsyncMock(return_value="/test/dir")
                        mock_terminal.is_process_running = AsyncMock(return_value=True)

                        events = []
                        async for event in poller.poll("test-stable", "test-tmux", output_file):
                            events.append(event)

                assert isinstance(events[0], OutputChanged)
                assert "output 1" in events[0].output
                assert isinstance(events[-1], ProcessExited)

    async def test_markerless_exit_forces_final_update(self, poller, tmp_path):
        """Markerless exit should force a final OutputChanged even if interval hasn't elapsed."""
        output_file = tmp_path / "output.txt"

        def time_mock():
            times = [1000.0, 1002.0, 1004.0, 1004.5, 1005.0, 1005.0]
            for t in times:
                yield t
            while True:
                yield times[-1]

        time_iter = time_mock()

        with patch("teleclaude.core.output_poller.DIRECTORY_CHECK_INTERVAL", 0):
            with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                _init_terminal_mock(mock_terminal)
                with patch("teleclaude.core.output_poller.db") as mock_db:
                    with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                        with patch("teleclaude.core.output_poller.time.time", new=lambda: next(time_iter)):
                            with _patch_reader(["first output\n", "second output\n"]):
                                mock_terminal.session_exists = AsyncMock(side_effect=[True, True, False])
                                mock_db.get_session = AsyncMock(return_value=None)

                                events = []
                                async for event in poller.poll("test-final", "test-tmux", output_file):
                                    events.append(event)

        assert len(events) >= 2
        assert any(isinstance(event, OutputChanged) for event in events)
        assert isinstance(events[-1], ProcessExited)

    async def test_periodic_updates_with_exponential_backoff(self, poller, tmp_path):
        """Test poll does not send periodic updates when output is unchanged."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.DIRECTORY_CHECK_INTERVAL", 0):  # Disable directory checking
            with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                _init_terminal_mock(mock_terminal)
                with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                    with patch("teleclaude.core.output_poller.time.time", make_advancing_time_mock()):
                        with _patch_reader(["initial output\n"]):
                            iteration_count = 0

                            async def session_exists_mock(name, log_missing=True):
                                nonlocal iteration_count
                                iteration_count += 1
                                # Run for 20 iterations (need: 1 initial + 5 for first periodic + 10 for second periodic = 16)
                                return iteration_count < 20

                            mock_terminal.session_exists = session_exists_mock
                            mock_terminal.is_process_running = AsyncMock(return_value=True)

                            # Collect events
                            events = []
                            async for event in poller.poll("test-periodic", "test-tmux", output_file):
                                events.append(event)

                    # Verify only the initial OutputChanged event is sent
                    output_changed_events = [e for e in events if isinstance(e, OutputChanged)]
                    assert len(output_changed_events) == 1

    async def test_idle_summary_logging_suppresses_tick_noise(self, poller, tmp_path, caplog):
        """Summarize idle ticks instead of per-tick spam."""
        output_file = tmp_path / "output.txt"

        trace_level = getattr(logging, "TRACE", logging.DEBUG)
        caplog.set_level(trace_level, logger="teleclaude.core.output_poller")

        with patch("teleclaude.core.output_poller.DIRECTORY_CHECK_INTERVAL", 0):
            with patch("teleclaude.core.output_poller.IDLE_SUMMARY_INTERVAL_S", 0.5):
                with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                    _init_terminal_mock(mock_terminal)
                    with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                        with patch(
                            "teleclaude.core.output_poller.time.time",
                            make_advancing_time_mock(increment=0.2),
                        ):
                            with _patch_reader(["output\n"]):
                                iteration_count = 0

                                async def session_exists_mock(name, log_missing=True):
                                    nonlocal iteration_count
                                    iteration_count += 1
                                    return iteration_count < 8

                                mock_terminal.session_exists = session_exists_mock
                                mock_terminal.is_process_running = AsyncMock(return_value=True)

                                events = []
                                async for event in poller.poll("test-idle", "test-tmux", output_file):
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
            _init_terminal_mock(mock_terminal)
            with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                with _patch_reader([]):
                    # Session dies immediately
                    mock_terminal.session_exists = AsyncMock(return_value=False)
                    mock_terminal.is_process_running = AsyncMock(return_value=False)

                    # Should not raise exception, just log warning
                    events = []
                    async for event in poller.poll("test-err", "test-tmux", output_file):
                        events.append(event)

                # Verify ProcessExited event still yielded
                assert len(events) == 1
                assert isinstance(events[0], ProcessExited)

    async def test_directory_change_detection(self, poller, tmp_path):
        """Test poll detects directory changes and yields DirectoryChanged events."""
        output_file = tmp_path / "output.txt"

        with patch("teleclaude.core.output_poller.DIRECTORY_CHECK_INTERVAL", 3):  # Check every 3 seconds
            with patch("teleclaude.core.output_poller.terminal_bridge") as mock_terminal:
                _init_terminal_mock(mock_terminal)
                with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                    with _patch_reader(["output\n"]):
                        iteration_count = 0
                        directory_calls = 0

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal iteration_count
                            iteration_count += 1
                            # Run for 10 iterations (3 directory checks at intervals 3, 6, 9)
                            return iteration_count < 10

                        mock_terminal.session_exists = session_exists_mock
                        mock_terminal.is_process_running = AsyncMock(return_value=True)

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
                        async for event in poller.poll("test-dir", "test-tmux", output_file):
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
                _init_terminal_mock(mock_terminal)
                with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
                    with _patch_reader(["output\n"]):
                        iteration_count = 0

                        async def session_exists_mock(name, log_missing=True):
                            nonlocal iteration_count
                            iteration_count += 1
                            return iteration_count < 5

                        mock_terminal.session_exists = session_exists_mock
                        mock_terminal.is_process_running = AsyncMock(return_value=True)
                        mock_terminal.get_current_directory = AsyncMock(return_value="/home/user")

                        # Collect events
                        events = []
                        async for event in poller.poll("test-disabled", "test-tmux", output_file):
                            events.append(event)

                        # Verify no DirectoryChanged events
                        dir_events = [e for e in events if isinstance(e, DirectoryChanged)]
                        assert len(dir_events) == 0
                        # Verify get_current_directory never called
                        mock_terminal.get_current_directory.assert_not_called()
