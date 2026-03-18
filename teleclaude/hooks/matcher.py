"""Property-based matching engine for webhook contracts."""

from __future__ import annotations

import fnmatch

from teleclaude.hooks.webhook_models import Contract, HookEvent, PropertyCriterion


def match_criterion(value: str | int | float | bool | list[str] | None, criterion: PropertyCriterion) -> bool:
    """Evaluate a single value against a property criterion.

    Returns True if the value satisfies the criterion.
    """
    result = True
    if criterion.required:
        if criterion.match is None and criterion.pattern is None:
            # Required presence only — value must exist (not None)
            result = value is not None
        elif value is None:
            result = False
        elif criterion.pattern is not None:
            # Wildcard pattern with dot-segment matching
            result = fnmatch.fnmatch(str(value), criterion.pattern)
        elif criterion.match is not None:
            result = _matches_exact_value(value, criterion.match)
        else:
            result = False
    return result


def _matches_exact_value(
    value: str | int | float | bool | list[str],
    expected: str | list[str],
) -> bool:
    """Return True when a value matches an exact criterion."""
    if isinstance(expected, list):
        return value in expected or str(value) in expected
    return value == expected or str(value) == str(expected)


def match_event(event: HookEvent, contract: Contract) -> bool:
    """Check if an event matches a contract's criteria.

    All required criteria must pass for a match.
    """
    # Check source criterion
    if contract.source_criterion is not None:
        if not match_criterion(event.source, contract.source_criterion):
            return False

    # Check type criterion
    if contract.type_criterion is not None:
        if not match_criterion(event.type, contract.type_criterion):
            return False

    # Check property criteria
    for prop_name, criterion in contract.properties.items():
        value = event.properties.get(prop_name)
        if not match_criterion(value, criterion):
            return False

    return True
