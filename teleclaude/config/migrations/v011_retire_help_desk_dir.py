"""Retire the machine-wide help-desk directory from the computer document."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 11
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_COMPUTER = "computer"
_HELP_DESK_DIR = "help_desk_dir"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Drop `computer.help_desk_dir`; its value is dropped, not moved.

    A help desk's folder follows from its kind and its home, so no machine-wide
    desk location remains: a non-default value on some machine loses its
    meaning by design.
    """
    computer = document.get(_COMPUTER)
    if isinstance(computer, MutableMapping):
        computer.pop(_HELP_DESK_DIR, None)
