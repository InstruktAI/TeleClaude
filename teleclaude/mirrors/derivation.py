"""First-message title derivation for mirrors.

Classification, command, slug, and title come from the session record
(``teleclaude.mirrors.session_context.get_session_context``); this module owns what the
record cannot supply: a first-message title for a transcript that carries no
session record at all. The dispatch loader never reaches a mirror as a
conversation turn: canonical projection classifies it as platform text.

Bumping :data:`DERIVATION_VERSION` forces a fleet-wide re-derivation through
the reconciliation loop.
"""

from __future__ import annotations

from collections.abc import Iterable

from teleclaude.utils.transcript import StructuredMessage

# Bump to force every existing mirror to re-derive through the reconciliation loop.
# A bump re-runs full generation per transcript, so it is not the cheap route for a
# classification-only change.
DERIVATION_VERSION = 6

_TITLE_MAX_CHARS = 120


def _truncate_title(text: str) -> str:
    title = text.split("\n", 1)[0].strip()
    if len(title) <= _TITLE_MAX_CHARS:
        return title
    return title[: _TITLE_MAX_CHARS - 3].rstrip() + "..."


def derive_human_title(messages: Iterable[StructuredMessage]) -> str:
    """Derive a human title from the first user message: first line, length-capped."""
    for message in messages:
        if message.role == "user" and message.text.strip():
            return _truncate_title(message.text)
    return ""
