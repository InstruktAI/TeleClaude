"""Effective ``enabled`` of a machine configuration, derived from section declarations.

A section's ``enabled`` flag governs the whole section: when its effective value is
false, every ``enabled`` nested beneath it reads false too. A master-scoped path
(``Scope.MASTER``) reads disabled on a computer that is not the master. An ``enabled``
flag that declares ``governs_section`` false (``tiers.pydantic_field_governs_section``)
is not its section's switch, so nothing beneath it derives from it. The document is
never rewritten; the derivation settles the validated aggregate only.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from teleclaude.config.tiers import Scope, effective_scope, pydantic_field_governs_section, pydantic_field_scope

ENABLED_FIELD = "enabled"


def settle_effective_enabled(aggregate: BaseModel, *, is_master: bool) -> None:
    """Set every ``enabled`` flag of ``aggregate`` to its effective value, in place."""
    for name, field_info in type(aggregate).model_fields.items():
        scope = effective_scope(pydantic_field_scope(field_info), Scope.LOCAL)
        _settle(getattr(aggregate, name), scope is Scope.MASTER and not is_master, scope, is_master)


def _settle(node: object, disabled: bool, inherited_scope: Scope, is_master: bool) -> None:
    if isinstance(node, BaseModel):
        fields = type(node).model_fields
        if ENABLED_FIELD in fields:
            enabled_scope = effective_scope(pydantic_field_scope(fields[ENABLED_FIELD]), inherited_scope)
            disabled_enabled = disabled or (enabled_scope is Scope.MASTER and not is_master)
            if disabled_enabled:
                setattr(node, ENABLED_FIELD, False)
            governs = pydantic_field_governs_section(fields[ENABLED_FIELD])
            disabled = disabled or (governs and not getattr(node, ENABLED_FIELD))
        for name in fields:
            if name != ENABLED_FIELD:
                field_scope = effective_scope(pydantic_field_scope(fields[name]), inherited_scope)
                outside_scope = field_scope is Scope.MASTER and not is_master
                _settle(getattr(node, name), disabled or outside_scope, field_scope, is_master)
    elif isinstance(node, Mapping):
        for member in node.values():
            _settle(member, disabled, inherited_scope, is_master)
    elif isinstance(node, list):
        for member in node:
            _settle(member, disabled, inherited_scope, is_master)
