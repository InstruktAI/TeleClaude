"""Mark the version at which a global, company or project document may declare a help desk."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 10
KINDS: Final = frozenset({ConfigSubjectKind.GLOBAL, ConfigSubjectKind.COMPANY, ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = False


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Change nothing: an absent `help_desk` block already means the home keeps no help desk.

    The step exists so a document's version says whether it may carry the block;
    an installation older than this version refuses such a document as newer
    than itself instead of meeting an unknown key.
    """
