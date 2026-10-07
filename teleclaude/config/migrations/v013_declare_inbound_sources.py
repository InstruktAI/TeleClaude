"""Mark the version at which a home's `hooks.inbound` keys are protocols that declare inbound sources."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 13
KINDS: Final = frozenset(
    {
        ConfigSubjectKind.GLOBAL,
        ConfigSubjectKind.COMPANY,
        ConfigSubjectKind.PERSON,
        ConfigSubjectKind.PROJECT,
    }
)
READ_REQUIRES_REGISTRY: Final = False


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Change nothing: an absent `hooks.inbound` block already means the home declares no inbound source.

    The step exists so a document's version says whether its `hooks.inbound` keys
    name protocols; an installation older than this version refuses such a
    document as newer than itself instead of reading a protocol key as a free
    source name.
    """
