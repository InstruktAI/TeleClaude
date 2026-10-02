"""What one ``telec sessions send`` invocation asks for, resolved as the command resolves it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import SESSIONS_SEND

__all__ = ["SessionSendRequest", "SessionSendUsageError", "resolve_session_send"]

_DEFAULT_COMPUTER: Final = "local"
_COMBINED_TARGET_ERROR: Final = "do not combine positional session_id with --session"
_COMBINED_MESSAGE_ERROR: Final = "do not combine positional message with --message"
_MISSING_TARGET_ERROR: Final = "session_id required"
_MISSING_MESSAGE_ERROR: Final = "message required"
_MESSAGE_SEPARATOR: Final = " "


class SessionSendUsageError(ValueError):
    """The arguments name no deliverable send."""


@dataclass(frozen=True)
class SessionSendRequest:
    """The target session and payload of one send."""

    session_id: str
    message: str | None
    computer: str
    direct: bool
    close_link: bool


def resolve_session_send(args: Sequence[str]) -> SessionSendRequest:
    """Resolve send arguments into a request, or raise for arguments the command refuses.

    Raises ``CliUsageError`` for arguments the command surface rejects and
    ``SessionSendUsageError`` for combinations that name no deliverable send.
    """
    parsed = parse_command_args(SESSIONS_SEND, args)
    positionals = parsed.positionals
    session_id = positionals[0] if positionals else None
    message = _MESSAGE_SEPARATOR.join(positionals[1:]) if len(positionals) > 1 else None
    if parsed.has(F.FLAG_SESSION):
        if session_id is not None:
            raise SessionSendUsageError(_COMBINED_TARGET_ERROR)
        session_id = parsed.value(F.FLAG_SESSION)
    if parsed.has(F.FLAG_MESSAGE_ALIAS):
        if message is not None:
            raise SessionSendUsageError(_COMBINED_MESSAGE_ERROR)
        message = parsed.value(F.FLAG_MESSAGE_ALIAS)
    if not session_id:
        raise SessionSendUsageError(_MISSING_TARGET_ERROR)
    close_link = parsed.has(F.FLAG_CLOSE_LINK) or parsed.has(F.FLAG_CLOSE_LINK_ALIAS)
    if not close_link and not message:
        raise SessionSendUsageError(_MISSING_MESSAGE_ERROR)
    return SessionSendRequest(
        session_id=session_id,
        message=message or None,
        computer=parsed.value(F.FLAG_COMPUTER) or _DEFAULT_COMPUTER,
        direct=parsed.has(F.FLAG_DIRECT_SEND),
        close_link=close_link,
    )
