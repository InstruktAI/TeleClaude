"""Domain vocabulary for configuration subjects, independent of config runtime loading."""

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
_SINGLETON_INSTANCE_ERROR = "{kind} is a singleton subject and takes no instance"
_DECLARATION_INSTANCE_ERROR = "A declaration-only subject cannot infer an instance"
_SUBJECT_TOKEN_SEPARATOR = ":"
_MALFORMED_SUBJECT_TOKEN = "Recorded configuration subject must be <kind>:<instance>"
_NON_REGISTRY_SUBJECT_TOKEN = "Recorded configuration subject must name a registry subject"
_SUBJECT_TOKEN_INSTANCE_REQUIRED = "Recorded configuration subject requires an instance"


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
                raise ValueError(_SINGLETON_INSTANCE_ERROR.format(kind=self.kind))
        elif self.instance is not None:
            validate_slug(self.instance)
        if self.source is SubjectSource.DECLARATION and self.instance is not None:
            raise ValueError(_DECLARATION_INSTANCE_ERROR)

    def to_token(self) -> str:
        """Render this registry subject as its persisted token."""
        if self.source is not SubjectSource.REGISTRY:
            raise ValueError(_NON_REGISTRY_SUBJECT_TOKEN)
        if self.instance is None or self.kind in _SINGLETON_KINDS:
            raise ValueError(_SUBJECT_TOKEN_INSTANCE_REQUIRED)
        return _SUBJECT_TOKEN_SEPARATOR.join((self.kind.value, self.instance))

    @classmethod
    def from_token(cls, token: str) -> SubjectRef:
        """Parse a persisted registry-subject token."""
        kind_value, separator, instance = token.partition(_SUBJECT_TOKEN_SEPARATOR)
        if not separator or not kind_value or not instance:
            raise ValueError(_MALFORMED_SUBJECT_TOKEN)
        try:
            kind = ConfigSubjectKind(kind_value)
        except ValueError as exc:
            raise ValueError(_MALFORMED_SUBJECT_TOKEN) from exc
        if kind in _SINGLETON_KINDS:
            raise ValueError(_SUBJECT_TOKEN_INSTANCE_REQUIRED)
        return cls(kind=kind, instance=instance)
