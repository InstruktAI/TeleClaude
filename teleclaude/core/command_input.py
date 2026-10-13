"""Typed command-input intent shared by interactive transport edges."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from teleclaude.cli.telec.auth import is_command_allowed

_ORDINARY_INPUT_MODE = "ordinary"
_INTERACTIVE_SHORTHAND_INPUT_MODE = "interactive_shorthand"
_SESSIONS_RUN_COMMAND = "telec sessions run"
_COMMAND_INPUT_CLEARANCE_DETAIL = "caller is not permitted to invoke command input"


class CommandInputMode(StrEnum):
    """Whether an ingress explicitly opts into interactive command shorthand."""

    ORDINARY = _ORDINARY_INPUT_MODE
    INTERACTIVE_SHORTHAND = _INTERACTIVE_SHORTHAND_INPUT_MODE


class CommandInputError(ValueError):
    """A command-shaped interactive input violates the command-input contract."""


@dataclass(frozen=True)
class NoCommandInput:
    """The input remains ordinary conversation."""


@dataclass(frozen=True)
class ResolvedCommandInput:
    """One published entry procedure invocation: the procedure's snippet ID and its argument text."""

    command: str
    args: str


CommandInputResult = NoCommandInput | ResolvedCommandInput


def admit_command_input(human_role: str | None) -> None:
    """Apply shared interactive command admission before an invocation is composed."""
    if not is_command_allowed(_SESSIONS_RUN_COMMAND, None, human_role):
        raise CommandInputError(_COMMAND_INPUT_CLEARANCE_DETAIL)
