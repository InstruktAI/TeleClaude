"""Effective ``enabled`` of a machine configuration, derived from section declarations.

A section's ``enabled`` flag governs the whole section: when its effective value is
false, every ``enabled`` nested beneath it reads false too. A master-scoped section
(``Scope.MASTER``) reads disabled on a computer that is not the master. An ``enabled``
flag that declares ``governs_section`` false (``tiers.pydantic_field_governs_section``)
is not its section's switch, so nothing beneath it derives from it. The document is
never rewritten; the derivation settles the validated aggregate only.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from teleclaude.config.tiers import Scope, pydantic_field_governs_section, pydantic_field_scope

ENABLED_FIELD = "enabled"


def settle_effective_enabled(aggregate: BaseModel, *, is_master: bool) -> None:
    """Set every ``enabled`` flag of ``aggregate`` to its effective value, in place."""
    for name, field_info in type(aggregate).model_fields.items():
        outside_scope = pydantic_field_scope(field_info) is Scope.MASTER and not is_master
        _settle(getattr(aggregate, name), outside_scope)


def _settle(node: object, disabled: bool) -> None:
    if isinstance(node, BaseModel):
        fields = type(node).model_fields
        if ENABLED_FIELD in fields:
            if disabled:
                setattr(node, ENABLED_FIELD, False)
            governs = pydantic_field_governs_section(fields[ENABLED_FIELD])
            disabled = disabled or (governs and not getattr(node, ENABLED_FIELD))
        for name in fields:
            if name != ENABLED_FIELD:
                _settle(getattr(node, name), disabled)
    elif isinstance(node, Mapping):
        for member in node.values():
            _settle(member, disabled)
    elif isinstance(node, list):
        for member in node:
            _settle(member, disabled)
