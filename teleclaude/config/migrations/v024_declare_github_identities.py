"""Mark the schema that declares person GitHub identities and platform App profiles."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 24
KINDS: Final = frozenset({ConfigSubjectKind.GLOBAL, ConfigSubjectKind.PERSON})
READ_REQUIRES_REGISTRY: Final = False


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Preserve every declaration; absence already means no GitHub account/App configuration.

    Like the inbound-source schema boundary, this step needs no data rewrite:
    empty defaults make the older shape valid. The chain advances the version
    so older installations refuse a document that can carry the new fields.
    Already-declared accounts, Apps, role mappings and key references remain
    unchanged, and the transform creates no identity, credential or binding.
    """
