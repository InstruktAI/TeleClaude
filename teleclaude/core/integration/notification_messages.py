"""Notification messages: one readable message stating what happened, to which thing, where and when.

A message is composed from the facts an event and its type's declaration state, so every type
reads the same way and a type introduced later needs no change here. The sentences use no markup
characters, so they read the same as markdown and as plain text on every channel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from teleclaude.events.catalog import EventDeclaration
from teleclaude.events.references import EventRef

_SENTENCE_END: Final = "."
_SENTENCE_SEPARATOR: Final = " "
_MESSAGE_TEMPLATE: Final = "{what} Thing: {subject}. Computer: {computer}. Time: {time}."
_SUBJECT_TEMPLATE: Final = "{kind} {identity}"
_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S UTC"


def compose_notification_message(
    *,
    declaration: EventDeclaration,
    subject: EventRef,
    computer: str,
    occurred_at: datetime,
    addition: str | None = None,
) -> str:
    """The message for an event of this declared type about this subject, as it happened on a computer.

    `addition` is a sentence a consumer appends to its own messages, such as how long a recovered
    thing was broken.
    """
    message = _MESSAGE_TEMPLATE.format(
        what=declaration.description.rstrip(_SENTENCE_END) + _SENTENCE_END,
        subject=_SUBJECT_TEMPLATE.format(kind=subject.kind, identity=subject.identity),
        computer=computer,
        time=occurred_at.astimezone(UTC).strftime(_TIME_FORMAT),
    )
    return message if addition is None else message + _SENTENCE_SEPARATOR + addition
