"""Terminal-origin metadata contract for adapter events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, TypedDict

TERMINAL_METADATA_KEY = "terminal"
TERMINAL_TTY_PATH_KEY = "tty_path"
TERMINAL_PARENT_PID_KEY = "parent_pid"
TERMINAL_SIZE_KEY = "terminal_size"


class TerminalOutboxPayload(TypedDict, total=False):
    session_id: str
    args: list[str]
    text: str
    message_id: str


class TerminalOutboxMetadata(TypedDict, total=False):
    adapter_type: str
    project_dir: str
    channel_metadata: Mapping[str, object]
    auto_command: str
    message_thread_id: int
    title: str
    channel_id: str
    raw_format: bool
    parse_mode: str


class TerminalOutboxResponse(TypedDict, total=False):
    status: str
    data: object
    error: str
    code: str


@dataclass
class TerminalEventMetadata:
    """Contract for terminal-origin metadata in adapter channel_metadata."""

    tty_path: Optional[str] = None
    parent_pid: Optional[int] = None
    terminal_size: Optional[str] = None

    def to_channel_metadata(self) -> TerminalChannelMetadata:
        """Serialize into channel_metadata payload."""
        terminal_payload: TerminalChannelPayload = {}
        if self.tty_path:
            terminal_payload[TERMINAL_TTY_PATH_KEY] = self.tty_path
        if self.parent_pid is not None:
            terminal_payload[TERMINAL_PARENT_PID_KEY] = self.parent_pid
        if self.terminal_size:
            terminal_payload[TERMINAL_SIZE_KEY] = self.terminal_size
        if not terminal_payload:
            return {}
        return {TERMINAL_METADATA_KEY: terminal_payload}

    @classmethod
    def from_channel_metadata(
        cls,
        channel_metadata: Mapping[str, object] | None,
    ) -> "TerminalEventMetadata":
        """Parse terminal metadata from channel_metadata dict."""
        if not channel_metadata:
            return cls()

        raw_terminal = channel_metadata.get(TERMINAL_METADATA_KEY)
        if not isinstance(raw_terminal, dict):
            return cls()

        tty_raw = raw_terminal.get(TERMINAL_TTY_PATH_KEY)
        pid_raw = raw_terminal.get(TERMINAL_PARENT_PID_KEY)
        size_raw = raw_terminal.get(TERMINAL_SIZE_KEY)

        tty_path = str(tty_raw) if isinstance(tty_raw, str) and tty_raw else None

        parent_pid: int | None = None
        if isinstance(pid_raw, int):
            parent_pid = pid_raw
        elif isinstance(pid_raw, str) and pid_raw.isdigit():
            parent_pid = int(pid_raw)

        terminal_size = str(size_raw) if isinstance(size_raw, str) and size_raw else None

        return cls(tty_path=tty_path, parent_pid=parent_pid, terminal_size=terminal_size)


TerminalChannelPayload = dict[str, str | int]
TerminalChannelMetadata = dict[str, TerminalChannelPayload]
