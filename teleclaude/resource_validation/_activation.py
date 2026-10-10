"""Procedure activation declarations: the event subscriptions, the home kind they answer, and the self-selection trigger."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from teleclaude.docs_subscriptions import IndexKey, SubscriptionAttendance, SubscriptionHomeKind, SubscriptionIdentity
from teleclaude.events.type_pattern import TypePattern, TypePatternError
from teleclaude.resource_validation._models import _error
from teleclaude.snippet_scope import SnippetScope
from teleclaude.snippet_validation import SnippetClassification

_SUBSCRIPTION_HOME_FIELD = "subscription_home"
_UNCLASSIFIED_TIER = "unclassified"
_SUBSCRIPTION_TIER_FINDING = "snippet_subscriptions_invalid_tier"
_SUBSCRIPTION_PATTERN_FINDING = "snippet_subscriptions_invalid_pattern"
_SUBSCRIPTION_HOME_REQUIRED_FINDING = "snippet_subscriptions_home_required"
_SUBSCRIPTION_HOME_UNEXPECTED_FINDING = "snippet_subscriptions_home_unexpected"
_SUBSCRIPTION_HOME_VALUE_FINDING = "snippet_subscriptions_home_invalid_value"
_SUBSCRIPTION_HOME_TIER_FINDING = "snippet_subscriptions_home_invalid_tier"
_SUBSCRIPTION_IDENTITY_UNEXPECTED_FINDING = "snippet_subscriptions_identity_unexpected"
_SUBSCRIPTION_IDENTITY_VALUE_FINDING = "snippet_subscriptions_identity_invalid_value"
_SUBSCRIPTION_ATTENDANCE_UNEXPECTED_FINDING = "snippet_subscriptions_attendance_unexpected"
_SUBSCRIPTION_ATTENDANCE_VALUE_FINDING = "snippet_subscriptions_attendance_invalid_value"
#: The tiers where a procedure's subscriptions are routed.
_SUBSCRIPTION_ROUTED_SCOPES = frozenset({SnippetScope.GLOBAL, SnippetScope.COMPANY, SnippetScope.PERSON})
#: The one home kind a procedure published in a home's own tier can answer.
_TIER_SUBSCRIPTION_HOME_KIND = {
    SnippetScope.COMPANY: SubscriptionHomeKind.COMPANY,
    SnippetScope.PERSON: SubscriptionHomeKind.PERSON,
}


def validate_activation_trigger(path: Path, meta: Mapping[str, object], *, snippet_type: str | None) -> None:
    activation_trigger = meta.get("activation_trigger")
    if activation_trigger is None:
        return
    if snippet_type != "procedure":
        _error("snippet_activation_trigger_invalid_type", path=str(path))
        return
    if not isinstance(activation_trigger, str):
        _error("snippet_activation_trigger_invalid_value", path=str(path))
        return
    if not activation_trigger.strip():
        _error("snippet_activation_trigger_empty", path=str(path))


def _subscription_tier_name(classification: SnippetClassification | None) -> str:
    return classification.scope.value if classification is not None else _UNCLASSIFIED_TIER


def _validate_subscription_pattern(path: Path, pattern: str) -> None:
    try:
        TypePattern(pattern)
    except TypePatternError:
        _error(_SUBSCRIPTION_PATTERN_FINDING, path=str(path), pattern=pattern)


def _validate_subscription_home(
    path: Path, declared_home: object, classification: SnippetClassification | None
) -> None:
    if declared_home is None:
        _error(_SUBSCRIPTION_HOME_REQUIRED_FINDING, path=str(path))
        return
    try:
        home_kind = SubscriptionHomeKind(str(declared_home))
    except ValueError:
        _error(_SUBSCRIPTION_HOME_VALUE_FINDING, path=str(path), value=str(declared_home))
        return
    tier_home_kind = _TIER_SUBSCRIPTION_HOME_KIND.get(classification.scope) if classification is not None else None
    if tier_home_kind is not None and home_kind is not tier_home_kind:
        _error(
            _SUBSCRIPTION_HOME_TIER_FINDING,
            path=str(path),
            tier=_subscription_tier_name(classification),
            value=home_kind.value,
        )


def _validate_subscription_identity(path: Path, declared_identity: object) -> None:
    if declared_identity is None:
        return
    try:
        SubscriptionIdentity(str(declared_identity))
    except ValueError:
        _error(_SUBSCRIPTION_IDENTITY_VALUE_FINDING, path=str(path), value=str(declared_identity))


def _validate_subscription_attendance(path: Path, declared_attendance: object) -> None:
    if declared_attendance is None:
        return
    try:
        SubscriptionAttendance(str(declared_attendance))
    except ValueError:
        _error(_SUBSCRIPTION_ATTENDANCE_VALUE_FINDING, path=str(path), value=str(declared_attendance))


def validate_subscriptions(
    path: Path,
    meta: Mapping[str, object],
    classification: SnippetClassification | None,
    *,
    snippet_type: str | None,
) -> None:
    subscriptions = meta.get("subscriptions")
    declared_home = meta.get(_SUBSCRIPTION_HOME_FIELD)
    declared_identity = meta.get(IndexKey.SUBSCRIPTION_IDENTITY)
    declared_attendance = meta.get(IndexKey.SUBSCRIPTION_ATTENDANCE)
    if subscriptions is None:
        if declared_home is not None:
            _error(_SUBSCRIPTION_HOME_UNEXPECTED_FINDING, path=str(path))
        if declared_identity is not None:
            _error(_SUBSCRIPTION_IDENTITY_UNEXPECTED_FINDING, path=str(path))
        if declared_attendance is not None:
            _error(_SUBSCRIPTION_ATTENDANCE_UNEXPECTED_FINDING, path=str(path))
        return
    if snippet_type != "procedure":
        _error("snippet_subscriptions_invalid_type", path=str(path))
        return
    if (
        not isinstance(subscriptions, list)
        or not subscriptions
        or not all(isinstance(item, str) and item.strip() for item in subscriptions)
    ):
        _error("snippet_subscriptions_invalid_value", path=str(path))
        return
    for pattern in subscriptions:
        _validate_subscription_pattern(path, pattern)
    if classification is None or classification.scope not in _SUBSCRIPTION_ROUTED_SCOPES:
        _error(_SUBSCRIPTION_TIER_FINDING, path=str(path), tier=_subscription_tier_name(classification))
    _validate_subscription_home(path, declared_home, classification)
    _validate_subscription_identity(path, declared_identity)
    _validate_subscription_attendance(path, declared_attendance)


def validate_activation_mode_exclusivity(path: Path, meta: Mapping[str, object]) -> None:
    """A procedure declares event activation or the self-selection trigger, never both.

    Kept independent of either individual validator's early returns, so a
    shape defect in one field never masks the exclusivity finding.
    """
    if meta.get("activation_trigger") is not None and meta.get("subscriptions") is not None:
        _error("snippet_activation_mode_conflict", path=str(path))
