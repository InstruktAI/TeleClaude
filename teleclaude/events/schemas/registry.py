"""The built-in event declarations, in the order the catalog lists them."""

from __future__ import annotations

from importlib import import_module

from teleclaude.events.catalog import DeclaredEvent

_DECLARATION_MODULES = (
    "teleclaude.events.schemas.system",
    "teleclaude.events.schemas.jobs",
    "teleclaude.events.schemas.maintenance",
    "teleclaude.events.schemas.sdlc",
    "teleclaude.events.schemas.node",
    "teleclaude.events.schemas.deployment",
    "teleclaude.events.schemas.content",
    "teleclaude.events.schemas.notification",
    "teleclaude.events.schemas.schema",
    "teleclaude.events.schemas.signal",
    "teleclaude.events.schemas.session_mirrors",
    "teleclaude.events.schemas.memory",
    "teleclaude.events.schemas.ci",
    "teleclaude.events.schemas.installation",
)


def declared_events() -> tuple[DeclaredEvent, ...]:
    """Return every built-in declaration, in module order."""
    declared: tuple[DeclaredEvent, ...] = ()
    for module_name in _DECLARATION_MODULES:
        declared += import_module(module_name).DECLARED
    return declared
