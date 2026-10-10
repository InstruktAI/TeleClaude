"""Notification messages: one readable message stating what happened, to which thing, where and when.

A message is composed from the facts an event and its type's declaration state, so every type
reads the same way and a type introduced later needs no change here. A type with no declaration,
such as one relayed from an external system, states what happened by its type name read as words.
The sentences use no markup characters, so they read the same as markdown and as plain text on
every channel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from teleclaude.events.catalog import EventDeclaration
from teleclaude.events.references import EventRef

_SENTENCE_END: Final = "."
_SENTENCE_SEPARATOR: Final = " "
_TYPE_NAME_AS_WORDS: Final = str.maketrans({".": " ", "_": " "})
_MESSAGE_TEMPLATE: Final = "{what} Thing: {subject}. Computer: {computer}. Time: {time}."
_SUBJECT_TEMPLATE: Final = "{kind} {identity}"
_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S UTC"


def _what_happened(event_type: str, declaration: EventDeclaration | None) -> str:
    """The declaration's description, or for an undeclared type its name read as words, as one sentence."""
    if declaration is not None:
        return declaration.description.rstrip(_SENTENCE_END) + _SENTENCE_END
    words = event_type.translate(_TYPE_NAME_AS_WORDS)
    return words[:1].upper() + words[1:] + _SENTENCE_END


def compose_notification_message(
    *,
    event_type: str,
    declaration: EventDeclaration | None,
    subject: EventRef,
    computer: str,
    occurred_at: datetime,
    addition: str | None = None,
) -> str:
    """The message for an event of this type about this subject, as it happened on a computer.

    `declaration` is the catalog's declaration of the type, none for a type the catalog does not declare.
    `addition` is a sentence a consumer appends to its own messages, such as how long a recovered
    thing was broken.
    """
    message = _MESSAGE_TEMPLATE.format(
        what=_what_happened(event_type, declaration),
        subject=_SUBJECT_TEMPLATE.format(kind=subject.kind, identity=subject.identity),
        computer=computer,
        time=occurred_at.astimezone(UTC).strftime(_TIME_FORMAT),
    )
    return message if addition is None else message + _SENTENCE_SEPARATOR + addition
