"""Loader-envelope stripping and first-message title derivation for mirrors.

Classification, command, slug, and title come from the session record
(``teleclaude.mirrors.session_context.get_session_context``); this module owns what the
record cannot supply: recognizing the generated loader-envelope block so it
never appears as a conversation turn, and deriving a first-message title for
a transcript that carries no session record at all.

Bumping :data:`DERIVATION_VERSION` forces a fleet-wide re-derivation through
the reconciliation loop.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from teleclaude.utils.transcript import StructuredMessage

# Bump to force every existing mirror to re-derive through the reconciliation loop.
# Note that a bump re-runs full generation per transcript, summarizer call included,
# so it is not the cheap route for a classification-only change.
DERIVATION_VERSION = 3

_TITLE_MAX_CHARS = 120

_LOADER_ENVELOPE_RE = re.compile(
    r"\ARead\s+\S*?commands/[\w-]+\.md\s+verbatim and follow it exactly as the active instruction set for this session\.\s*"
    r"Treat the following as provided inputs to that instruction set:\s*\n+\s*\S+(?:\s*\n+ADDITIONAL CONTEXT:\s*\n[\s\S]*)?\s*\Z"
)


def is_exact_loader_envelope(text: str) -> bool:
    """Return whether one projected user block is the generated loader envelope."""
    return _LOADER_ENVELOPE_RE.fullmatch(text) is not None


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
