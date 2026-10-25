"""Run fresh commands through one persistent, externally launched terminal."""

from __future__ import annotations

import fcntl
import os
import pty
import select
import shlex
import signal
import struct
import subprocess
import termios
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Self

_UTF8 = "utf-8"
_ERROR_REPLACE_MODE = "replace"
_PTY_SIZE_FORMAT = "HHHH"
_PTY_ROWS = 40
_PTY_COLUMNS = 120
_PTY_READ_CHUNK_SIZE = 65536
_PTY_WAIT_POLL_SECONDS = 0.1
_EXIT_MARKER_PREFIX = "_TC_TERMINAL_EXIT_"
_SHELL_COMMAND_FORMAT = '{command}; __tc_status=$?; printf "\\n{marker}%s\\n" "$__tc_status"'
_NEWLINE = "\n"
_BYTE_NEWLINE = b"\n"
_EMPTY_BYTES = b""
_EXIT_COMMAND = "exit"
_DEFAULT_OUTPUT_LIMIT = 1024 * 1024
_MAX_MARKER_OVERHEAD = 128
_PROCESS_EXIT_TIMEOUT_SECONDS = 5
_TERMINAL_NOT_STARTED = "The persistent terminal has not been started."
_TERMINAL_EXITED = "The persistent terminal exited before returning a command result."
_TERMINAL_TIMED_OUT = "The persistent terminal command exceeded its deadline."
_TERMINAL_OUTPUT_LIMIT = "The persistent terminal output exceeded its configured limit."
_TERMINAL_LOCAL_FLAGS_INDEX = 3


@dataclass(frozen=True)
class CommandResult:
    """Captured result from one command sent through a persistent terminal."""

    returncode: int
    output: str


class TerminalFailure(RuntimeError):
    """A terminal command failed to produce a bounded result."""

    def __init__(self, message: str, *, output: str = "") -> None:
        super().__init__(message)
        self.output = output


