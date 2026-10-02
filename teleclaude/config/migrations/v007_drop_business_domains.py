"""Remove the retired business domain declaration from every tier."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 7
KINDS: Final = frozenset(
    {
        ConfigSubjectKind.COMPUTER,
        ConfigSubjectKind.GLOBAL,
        ConfigSubjectKind.PERSON,
        ConfigSubjectKind.COMPANY,
        ConfigSubjectKind.PROJECT,
    }
)
READ_REQUIRES_REGISTRY: Final = False
_BUSINESS = "business"
_DOMAINS = "domains"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Drop `business.domains` and remove an empty business mapping."""
    business = document.get(_BUSINESS)
    if not isinstance(business, MutableMapping):
        return
    business.pop(_DOMAINS, None)
    if not business:
        document.pop(_BUSINESS, None)
