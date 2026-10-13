"""The local computer as the daemon projects it to the TUI.

The daemon's computers projection marks one entry local and carries that
computer's name and tmux binary. The TUI adopts that entry when it arrives and
answers every local-versus-remote question from it, so no view reads machine
configuration for the computer's identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from teleclaude.api_models import ComputerDTO
from teleclaude.constants import LOCAL_COMPUTER


@dataclass(frozen=True)
class LocalComputer:
    """The facts of the computer this TUI runs on."""

    name: str
    tmux_binary: str | None


@dataclass
class _LocalComputerHolder:
    current: LocalComputer | None = None


_HOLDER = _LocalComputerHolder()


def adopt_local_computer(computers: Sequence[ComputerDTO]) -> LocalComputer | None:
    """Adopt the local entry of a computers projection; keep the last adopted one when it carries none."""
    entry = next((computer for computer in computers if computer.is_local), None)
    if entry is not None:
        _HOLDER.current = LocalComputer(name=entry.name, tmux_binary=entry.tmux_binary)
    return _HOLDER.current


def local_computer() -> LocalComputer | None:
    """The adopted local computer, or None before the daemon's projection has arrived."""
    return _HOLDER.current


def local_computer_name() -> str | None:
    """The local computer's name, or None before the daemon's projection has arrived."""
    return _HOLDER.current.name if _HOLDER.current is not None else None


def is_remote_computer(computer: str | None) -> bool:
    """Whether a computer label names a computer other than this one."""
    return bool(computer) and computer not in (LOCAL_COMPUTER, local_computer_name())


def remote_computer(computer: str | None) -> str | None:
    """The computer a UI row belongs to when it is another computer, else None."""
    return computer if is_remote_computer(computer) else None
