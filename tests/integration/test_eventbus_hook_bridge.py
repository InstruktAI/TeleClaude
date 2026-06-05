"""Spec-anchored tests for the eventbus-hook-bridge feature.

This is the reference shape for the suite: each test binds exactly one scenario
from a feature spec via ``@pytest.mark.spec(<spec_id>, <scenario_id>)``. The
human-authored Gherkin in the spec is the contract (the assertions); the test
body only realizes the scenario's Given/When/Then against the real component.
An agent never invents what to assert — it binds an unbound scenario.

Spec: docs/project/spec/feature/integration/eventbus-hook-bridge.md
"""

from __future__ import annotations

import pytest

from teleclaude.core.events import SessionLifecycleContext, TeleClaudeEvents
from teleclaude.hooks.bridge import EventBusBridge
from teleclaude.hooks.webhook_models import HookEvent

pytestmark = pytest.mark.integration

_SPEC = "project/spec/feature/integration/eventbus-hook-bridge"


class _CapturingDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[HookEvent] = []

    async def dispatch(self, event: HookEvent) -> None:
        self.dispatched.append(event)


class _RaisingDispatcher:
    async def dispatch(self, _event: HookEvent) -> None:
        raise RuntimeError("matcher fault")


@pytest.mark.spec(_SPEC, "UC-EB1")
async def test_session_lifecycle_event_becomes_session_hookevent(snapshot) -> None:
    # Given a SESSION_STARTED event with a SessionLifecycleContext,
    # When the bridge handles it,
    # Then it emits a system-sourced session.started HookEvent carrying the session_id.
    # The emitted shape is the contract; snapshot it per the string-assertion paradigm.
    dispatcher = _CapturingDispatcher()
    bridge = EventBusBridge(dispatcher)  # type: ignore[arg-type]

    await bridge._handle(TeleClaudeEvents.SESSION_STARTED, SessionLifecycleContext(session_id="sess-1"))

    [event] = dispatcher.dispatched
    assert {"source": event.source, "type": event.type, "properties": event.properties} == snapshot


@pytest.mark.spec(_SPEC, "UC-EB5")
async def test_dispatch_failure_is_logged_not_raised() -> None:
    # Given a dispatcher that raises,
    # When the bridge handles an event,
    # Then the exception is swallowed (logged) and never escapes _handle.
    bridge = EventBusBridge(_RaisingDispatcher())  # type: ignore[arg-type]

    await bridge._handle(TeleClaudeEvents.SESSION_STARTED, SessionLifecycleContext(session_id="s1"))
