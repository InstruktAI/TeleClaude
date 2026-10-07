"""Mark the version at which a project's maintenance entries may declare `on_demand` and `owed_probe`."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 14
KINDS: Final = frozenset({ConfigSubjectKind.PROJECT})
READ_REQUIRES_REGISTRY: Final = False


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Change nothing: an absent `on_demand` already means the maintenance entry is performed on demand.

    The step exists so a document's version says whether its maintenance entries
    may carry `on_demand` and `owed_probe`; an installation older than this
    version refuses such a document as newer than itself instead of failing on an
    unknown key.
    """
