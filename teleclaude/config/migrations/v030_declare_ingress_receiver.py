"""Declare whether the ingress's standalone receiver serves its inbound endpoints (ADR-0148)."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 30
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_COMPUTER = "computer"
_INGRESS_RECEIVER = "ingress_receiver"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Give a computer block that does not say so the daemon-served ingress; a stated choice is kept.

    Documents at this version are refused by releases that predate the setting, so an installation that wrote
    them is not offered a rollback to such a release.
    """
    computer = document.get(_COMPUTER)
    if not isinstance(computer, MutableMapping) or _INGRESS_RECEIVER in computer:
        return
    computer[_INGRESS_RECEIVER] = False
