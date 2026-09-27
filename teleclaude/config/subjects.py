"""Domain vocabulary for configuration subjects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from teleclaude.slug import validate_slug


class ConfigSubjectKind(StrEnum):
    """The addressable configuration subjects."""

    COMPUTER = "computer"
    GLOBAL = "global"
    PERSON = "person"
    COMPANY = "company"
    PROJECT = "project"


class SubjectSource(StrEnum):
    """Authority behind a configuration subject used to interpret a document."""

    REGISTRY = "registry"
    DECLARATION = "declaration"


_SINGLETON_KINDS = frozenset({ConfigSubjectKind.COMPUTER, ConfigSubjectKind.GLOBAL})
_DECLARATION_INSTANCE_ERROR = "A declaration-only subject cannot infer an instance"


@dataclass(frozen=True)
class SubjectRef:
    """One addressed configuration subject, optionally carrying its registry instance.

    The config resource API permits a missing instance only for ``init_subject``;
    the migration read resolver also permits it for a declaration-only subject,
    which cannot carry registry standing or infer a person/company slug.
    """

    kind: ConfigSubjectKind
    instance: str | None = None
    source: SubjectSource = SubjectSource.REGISTRY

    def __post_init__(self) -> None:
        if self.kind in _SINGLETON_KINDS:
            if self.instance is not None:
                raise ValueError(f"{self.kind} is a singleton subject and takes no instance")
        elif self.instance is not None:
            validate_slug(self.instance)
        if self.source is SubjectSource.DECLARATION and self.instance is not None:
            raise ValueError(_DECLARATION_INSTANCE_ERROR)
