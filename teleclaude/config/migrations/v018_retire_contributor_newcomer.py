"""Retire the contributor and newcomer roles from the global people and the company rosters."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 18
KINDS: Final = frozenset({ConfigSubjectKind.GLOBAL, ConfigSubjectKind.COMPANY})
READ_REQUIRES_REGISTRY: Final = False
_RETIRED_ROLES: Final = frozenset({"contributor", "newcomer"})
_PEOPLE = "people"
_MEMBERS = "members"
_ROLE = "role"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Narrow reach only: a person holding a retired platform role keeps none, and a retired roster role is removed.

    Mapping a retired role to a remaining one would grant authority nobody granted,
    so the person's platform role is dropped and the roster membership is removed.
    """
    people = document.get(_PEOPLE)
    if isinstance(people, list):
        for person in people:
            if isinstance(person, MutableMapping) and person.get(_ROLE) in _RETIRED_ROLES:
                person.pop(_ROLE, None)
    members = document.get(_MEMBERS)
    if isinstance(members, MutableMapping):
        for slug in [
            slug
            for slug, member in members.items()
            if isinstance(member, MutableMapping) and member.get(_ROLE) in _RETIRED_ROLES
        ]:
            members.pop(slug, None)
