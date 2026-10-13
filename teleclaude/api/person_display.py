"""Person display facts composed onto the rows UI clients present.

Identity resolves the person a row belongs to and config declares the person's
chip color. This module composes both onto session and todo rows without
changing what those projections mean, so a client renders owner chips from the
row it received and never opens the person registry.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from teleclaude.api_models import SessionDTO, TodoDTO
from teleclaude.api_models_identity import ChipColorPairDTO, OwnershipSurfaceDTO, PersonChipDTO
from teleclaude.config.schema import PersonChipColorPair
from teleclaude.core.identity import derive_initials, get_identity_resolver
from teleclaude.types.creation_record import HUMAN_ROOT_PREFIX, Lineage

_PERSON_CHIP_FIELD: Final = "person_chip"


def ownership_surface() -> OwnershipSurfaceDTO:
    """Whether owner chips and the per-person filter apply: only when several people are registered."""
    return OwnershipSurfaceDTO(enabled=get_identity_resolver().is_multi_user)


def _pair_dto(pair: PersonChipColorPair) -> ChipColorPairDTO:
    return ChipColorPairDTO(light=pair.light, dark=pair.dark)


def _chip_for_email(email: str | None) -> PersonChipDTO | None:
    """The chip of the registered person owning an email, or None when there is none to show."""
    resolver = get_identity_resolver()
    if not email or not resolver.is_multi_user:
        return None
    context = resolver.resolve_by_email(email)
    initials = derive_initials(context.person_name) if context.person_name else None
    if not initials:
        return None
    color = context.chip_color
    if color is None:
        return PersonChipDTO(initials=initials)
    return PersonChipDTO(initials=initials, background=_pair_dto(color.background), text=_pair_dto(color.text))


def _chip_for_lineage_root(root: str | None) -> PersonChipDTO | None:
    """The chip of the person a human-rooted lineage names; system roots name no person."""
    if root is None or not root.startswith(HUMAN_ROOT_PREFIX):
        return None
    return _chip_for_email(root.removeprefix(HUMAN_ROOT_PREFIX).strip())


def with_person_chips_on_todos(todos: Iterable[TodoDTO]) -> list[TodoDTO]:
    """Todo rows carrying the chip of the person their lineage names."""
    return [
        todo.model_copy(update={_PERSON_CHIP_FIELD: _chip_for_lineage_root(Lineage.root_of(todo.lineage))})
        for todo in todos
    ]


def with_person_chips_on_sessions(sessions: Iterable[SessionDTO]) -> list[SessionDTO]:
    """Session rows carrying the chip of the person owning them: by principal, else by human email."""
    return [
        session.model_copy(
            update={
                _PERSON_CHIP_FIELD: _chip_for_email(session.human_email)
                if session.principal is None
                else _chip_for_lineage_root(session.principal)
            }
        )
        for session in sessions
    ]
