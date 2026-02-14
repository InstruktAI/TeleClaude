"""Property-based matching engine for webhook contracts."""

from __future__ import annotations

import fnmatch

from teleclaude.hooks.webhook_models import Contract, HookEvent, PropertyCriterion


def match_criterion(value: str | int | float | bool | list[str] | None, criterion: PropertyCriterion) -> bool:
    """Evaluate a single value against a property criterion.

    Returns True if the value satisfies the criterion.
    """
    if not criterion.required:
        return True

    if criterion.match is None and criterion.pattern is None:
        # Required presence only — value must exist (not None)
        return value is not None

    if criterion.pattern is not None:
        if value is None:
            return False
        # Wildcard pattern with dot-segment matching
        return fnmatch.fnmatch(str(value), criterion.pattern)

    if criterion.match is not None:
        if value is None:
            return False
        if isinstance(criterion.match, list):
            return value in criterion.match or str(value) in criterion.match
        return value == criterion.match or str(value) == str(criterion.match)

    return False


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