class PersistentTerminal:
    """Keep one real terminal session for a sequence of fresh child commands."""

    def __init__(
        self,
        launch_argv: Sequence[str],
        *,
        environment: Mapping[str, str] | None,
        timeout_seconds: float,
        output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT,
        disable_echo: bool = False,
    ) -> None:
        if not launch_argv:
            raise ValueError(_TERMINAL_NOT_STARTED)
        self._launch_argv = tuple(launch_argv)
        self._environment = dict(environment) if environment is not None else None
        self._timeout_seconds = timeout_seconds
        self._output_limit_bytes = output_limit_bytes
        self._disable_echo = disable_echo
        self._process: subprocess.Popen[bytes] | None = None
        self._master_fd: int | None = None
        self._buffer = bytearray()

    def __enter__(self) -> Self:
        master_fd, slave_fd = pty.openpty()
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack(_PTY_SIZE_FORMAT, _PTY_ROWS, _PTY_COLUMNS, 0, 0))
        if self._disable_echo:
            attributes = termios.tcgetattr(slave_fd)
            attributes[_TERMINAL_LOCAL_FLAGS_INDEX] &= ~termios.ECHO
            termios.tcsetattr(slave_fd, termios.TCSANOW, attributes)
        try:
            # A PTY-backed child is the public terminal boundary; an in-process substitute would not exercise it.
            self._process = subprocess.Popen(
                list(self._launch_argv),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=self._environment,
                close_fds=True,
                start_new_session=True,
            )
        except BaseException:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)
        self._master_fd = master_fd
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        return self

    def run(self, command: Sequence[str], *, timeout_seconds: float | None = None) -> CommandResult:
        if self._process is None or self._master_fd is None:
            raise TerminalFailure(_TERMINAL_NOT_STARTED)
        marker = f"{_EXIT_MARKER_PREFIX}{uuid.uuid4().hex}"
        shell_command = _SHELL_COMMAND_FORMAT.format(command=shlex.join(list(command)), marker=marker)
        os.write(self._master_fd, (shell_command + _NEWLINE).encode(_UTF8))
        output, status = self._read_to_marker(
            marker, self._timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        return CommandResult(returncode=status, output=output)

    def _read_to_marker(self, marker: str, timeout_seconds: float) -> tuple[str, int]:
        assert self._master_fd is not None
        assert self._process is not None
        deadline = time.monotonic() + timeout_seconds
        encoded_marker = marker.encode(_UTF8)
        start = 0
        while time.monotonic() < deadline:
            marker_index = self._buffer.rfind(encoded_marker, start)
            if marker_index >= 0:
                if marker_index - start > self._output_limit_bytes:
                    raise TerminalFailure(_TERMINAL_OUTPUT_LIMIT, output=self._captured_output(start))
                suffix = bytes(self._buffer[marker_index + len(encoded_marker) :])
                line_end = suffix.find(_BYTE_NEWLINE)
                status_line = suffix[:line_end] if line_end >= 0 else _EMPTY_BYTES
                if line_end >= 0 and status_line.strip().isdigit():
                    output = bytes(self._buffer[start:marker_index]).decode(_UTF8, errors=_ERROR_REPLACE_MODE)
                    self._buffer = bytearray(suffix[line_end + 1 :])
                    return output, int(status_line.strip())
            if self._process.poll() is not None:
                raise TerminalFailure(_TERMINAL_EXITED, output=self._captured_output(start))
            ready, _, _ = select.select([self._master_fd], [], [], _PTY_WAIT_POLL_SECONDS)
            if not ready:
                continue
            try:
                chunk = os.read(self._master_fd, _PTY_READ_CHUNK_SIZE)
            except BlockingIOError:
                continue
            except OSError as exc:
                if self._process.poll() is not None:
                    raise TerminalFailure(_TERMINAL_EXITED, output=self._captured_output(start)) from exc
                break
            if not chunk:
                break
            self._buffer.extend(chunk)
            if len(self._buffer) - start > self._output_limit_bytes + _MAX_MARKER_OVERHEAD:
                raise TerminalFailure(_TERMINAL_OUTPUT_LIMIT, output=self._captured_output(start))
        raise TerminalFailure(_TERMINAL_TIMED_OUT, output=self._captured_output(start))

    def _captured_output(self, start: int) -> str:
        return bytes(self._buffer[start:]).decode(_UTF8, errors=_ERROR_REPLACE_MODE)

    def close(self) -> None:
        process = self._process
        master_fd = self._master_fd
        if process is not None and process.poll() is None and master_fd is not None:
            try:
                os.write(master_fd, (_EXIT_COMMAND + _NEWLINE).encode(_UTF8))
            except OSError:
                self._signal_process_group(process, signal.SIGTERM)
        if process is not None:
            try:
                self._wait_draining(process, master_fd, self._timeout_seconds)
            except subprocess.TimeoutExpired:
                self._signal_process_group(process, signal.SIGTERM)
                try:
                    self._wait_draining(process, master_fd, _PROCESS_EXIT_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    self._signal_process_group(process, signal.SIGKILL)
                    process.wait()
        if master_fd is not None:
            os.close(master_fd)
        self._process = None
        self._master_fd = None

    @staticmethod
    def _wait_draining(process: subprocess.Popen[bytes], master_fd: int | None, timeout_seconds: float) -> None:
        """Wait for the shell to exit while reading the terminal, so output it still has to flush cannot block it."""
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args, timeout_seconds)
            if master_fd is None:
                time.sleep(_PTY_WAIT_POLL_SECONDS)
                continue
            ready, _, _ = select.select([master_fd], [], [], _PTY_WAIT_POLL_SECONDS)
            if ready:
                try:
                    os.read(master_fd, _PTY_READ_CHUNK_SIZE)
                except OSError:
                    time.sleep(_PTY_WAIT_POLL_SECONDS)

    @staticmethod
    def _signal_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return

    def __exit__(self, *_: object) -> None:
        self.close()
