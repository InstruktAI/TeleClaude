"""A person's notification interests: what they select, where they start and when they are unusable.

Interests are grouped by category — ``teleclaude`` for the platform's own events,
or a published domain's name. A pattern is written relative to its category and
read by the platform's one type-pattern matcher. This module owns the usability
rule, so selection and validation read the same verdict and cannot disagree.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, TypedDict

from teleclaude.config.schema import PLATFORM_EVENT_CATEGORY, NotificationCategory
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.events.type_pattern import TypePattern, TypePatternError

PLATFORM_CATEGORY: Final = PLATFORM_EVENT_CATEGORY
_NAMESPACE_SEPARATOR: Final = "."
_ANY_PATTERN: Final = "*"
_FAMILY_PATTERN_SUFFIX: Final = ".*"
_SLUG_FIELD: Final = "slug"
_NOTIFICATIONS_FIELD: Final = "notifications"
_CATEGORY_FAULT_TEXT: Final = "notifications.{category}: {reason}"
_PATTERN_FAULT_TEXT: Final = "notifications.{category}.events {pattern!r}: {reason}"

#: Interests a new person starts with, by role; a role absent here starts with none.
STARTING_INTERESTS_BY_ROLE: Final[Mapping[str, Mapping[str, NotificationCategory]]] = {
    HUMAN_ROLE_ADMIN: {
        PLATFORM_CATEGORY: NotificationCategory(enabled=True, events=["job.*", "deployment.*"]),
    },
}


class InterestFaultReason(StrEnum):
    """Why an interest cannot be used."""

    UNKNOWN_CATEGORY = "the category is neither 'teleclaude' nor a published domain"
    REFUSED_PATTERN = "the type-pattern matcher refuses the pattern"
    PLATFORM_PATTERN_NOT_FAMILY = (
        "a 'teleclaude' pattern must be '*' or end in '.*', since platform events form lifecycle families"
    )


@dataclass(frozen=True)
class InterestFault:
    """One unusable interest: the category, the pattern when the fault is the pattern's, and why."""

    category: str
    pattern: str | None
    reason: InterestFaultReason

    def describe(self) -> str:
        """Name the interest and the reason it cannot be used."""
        if self.pattern is None:
            return _CATEGORY_FAULT_TEXT.format(category=self.category, reason=self.reason)
        return _PATTERN_FAULT_TEXT.format(category=self.category, pattern=self.pattern, reason=self.reason)


class NotificationCategoryDocument(TypedDict):
    """A category as written in a person's configuration document."""

    enabled: bool
    events: list[str]


def starting_notifications(role: str) -> dict[str, NotificationCategoryDocument]:
    """The interests a new person of this role is created with, as a configuration document value."""
    return {
        category: NotificationCategoryDocument(enabled=entry.enabled, events=list(entry.events))
        for category, entry in STARTING_INTERESTS_BY_ROLE.get(role, {}).items()
    }


def new_person_document(slug: str, role: str | None) -> Mapping[str, object]:
    """The declaration a new person is written with: their slug and, for a role that has them, starting interests."""
    starting = starting_notifications(role) if role is not None else {}
    if not starting:
        return {_SLUG_FIELD: slug}
    return {_SLUG_FIELD: slug, _NOTIFICATIONS_FIELD: starting}


def _category_recognized(category: str, published_domains: Collection[str]) -> bool:
    return category == PLATFORM_CATEGORY or category in published_domains


def _pattern_fault(category: str, pattern: str) -> InterestFaultReason | None:
    try:
        TypePattern(pattern)
    except TypePatternError:
        return InterestFaultReason.REFUSED_PATTERN
    if category == PLATFORM_CATEGORY and pattern != _ANY_PATTERN and not pattern.endswith(_FAMILY_PATTERN_SUFFIX):
        return InterestFaultReason.PLATFORM_PATTERN_NOT_FAMILY
    return None


def interest_faults(
    notifications: Mapping[str, NotificationCategory],
    published_domains: Collection[str],
) -> list[InterestFault]:
    """Every interest that cannot be used; an interest that merely overlaps another is valid and absent here."""
    faults: list[InterestFault] = []
    for category, entry in notifications.items():
        if not _category_recognized(category, published_domains):
            faults.append(InterestFault(category, None, InterestFaultReason.UNKNOWN_CATEGORY))
            continue
        for pattern in entry.events:
            reason = _pattern_fault(category, pattern)
            if reason is not None:
                faults.append(InterestFault(category, pattern, reason))
    return faults


def selects(
    notifications: Mapping[str, NotificationCategory],
    event_type: str,
    published_domains: Collection[str],
) -> bool:
    """Whether an event type lies in a switched-on category and matches one of its usable patterns.

    An interest that `interest_faults` reports selects nothing; the others keep matching.
    Patterns are read relative to the category's namespace, so a pattern cannot reach
    outside it. Any match suffices, so overlapping or repeated patterns mean one.
    """
    for category, entry in notifications.items():
        if not entry.enabled or not _category_recognized(category, published_domains):
            continue
        namespace = category + _NAMESPACE_SEPARATOR
        if not event_type.startswith(namespace):
            continue
        relative_type = event_type.removeprefix(namespace)
        if any(
            _pattern_fault(category, pattern) is None and TypePattern(pattern).matches(relative_type)
            for pattern in entry.events
        ):
            return True
    return False
