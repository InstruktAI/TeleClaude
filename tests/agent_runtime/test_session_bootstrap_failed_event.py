"""Functional coverage for the session bootstrap-failure event registration."""

from __future__ import annotations

from teleclaude.events import build_default_catalog
from teleclaude.events.envelope import EventLevel

_EVENT_TYPE = "system.session.bootstrap_failed"
_EVENT_DOMAIN = "system"


def test_default_catalog_registers_bootstrap_failed_event() -> None:
    """The built-in event catalog includes the session bootstrap-failure event."""
    schema = build_default_catalog().get(_EVENT_TYPE)

    assert schema is not None
    assert schema.actionable is True
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.default_level is EventLevel.OPERATIONAL
    assert schema.domain == _EVENT_DOMAIN
