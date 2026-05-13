"""Characterization tests, regression guards, and behavioral specs for
teleclaude.core.event_bus.

- ``TestEventBus`` characterizes the Redis-backed public API behavior that
  replaces the original in-process implementation.
- ``TestEventBusApiRegressionGuards`` provides non-spec coverage of the
  public API surface (signatures, module-level singleton). Survives the
  migration as ordinary regression coverage; not in the spec suite.
- ``TestEventBusRedisMigrationSpecs`` pins the behavioral contract of the
  Redis-Streams-backed adapter.
- ``TestEventBusContextRoundTripSpecs`` pins typed-round-trip behavior for
  every ``EventContext`` union member declared in
  ``teleclaude/core/events.py``.
- ``TestEventBusCallSiteSpecs`` pins emit/subscribe behavior for
  existing call-site patterns from the migration scope.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core import event_bus as event_bus_module
from teleclaude.core.event_bus import EventBus
from teleclaude.core.events import (
    AgentActivityEvent,
    AgentAvailabilityContext,
    AgentEventContext,
    AgentHookEventType,
    AgentRestartDispatchedPayload,
    AgentSessionStartPayload,
    AgentStopActivityEvent,
    ErrorEventContext,
    JobCompletedPayload,
    JobFailedPayload,
    JobStartedPayload,
    MessageEventContext,
    NotificationClaimedPayload,
    NotificationResolvedPayload,
    OperationCompletedContext,
    SessionCloseCompletedPayload,
    SessionEscalatedPayload,
    SessionLifecycleContext,
    SessionStatusContext,
    SessionUpdatedContext,
    SystemCommandContext,
    ToolUseActivityEvent,
    UserPromptSubmitActivityEvent,
)
from teleclaude.events.envelope import EventEnvelope, EventVisibility
from teleclaude.events.processor import (
    CONSUMER_GROUP as CARTRIDGE_CONSUMER_GROUP,
)
from teleclaude.events.processor import (
    STREAM_NAME as CARTRIDGE_STREAM_NAME,
)


def _make_redis_fake() -> MagicMock:
    """Build a Redis client fake matching the project's tests/unit/events pattern."""
    redis = MagicMock()
    redis.xadd = AsyncMock(return_value=b"1-0")
    redis.xack = AsyncMock()
    redis.xgroup_create = AsyncMock()
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xautoclaim = AsyncMock(return_value=(b"0-0", [], []))
    redis.xpending = AsyncMock(return_value={"pending": 0, "min": None, "max": None, "consumers": []})
    redis.xpending_range = AsyncMock(return_value=[])
    redis.xclaim = AsyncMock(return_value=[])
    return redis


def _captured_xadd_calls(redis_fake: MagicMock) -> list[tuple[str, dict[str, str]]]:
    """Return [(stream_name, payload_dict), ...] captured by redis_fake.xadd."""
    out: list[tuple[str, dict[str, str]]] = []
    for call in redis_fake.xadd.await_args_list:
        args, kwargs = call.args, call.kwargs
        stream = args[0] if args else kwargs.get("name", "")
        data = args[1] if len(args) > 1 else kwargs.get("fields", {})
        out.append((stream, data))
    return out


def _captured_xgroup_create_calls(redis_fake: MagicMock) -> list[tuple[str, str]]:
    """Return [(stream_name, group_name), ...] captured by redis_fake.xgroup_create."""
    out: list[tuple[str, str]] = []
    for call in redis_fake.xgroup_create.await_args_list:
        args, kwargs = call.args, call.kwargs
        stream = args[0] if args else kwargs.get("name", "")
        group = args[1] if len(args) > 1 else kwargs.get("groupname", "")
        out.append((stream, group))
    return out


async def _start_and_immediately_shutdown(bus: EventBus) -> None:
    """Run ``bus.start`` with an already-set shutdown event so consumer-group
    setup runs but the read loop does not block."""
    shutdown = asyncio.Event()
    shutdown.set()
    await bus.start(shutdown)


def _contract_field(contract: object, field_name: str) -> object | None:
    """Read a structured implementation-boundary contract from a mapping or object."""
    if isinstance(contract, Mapping):
        return contract.get(field_name)
    return getattr(contract, field_name, None)


def _session_started_envelope(session_id: str = "sess-1") -> EventEnvelope:
    """Build a typed internal session_started envelope for consumer-path specs."""
    return EventEnvelope(
        event="internal.session_started",
        source="test",
        level=2,
        payload={"context_type": "SessionLifecycleContext", "session_id": session_id},
    )


def _agent_event_envelope() -> EventEnvelope:
    """Build a typed internal agent_event envelope for fan-out specs."""
    return EventEnvelope(
        event="internal.agent_event",
        source="test",
        level=2,
        payload={"context_type": "AgentAvailabilityContext", "agent": "claude", "available": True},
    )


class TestEventBus:
    @pytest.mark.unit
    async def test_emit_publishes_event_to_internal_stream(self) -> None:
        bus = EventBus()
        redis = _make_redis_fake()
        bus.configure(role="daemon", redis_client=redis)
        await bus.emit("agent_event", AgentAvailabilityContext(agent="claude", available=True))
        calls = _captured_xadd_calls(redis)
        assert calls

    @pytest.mark.unit
    async def test_emit_without_local_handler_still_publishes(self) -> None:
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("agent_event", AgentAvailabilityContext(agent="claude", available=True))
        calls = _captured_xadd_calls(redis)
        assert calls

    @pytest.mark.unit
    def test_clear_removes_all_handlers(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        async def handler(event: str, context: Any) -> None:
            del context
            calls.append(event)

        bus.subscribe("agent_event", handler)
        bus.clear()
        assert bus._handlers.get("agent_event") is None

    @pytest.mark.unit
    async def test_multiple_handlers_for_same_event_are_registered(self) -> None:
        bus = EventBus()

        async def h1(event: str, context: Any) -> None:
            del event, context

        async def h2(event: str, context: Any) -> None:
            del event, context

        bus.subscribe("agent_event", h1)
        bus.subscribe("agent_event", h2)
        assert len(bus._handlers["agent_event"]) == 2


class TestEventBusApiRegressionGuards:
    """Regression coverage for the public API surface across the migration.

    These tests are deliberately not in the migration spec suite. They
    are ordinary characterization plus contract preservation. A failure here
    indicates either the migration broke the public API (regression) or a
    pre-existing call site has drifted.
    """

    @pytest.mark.unit
    def test_public_api_signatures_match_existing_call_site_shape(self) -> None:
        """``subscribe``, ``emit``, and ``clear`` keep their existing call shape.

        Catches a regression where a future edit drops `event`/`context` or
        adds required positional args without defaults. Existing call sites
        across `daemon_session.py`, `core/operations/service.py`, and others
        rely on the unchanged shape.
        """
        subscribe_sig = inspect.signature(EventBus.subscribe)
        emit_sig = inspect.signature(EventBus.emit)
        clear_sig = inspect.signature(EventBus.clear)
        assert list(subscribe_sig.parameters)[1:] == ["event", "handler"]
        # Positional surface preserved: callers passing (event, context) keep working.
        # The visibility-aware dispatch contract added a keyword-only `visibility`
        # parameter with a default so existing call sites are unaffected.
        emit_params = emit_sig.parameters
        emit_positional = [
            name
            for name, p in emit_params.items()
            if name != "self" and p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)
        ]
        assert emit_positional == ["event", "context"]
        visibility_param = emit_params.get("visibility")
        assert visibility_param is not None
        assert visibility_param.kind == visibility_param.KEYWORD_ONLY
        assert visibility_param.default is not inspect.Parameter.empty
        assert list(clear_sig.parameters) == ["self"]

    @pytest.mark.unit
    def test_module_level_singleton_is_importable(self) -> None:
        """The module-level ``event_bus`` singleton is importable.

        Catches a regression where the singleton is removed or renamed,
        breaking every existing call site that imports it.
        """
        assert hasattr(event_bus_module, "event_bus")
        bus = event_bus_module.event_bus
        assert callable(bus.subscribe)
        assert callable(bus.emit)
        assert callable(bus.clear)


class TestEventBusRedisMigrationSpecs:
    """Behavioral contract for the Redis-Streams-backed ``EventBus`` adapter.

    These specs pin public-API and on-the-wire behavior. The required public seam is the
    minimum contract pinned in ``requirements.md``: ``EventBus(role,
    redis_client)``, async ``start(shutdown_event)``, and the existing
    ``subscribe``/``emit``/``clear`` API.
    """

    @pytest.mark.unit
    async def test_internal_event_stream_distinct_from_cartridge_stream(self) -> None:
        """Internal-event emit publishes to a stream name != cartridge ``STREAM_NAME``.

        Catches a regression where internal events accidentally collide with
        the cartridge pipeline's ``teleclaude:events`` stream.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("session_started", SessionLifecycleContext(session_id="sess-1"))
        calls = _captured_xadd_calls(redis)
        assert calls, "emit must produce at least one XADD call"
        for stream_name, _ in calls:
            assert stream_name != CARTRIDGE_STREAM_NAME

    @pytest.mark.unit
    async def test_internal_event_uses_distinct_event_namespace(self) -> None:
        """Envelope ``event`` field for an internal event is distinct from cartridge events.

        Catches a regression where the migration reuses cartridge event
        identifiers (e.g. raw ``EventType`` values) verbatim on the wire.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("session_started", SessionLifecycleContext(session_id="sess-1"))
        calls = _captured_xadd_calls(redis)
        assert calls, "emit must produce at least one XADD call"
        for _, payload in calls:
            envelope_event = payload.get("event", "")
            assert envelope_event != "session_started"

    @pytest.mark.unit
    async def test_internal_event_namespace_does_not_collide_with_cartridge_vocabulary(self) -> None:
        """Internal-event envelope ``event`` does not match any cartridge event identifier.

        Catches a regression where the migration's namespace prefix collides
        with cartridge event vocabulary, routing internal traffic into
        cartridge consumer code paths.
        """
        cartridge_event_identifiers = {
            "todo_dumped",
            "agent_restart_dispatched",
            "session_close_completed",
            "session_escalated",
            "todo_finalize_ready",
            "system.event.dead_lettered",
        }
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("session_started", SessionLifecycleContext(session_id="sess-1"))
        await bus.emit("agent_event", AgentAvailabilityContext(agent="claude", available=True))
        calls = _captured_xadd_calls(redis)
        assert calls
        for _, payload in calls:
            envelope_event = payload.get("event", "")
            assert envelope_event not in cartridge_event_identifiers, (
                f"Internal event {envelope_event!r} collides with the cartridge vocabulary"
            )

    @pytest.mark.unit
    async def test_internal_consumer_group_distinct_from_cartridge_consumer_group(self) -> None:
        """Internal-event consumer group identity != cartridge ``CONSUMER_GROUP``.

        Catches a regression where the EventBus creates a consumer group
        on the cartridge pipeline's group name, mixing cartridge and
        internal delivery cursors.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await _start_and_immediately_shutdown(bus)
        groups = _captured_xgroup_create_calls(redis)
        assert groups, "start() must register a consumer group via xgroup_create"
        for _stream, group_name in groups:
            assert group_name != CARTRIDGE_CONSUMER_GROUP, (
                f"Internal-event group {group_name!r} collides with cartridge group {CARTRIDGE_CONSUMER_GROUP!r}"
            )

    @pytest.mark.unit
    def test_module_exposes_internal_event_contract_metadata(self) -> None:
        """Module exposes structured stream/group/namespace/outage contract metadata.

        Catches a regression where the implementation lands without
        publishing the implementation-boundary contract required by the
        requirements. The assertion uses structured fields instead of
        prose-locking human-facing documentation text.
        """
        contract = getattr(event_bus_module, "INTERNAL_EVENT_BUS_CONTRACT", None)
        assert contract is not None
        assert _contract_field(contract, "stream_name") != CARTRIDGE_STREAM_NAME
        assert _contract_field(contract, "consumer_group_rule") not in (None, "")
        assert _contract_field(contract, "event_namespace_rule") not in (None, "")
        assert _contract_field(contract, "redis_outage_mode") not in (None, "")

    @pytest.mark.unit
    async def test_subscribers_run_under_durable_acknowledgment_boundary_subscriber_exception(
        self,
    ) -> None:
        """A subscribed handler that raises does not produce an XACK.

        Catches a regression where the migration silently swallows handler
        exceptions instead of letting the durable acknowledgment boundary
        withhold ACK and trigger redelivery.
        """
        redis = _make_redis_fake()
        envelope = _session_started_envelope()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                [],
                [(b"internal-stream", [(b"1-0", envelope.to_stream_dict())])],
                asyncio.CancelledError(),
            ]
        )
        bus = EventBus(role="daemon", redis_client=redis)

        async def raising_handler(_event: str, _context: Any) -> None:
            raise RuntimeError("handler failure")

        bus.subscribe("session_started", raising_handler)
        shutdown = asyncio.Event()
        await bus.start(shutdown)
        redis.xack.assert_not_called()

    @pytest.mark.unit
    async def test_subscribers_run_under_durable_acknowledgment_boundary_subscriber_skip(
        self,
    ) -> None:
        """A subscribed handler that returns ``None`` is a deliberate skip and ACKs.

        Catches a regression where deliberate skips are treated as failures.
        """
        redis = _make_redis_fake()
        envelope = _session_started_envelope()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                [],
                [(b"internal-stream", [(b"1-0", envelope.to_stream_dict())])],
                asyncio.CancelledError(),
            ]
        )
        bus = EventBus(role="daemon", redis_client=redis)

        async def skipping_handler(_event: str, _context: Any) -> None:
            return None

        bus.subscribe("session_started", skipping_handler)
        shutdown = asyncio.Event()
        await bus.start(shutdown)
        redis.xack.assert_called()

    @pytest.mark.unit
    async def test_subscriber_idempotent_under_redelivery(self) -> None:
        """A successful subscriber is not re-run when the same entry is redelivered."""
        redis = _make_redis_fake()
        envelope = EventEnvelope(
            event="internal.session_started",
            source="test",
            level=2,
            idempotency_key="sess-1",
            payload={"context_type": "SessionLifecycleContext", "session_id": "sess-1"},
        )
        redis.xreadgroup = AsyncMock(
            side_effect=[
                [],
                [(b"internal-stream", [(b"1-0", envelope.to_stream_dict())])],
                [(b"internal-stream", [(b"1-0", envelope.to_stream_dict())])],
                asyncio.CancelledError(),
            ]
        )
        bus = EventBus(role="daemon", redis_client=redis)
        external_effects: list[str] = []

        async def successful_handler(_event: str, context: Any) -> None:
            external_effects.append(getattr(context, "session_id", "unknown"))

        async def failing_handler(_event: str, _context: Any) -> None:
            raise RuntimeError("force redelivery")

        bus.subscribe("session_started", successful_handler)
        bus.subscribe("session_started", failing_handler)
        shutdown = asyncio.Event()
        await bus.start(shutdown)
        assert external_effects == ["sess-1"]

    @pytest.mark.unit
    async def test_per_role_consumer_group_identity_is_stable_across_restarts(self) -> None:
        """Two EventBus instances with the same role register the same consumer group.

        Pinned via observable Redis side-effect (xgroup_create), not via a
        bus accessor — preserves the requirement's "role-binding mechanism
        is a draft-phase choice" stance for everything except the role
        parameter and the resulting Redis-side group identity.
        """
        redis_a = _make_redis_fake()
        redis_b = _make_redis_fake()
        bus_a = EventBus(role="operation-runner", redis_client=redis_a)
        bus_b = EventBus(role="operation-runner", redis_client=redis_b)
        await _start_and_immediately_shutdown(bus_a)
        await _start_and_immediately_shutdown(bus_b)
        groups_a = {group for _, group in _captured_xgroup_create_calls(redis_a)}
        groups_b = {group for _, group in _captured_xgroup_create_calls(redis_b)}
        assert groups_a, "first instance must register a consumer group"
        assert groups_b, "second instance must register a consumer group"
        assert groups_a == groups_b

    @pytest.mark.unit
    async def test_per_role_consumer_group_identity_differs_across_roles(self) -> None:
        """Two EventBus instances with different roles register different consumer groups."""
        redis_daemon = _make_redis_fake()
        redis_runner = _make_redis_fake()
        bus_daemon = EventBus(role="daemon", redis_client=redis_daemon)
        bus_runner = EventBus(role="operation-runner", redis_client=redis_runner)
        await _start_and_immediately_shutdown(bus_daemon)
        await _start_and_immediately_shutdown(bus_runner)
        groups_daemon = {group for _, group in _captured_xgroup_create_calls(redis_daemon)}
        groups_runner = {group for _, group in _captured_xgroup_create_calls(redis_runner)}
        assert groups_daemon
        assert groups_runner
        assert groups_daemon.isdisjoint(groups_runner)

    @pytest.mark.unit
    async def test_multiple_subscribers_in_one_process_all_receive_event(self) -> None:
        """Two subscribers in one Redis-backed EventBus instance both fire for one event.

        Pins post-migration intra-process concurrent fan-out under the
        durable acknowledgment boundary.
        """
        redis = _make_redis_fake()
        envelope = _agent_event_envelope()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                [],
                [(b"internal-stream", [(b"1-0", envelope.to_stream_dict())])],
                asyncio.CancelledError(),
            ]
        )
        bus = EventBus(role="daemon", redis_client=redis)
        invocations: list[str] = []

        async def handler_one(_event: str, _context: Any) -> None:
            invocations.append("one")

        async def handler_two(_event: str, _context: Any) -> None:
            invocations.append("two")

        bus.subscribe("agent_event", handler_one)
        bus.subscribe("agent_event", handler_two)
        shutdown = asyncio.Event()
        await bus.start(shutdown)
        assert sorted(invocations) == ["one", "two"]


class TestEventBusContextRoundTripSpecs:
    """Per-member ``EventContext`` round-trip behavioral specs.

    Each spec emits an instance of one ``EventContext`` union member, then
    reconstructs the same union-member instance from the wire-format
    envelope and asserts field-level equality. Catches per-member
    serialization regressions that the single-member representative test
    cannot distinguish.
    """

    async def _emit_and_reconstruct(self, event_name: str, context: Any, context_type: type[Any]) -> Any:
        """Emit ``context`` and reconstruct a typed instance of ``context_type``.

        Filters envelope payload keys to the declared dataclass fields of
        ``context_type`` so envelope-level metadata does not break
        instantiation. Builders satisfy these specs by carrying the full
        dataclass field set in the envelope payload.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(event_name, context)
        calls = _captured_xadd_calls(redis)
        assert calls, "emit must produce at least one XADD call"
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        field_names = {f.name for f in dataclasses.fields(context_type)}
        kwargs = {k: v for k, v in envelope.payload.items() if k in field_names}
        return context_type(**kwargs)

    @pytest.mark.unit
    async def test_round_trip_session_lifecycle_context(self) -> None:
        """``SessionLifecycleContext`` round-trip preserves session_id."""
        original = SessionLifecycleContext(session_id="sess-lifecycle-1")
        rebuilt = await self._emit_and_reconstruct("session_started", original, SessionLifecycleContext)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_session_close_completed_payload(self) -> None:
        """``SessionCloseCompletedPayload`` round-trip preserves session_id."""
        original = SessionCloseCompletedPayload(session_id="sess-close-1")
        rebuilt = await self._emit_and_reconstruct("session_closed", original, SessionCloseCompletedPayload)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_session_escalated_payload(self) -> None:
        """``SessionEscalatedPayload`` round-trip preserves session_id."""
        original = SessionEscalatedPayload(session_id="sess-escalated-1")
        rebuilt = await self._emit_and_reconstruct("session_started", original, SessionEscalatedPayload)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_agent_restart_dispatched_payload(self) -> None:
        """``AgentRestartDispatchedPayload`` round-trip preserves session_id."""
        original = AgentRestartDispatchedPayload(session_id="sess-restart-1")
        rebuilt = await self._emit_and_reconstruct("agent_event", original, AgentRestartDispatchedPayload)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_session_status_context(self) -> None:
        """``SessionStatusContext`` round-trip preserves required + optional fields."""
        original = SessionStatusContext(
            session_id="sess-status-1",
            status="active",
            reason="started",
            timestamp="2026-05-09T12:00:00Z",
            last_activity_at="2026-05-09T12:00:01Z",
            message_intent="ctrl_status",
            delivery_scope="CTRL",
        )
        rebuilt = await self._emit_and_reconstruct("session_status", original, SessionStatusContext)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_session_updated_context(self) -> None:
        """``SessionUpdatedContext`` round-trip preserves Mapping payload."""
        original = SessionUpdatedContext(
            session_id="sess-update-1",
            updated_fields={"status": "active", "last_activity_at": "2026-05-09T12:00:00Z"},
        )
        rebuilt = await self._emit_and_reconstruct("session_updated", original, SessionUpdatedContext)
        assert rebuilt.session_id == original.session_id
        assert dict(rebuilt.updated_fields) == dict(original.updated_fields)

    @pytest.mark.unit
    async def test_session_updated_context_serializes_datetime_update_values_as_utc_iso(self) -> None:
        """``SessionUpdatedContext`` datetime updates serialize as JSON-safe UTC timestamps."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        local_timestamp = datetime(2026, 5, 9, 14, 30, 0, tzinfo=timezone(timedelta(hours=2)))
        expected_timestamp = local_timestamp.astimezone(UTC).isoformat()

        await bus.emit(
            "session_updated",
            SessionUpdatedContext(
                session_id="sess-update-datetime-1",
                updated_fields={"last_activity_at": local_timestamp},
            ),
        )

        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        updated_fields = envelope.payload.get("updated_fields")
        assert isinstance(updated_fields, Mapping)
        assert updated_fields.get("last_activity_at") == expected_timestamp

    @pytest.mark.unit
    async def test_session_updated_context_treats_naive_datetime_update_values_as_utc(self) -> None:
        """``SessionUpdatedContext`` naive datetime updates serialize as UTC timestamps."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)

        await bus.emit(
            "session_updated",
            SessionUpdatedContext(
                session_id="sess-update-naive-datetime-1",
                updated_fields={"last_activity_at": datetime(2026, 5, 9, 14, 30, 0)},
            ),
        )

        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        updated_fields = envelope.payload.get("updated_fields")
        assert isinstance(updated_fields, Mapping)
        assert updated_fields.get("last_activity_at") == "2026-05-09T14:30:00+00:00"

    @pytest.mark.unit
    async def test_round_trip_message_event_context(self) -> None:
        """``MessageEventContext`` round-trip preserves session_id and text."""
        original = MessageEventContext(session_id="sess-msg-1", text="hello world")
        rebuilt = await self._emit_and_reconstruct("agent_event", original, MessageEventContext)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_system_command_context(self) -> None:
        """``SystemCommandContext`` round-trip preserves command and from_computer."""
        original = SystemCommandContext(command="restart", from_computer="MozBook")
        rebuilt = await self._emit_and_reconstruct("system_command", original, SystemCommandContext)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_agent_availability_context(self) -> None:
        """``AgentAvailabilityContext`` round-trip preserves required + optional fields."""
        original = AgentAvailabilityContext(
            agent="claude",
            available=False,
            status="busy",
            unavailable_until="2026-05-09T13:00:00Z",
            reason="rate-limited",
        )
        rebuilt = await self._emit_and_reconstruct("agent_availability", original, AgentAvailabilityContext)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_agent_event_context(self) -> None:
        """``AgentEventContext`` round-trip preserves nested payload union shape."""
        original = AgentEventContext(
            session_id="sess-agent-1",
            data=AgentSessionStartPayload(
                raw={"hook": "SessionStart"},
                transcript_path="/tmp/sess-agent-1.jsonl",
                session_id="sess-agent-1",
            ),
            event_type="session_start",
        )
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("agent_event", original)
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        nested = envelope.payload.get("data")
        event_type = envelope.payload.get("event_type")
        assert isinstance(nested, Mapping)
        assert event_type == original.event_type
        rebuilt = AgentEventContext(
            session_id=str(envelope.payload.get("session_id")),
            data=AgentSessionStartPayload(
                raw=dict(nested.get("raw", {})),
                transcript_path=nested.get("transcript_path"),
                session_id=nested.get("session_id"),
            ),
            event_type=cast(AgentHookEventType, event_type),
        )
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_error_event_context(self) -> None:
        """``ErrorEventContext`` round-trip preserves message, severity, and details."""
        original = ErrorEventContext(
            session_id="sess-err-1",
            message="upstream timeout",
            source="api",
            details={"attempt": 3, "route": "jobs"},
            severity="error",
            retryable=True,
            code="UPSTREAM_TIMEOUT",
        )
        rebuilt = await self._emit_and_reconstruct("error", original, ErrorEventContext)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_operation_completed_context(self) -> None:
        """``OperationCompletedContext`` round-trip preserves operation_id and error."""
        original = OperationCompletedContext(operation_id="op-1", error="boom: timeout reaching upstream")
        rebuilt = await self._emit_and_reconstruct(
            "operation.todo_create.completed", original, OperationCompletedContext
        )
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_job_started_payload(self) -> None:
        """``JobStartedPayload`` round-trip preserves job_name."""
        original = JobStartedPayload(job_name="ingest-corpus")
        rebuilt = await self._emit_and_reconstruct("agent_event", original, JobStartedPayload)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_job_completed_payload(self) -> None:
        """``JobCompletedPayload`` round-trip preserves job_name."""
        original = JobCompletedPayload(job_name="ingest-corpus")
        rebuilt = await self._emit_and_reconstruct("agent_event", original, JobCompletedPayload)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_job_failed_payload(self) -> None:
        """``JobFailedPayload`` round-trip preserves job_name and error."""
        original = JobFailedPayload(job_name="ingest-corpus", error="parser crashed")
        rebuilt = await self._emit_and_reconstruct("agent_event", original, JobFailedPayload)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_notification_claimed_payload(self) -> None:
        """``NotificationClaimedPayload`` round-trip preserves notification_id and agent_id."""
        original = NotificationClaimedPayload(notification_id=42, agent_id="claude")
        rebuilt = await self._emit_and_reconstruct("agent_event", original, NotificationClaimedPayload)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_notification_resolved_payload(self) -> None:
        """``NotificationResolvedPayload`` round-trip preserves notification_id."""
        original = NotificationResolvedPayload(notification_id=42)
        rebuilt = await self._emit_and_reconstruct("agent_event", original, NotificationResolvedPayload)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_user_prompt_submit_activity_event(self) -> None:
        """``UserPromptSubmitActivityEvent`` round-trip preserves the activity discriminant."""
        original = UserPromptSubmitActivityEvent(
            session_id="sess-prompt-1",
            event_type="user_prompt_submit",
            timestamp="2026-05-09T12:01:00Z",
            canonical_type="user_prompt",
            message_intent="activity",
            delivery_scope="SESSION",
        )
        rebuilt = await self._emit_and_reconstruct("agent_activity", original, UserPromptSubmitActivityEvent)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_tool_use_activity_event(self) -> None:
        """``ToolUseActivityEvent`` round-trip preserves tool fields."""
        original = ToolUseActivityEvent(
            session_id="sess-tool-1",
            event_type="tool_use",
            timestamp="2026-05-09T12:02:00Z",
            canonical_type="tool_use",
            message_intent="activity",
            delivery_scope="SESSION",
            tool_name="Bash",
            tool_preview="echo hi",
        )
        rebuilt = await self._emit_and_reconstruct("agent_activity", original, ToolUseActivityEvent)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_agent_stop_activity_event(self) -> None:
        """``AgentStopActivityEvent`` round-trip preserves summary/message."""
        original = AgentStopActivityEvent(
            session_id="sess-stop-1",
            event_type="agent_stop",
            timestamp="2026-05-09T12:03:00Z",
            canonical_type="agent_stop",
            message_intent="activity",
            delivery_scope="SESSION",
            summary="finished work",
            message="done",
        )
        rebuilt = await self._emit_and_reconstruct("agent_activity", original, AgentStopActivityEvent)
        assert rebuilt == original

    @pytest.mark.unit
    async def test_round_trip_agent_activity_event_union(self) -> None:
        """``AgentActivityEvent`` union dispatches to the correct subclass on round-trip.

        Catches a regression where the discriminant field is dropped on the
        wire, collapsing the union into a single shape.
        """
        original: AgentActivityEvent = ToolUseActivityEvent(
            session_id="sess-union-1",
            event_type="tool_use",
            tool_name="Read",
        )
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("agent_activity", original)
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        event_type = envelope.payload.get("event_type")
        assert event_type == "tool_use"
        activity_type = cast(AgentHookEventType, event_type)
        if activity_type == "tool_use":
            rebuilt = ToolUseActivityEvent(
                session_id=str(envelope.payload.get("session_id")),
                event_type=activity_type,
                tool_name=envelope.payload.get("tool_name"),
            )
        elif activity_type == "user_prompt_submit":
            rebuilt = UserPromptSubmitActivityEvent(
                session_id=str(envelope.payload.get("session_id")),
                event_type=activity_type,
            )
        else:
            rebuilt = AgentStopActivityEvent(
                session_id=str(envelope.payload.get("session_id")),
                event_type=activity_type,
            )
        assert rebuilt == original

    @pytest.mark.unit
    async def test_envelope_payload_carries_context_type_discriminator(self) -> None:
        """Envelope payload carries a non-domain discriminator for reconstruction."""
        original = ErrorEventContext(session_id="sess-discriminator-1", message="boom")
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("error", original)
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("context_type") == "ErrorEventContext"

    @pytest.mark.unit
    async def test_decode_internal_envelope_reconstructs_agent_activity_subclass(self) -> None:
        """Internal envelope decode rebuilds the typed activity subclass."""
        original = ToolUseActivityEvent(
            session_id="sess-decode-1",
            event_type="tool_use",
            tool_name="Read",
            tool_preview="teleclaude/core/event_bus.py",
        )
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("agent_activity", original)
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        event_name, rebuilt = event_bus_module.decode_internal_event_envelope(envelope)
        assert event_name == "agent_activity"
        assert isinstance(rebuilt, ToolUseActivityEvent)
        assert rebuilt == original


class TestEventBusCallSiteSpecs:
    """Behavioral specs for existing call-site patterns from the migration scope.

    Each spec exercises one distinct EventType + EventContext shape used by
    the existing production callers. Catches a regression where the
    migration breaks a specific call-site pattern (e.g. session lifecycle,
    operation completion) even when the public-API signature check passes.
    """

    @pytest.mark.unit
    async def test_call_site_session_lifecycle_emit(self) -> None:
        """``daemon_session.py``-style session-lifecycle emit produces an XADD.

        Pins that the migration preserves the most common emitter shape:
        a session-lifecycle event with a ``SessionLifecycleContext`` payload.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("session_started", SessionLifecycleContext(session_id="sess-cs-1"))
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("session_id") == "sess-cs-1"

    @pytest.mark.unit
    async def test_call_site_agent_availability_emit(self) -> None:
        """``daemon_session.py``-style agent-availability emit produces an XADD.

        Pins the migration preserves agent-availability emission with the
        ``AgentAvailabilityContext`` shape.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "agent_availability",
            AgentAvailabilityContext(agent="claude", available=True, status="ready"),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("agent") == "claude"
        assert envelope.payload.get("available") is True

    @pytest.mark.unit
    async def test_call_site_operation_completed_emit(self) -> None:
        """``core/operations/service.py``-style operation-completion emit produces an XADD.

        Pins the migration preserves the operation-completion call site at
        ``_run_operation`` — the most reliability-sensitive emission today.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "operation.todo_create.completed",
            OperationCompletedContext(operation_id="op-cs-1"),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("operation_id") == "op-cs-1"

    @pytest.mark.unit
    async def test_call_site_error_emit(self) -> None:
        """Error-event emit produces an XADD with the error payload preserved.

        Pins migration behavior for callers that surface an
        ``ErrorEventContext`` (e.g. session cleanup, command service).
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "error",
            ErrorEventContext(session_id="sess-err-cs", message="boom", severity="error"),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("message") == "boom"
        assert envelope.payload.get("severity") == "error"

    @pytest.mark.unit
    async def test_call_site_system_command_emit(self) -> None:
        """``daemon.py``-style system-command emit produces an XADD.

        Pins the migration preserves the no-session-id system-command shape.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "system_command",
            SystemCommandContext(command="restart", from_computer="MozBook"),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("command") == "restart"
        assert envelope.payload.get("from_computer") == "MozBook"

    @pytest.mark.unit
    async def test_call_site_job_started_raw_emit(self) -> None:
        """``api/jobs_routes.py`` job-started raw event-name emit produces an XADD."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "job.started",  # type: ignore[arg-type, unused-ignore]  # spec mirrors existing raw-string call site
            JobStartedPayload(job_name="nightly-sync"),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("job_name") == "nightly-sync"

    @pytest.mark.unit
    async def test_call_site_job_completed_raw_emit(self) -> None:
        """``api/jobs_routes.py`` job-completed raw event-name emit produces an XADD."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "job.completed",  # type: ignore[arg-type, unused-ignore]  # spec mirrors existing raw-string call site
            JobCompletedPayload(job_name="nightly-sync"),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("job_name") == "nightly-sync"

    @pytest.mark.unit
    async def test_call_site_job_failed_raw_emit(self) -> None:
        """``api/jobs_routes.py`` job-failed raw event-name emit preserves the error."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "job.failed",  # type: ignore[arg-type, unused-ignore]  # spec mirrors existing raw-string call site
            JobFailedPayload(job_name="nightly-sync", error="cron runner failed"),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("job_name") == "nightly-sync"
        assert envelope.payload.get("error") == "cron runner failed"

    @pytest.mark.unit
    async def test_call_site_notification_claimed_raw_emit(self) -> None:
        """``api/notifications_routes.py`` notification-claimed raw emit preserves fields."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "notification.claimed",  # type: ignore[arg-type, unused-ignore]  # spec mirrors existing raw-string call site
            NotificationClaimedPayload(notification_id=42, agent_id="claude"),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("notification_id") == 42
        assert envelope.payload.get("agent_id") == "claude"

    @pytest.mark.unit
    async def test_call_site_notification_resolved_raw_emit(self) -> None:
        """``api/notifications_routes.py`` notification-resolved raw emit preserves fields."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit(
            "notification.resolved",  # type: ignore[arg-type, unused-ignore]  # spec mirrors existing raw-string call site
            NotificationResolvedPayload(notification_id=42),
        )
        calls = _captured_xadd_calls(redis)
        assert calls
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        assert envelope.payload.get("notification_id") == 42


class TestEventBusVisibilityAwareDispatch:
    """Behavioral contract for ``EventBus.emit`` visibility-aware routing.

    Pins the LOCAL-vs-CLUSTER transport split that lets high-volume same-process
    signals (``AGENT_READY``) bypass Redis entirely without changing the
    public emit/subscribe surface.
    """

    @pytest.mark.unit
    async def test_emit_local_does_not_call_xadd(self) -> None:
        """``visibility=LOCAL`` must skip the Redis publish leg entirely."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        task = bus.emit(
            "agent_ready",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.LOCAL,
        )
        await task
        redis.xadd.assert_not_awaited()

    @pytest.mark.unit
    async def test_emit_local_dispatches_to_subscribed_handler(self) -> None:
        """``visibility=LOCAL`` must invoke registered in-process handlers."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        received: list[tuple[str, SessionLifecycleContext]] = []

        async def handler(event: str, context: Any) -> None:
            received.append((event, cast(SessionLifecycleContext, context)))

        bus.subscribe("agent_ready", handler)
        task = bus.emit(
            "agent_ready",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.LOCAL,
        )
        await task
        assert len(received) == 1
        assert received[0][0] == "agent_ready"
        assert received[0][1].session_id == "sess-1"

    @pytest.mark.unit
    async def test_emit_default_visibility_still_publishes_to_redis(self) -> None:
        """Existing call sites without ``visibility`` keep CLUSTER semantics (xadd called)."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        await bus.emit("session_started", SessionLifecycleContext(session_id="sess-1"))
        calls = _captured_xadd_calls(redis)
        assert calls, "default visibility must still publish to Redis"

    @pytest.mark.unit
    async def test_emit_cluster_also_dispatches_locally(self) -> None:
        """CLUSTER emit must invoke same-process handlers in addition to xadd.

        Pins R2 from implementation-plan: in-process dispatch happens for both
        LOCAL and CLUSTER envelopes; the difference is only whether the Redis
        leg additionally fires. Without this, same-process subscribers pay a
        Redis round-trip via consumer redelivery.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        received: list[str] = []

        async def handler(event: str, _context: Any) -> None:
            received.append(event)

        bus.subscribe("session_started", handler)
        await bus.emit(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.CLUSTER,
        )
        assert received == ["session_started"], "CLUSTER emit must dispatch to same-process subscribers at emit time"
        # Redis leg still ran.
        redis.xadd.assert_awaited()

    @pytest.mark.unit
    async def test_emit_cluster_populates_success_cache_for_local_handlers(self) -> None:
        """CLUSTER local dispatch must record handler success keyed by idempotency_key.

        Pins R4 dedup precondition: when the Redis consumer-group redelivers the
        same envelope to this process, the existing dedup check at deliver() must
        find the handler already recorded as successful and skip re-firing.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)

        async def handler(_event: str, _context: Any) -> None:
            return None

        wrapped = bus.subscribe("session_started", handler)
        await bus.emit(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.CLUSTER,
        )
        # Exactly one envelope was published; pull its idempotency_key.
        calls = _captured_xadd_calls(redis)
        assert calls, "CLUSTER emit must xadd"
        _, payload = calls[-1]
        idempotency_key = payload.get("idempotency_key")
        assert idempotency_key, "envelope must carry a non-empty idempotency_key"
        recorded = bus._successful_handlers.get(idempotency_key, set())
        assert id(wrapped) in recorded, (
            "local dispatch must record handler success against the same idempotency_key the Redis leg published with"
        )

    @pytest.mark.unit
    async def test_local_dispatch_counter_increments_on_local_emit(self) -> None:
        """LOCAL emit must increment ``event_bus.local_dispatch``."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        before = bus.local_dispatch_count
        await bus.emit(
            "agent_ready",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.LOCAL,
        )
        assert bus.local_dispatch_count == before + 1

    @pytest.mark.unit
    async def test_local_dispatch_counter_increments_on_cluster_emit(self) -> None:
        """CLUSTER emit must also increment ``event_bus.local_dispatch`` (it dispatches locally too)."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        before = bus.local_dispatch_count
        await bus.emit(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.CLUSTER,
        )
        assert bus.local_dispatch_count == before + 1

    @pytest.mark.unit
    async def test_cluster_publish_counter_increments_only_on_cluster_emit(self) -> None:
        """``event_bus.cluster_publish`` increments on CLUSTER but not LOCAL."""
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        before = bus.cluster_publish_count
        await bus.emit(
            "agent_ready",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.LOCAL,
        )
        assert bus.cluster_publish_count == before, "LOCAL must not increment cluster_publish"
        await bus.emit(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.CLUSTER,
        )
        assert bus.cluster_publish_count == before + 1, "CLUSTER must increment cluster_publish once per emit"

    @pytest.mark.unit
    async def test_emit_dispatches_locally_when_redis_unconfigured(self) -> None:
        """``emit`` with no Redis client must still dispatch to local subscribers.

        Same-process subscribers (e.g. the api_server WS-push handler) do not
        depend on Redis. The earlier guard short-circuited the entire emit
        when ``_redis is None``, which silently cut off TUI updates when the
        daemon started up while Redis was unreachable. The bus must serve
        same-process subscribers regardless of Redis state; only the
        cross-host publish leg is skipped.
        """
        bus = EventBus()  # no redis_client
        received: list[str] = []

        async def handler(event: str, _context: Any) -> None:
            received.append(event)

        bus.subscribe("session_started", handler)
        task = bus.emit(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
        )
        await task
        assert received == ["session_started"], "local dispatch must run even when Redis is unconfigured"

    @pytest.mark.unit
    async def test_redis_redelivery_does_not_refire_locally_dispatched_handler(self) -> None:
        """S2.2: a CLUSTER envelope that fired locally must not re-fire on redelivery.

        Simulates the consumer-group reading back the same envelope via
        ``deliver()`` and asserts the handler is invoked exactly once total —
        once on the local leg, zero times on the redelivery leg.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        fire_count = 0

        async def handler(_event: str, _context: Any) -> None:
            nonlocal fire_count
            fire_count += 1

        bus.subscribe("session_started", handler)
        await bus.emit(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.CLUSTER,
        )
        assert fire_count == 1, "local leg fires the handler"

        # Reconstruct the envelope as the consumer group would see it.
        calls = _captured_xadd_calls(redis)
        _, payload = calls[-1]
        envelope = EventEnvelope.from_stream_dict(payload)
        await bus.deliver(envelope)
        assert fire_count == 1, "redelivery must NOT re-fire the locally-dispatched handler"

    @pytest.mark.unit
    async def test_different_idempotency_key_fires_normally_on_delivery(self) -> None:
        """S2.3: dedup is keyed on idempotency_key, not on event name.

        Negative-control for S2.2: an envelope with the same event name but a
        fresh idempotency_key must fire the handler.
        """
        redis = _make_redis_fake()
        bus = EventBus(role="daemon", redis_client=redis)
        fire_count = 0

        async def handler(_event: str, _context: Any) -> None:
            nonlocal fire_count
            fire_count += 1

        bus.subscribe("session_started", handler)
        await bus.emit(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.CLUSTER,
        )
        # Build a fresh envelope (different idempotency_key) and deliver it.
        envelope = bus._build_envelope(
            "session_started",
            SessionLifecycleContext(session_id="sess-2"),
            EventVisibility.CLUSTER,
        )
        await bus.deliver(envelope)
        assert fire_count == 2, "second envelope with different idempotency_key fires the handler"

    @pytest.mark.unit
    async def test_local_emit_succeeds_when_redis_unreachable(self) -> None:
        """S3.1: LOCAL emit must continue working when the Redis client raises."""
        redis = _make_redis_fake()
        redis.xadd = AsyncMock(side_effect=ConnectionError("redis down"))
        bus = EventBus(role="daemon", redis_client=redis)
        fired = False

        async def handler(_event: str, _context: Any) -> None:
            nonlocal fired
            fired = True

        bus.subscribe("agent_ready", handler)
        await bus.emit(
            "agent_ready",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.LOCAL,
        )
        assert fired, "LOCAL emit must dispatch even with Redis unreachable"
        redis.xadd.assert_not_called()

    @pytest.mark.unit
    async def test_cluster_emit_local_leg_fires_when_xadd_fails(self) -> None:
        """S3.2: CLUSTER emit's local leg must run to completion even if xadd fails."""
        redis = _make_redis_fake()
        redis.xadd = AsyncMock(side_effect=ConnectionError("redis down"))
        bus = EventBus(role="daemon", redis_client=redis)
        fired = False

        async def handler(_event: str, _context: Any) -> None:
            nonlocal fired
            fired = True

        bus.subscribe("session_started", handler)
        # Emit and let the publish task fail in the background — emit itself
        # should not raise.
        task = bus.emit(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
            visibility=EventVisibility.CLUSTER,
        )
        # Drain any background tasks so the failure is observed.
        try:
            await task
        except ConnectionError:
            pass  # publish leg failure observed via _publish_done — acceptable
        await asyncio.gather(*list(bus._pending_tasks), return_exceptions=True)
        assert fired, "local leg must fire even when xadd raises"

    @pytest.mark.unit
    async def test_publish_failure_does_not_corrupt_success_cache(self) -> None:
        """S3.3: failed Redis publish must leave _successful_handlers correct.

        After publish failure, the locally-dispatched handler is still in the
        cache. A subsequent retry-via-deliver of the same envelope must dedup.
        """
        redis = _make_redis_fake()
        redis.xadd = AsyncMock(side_effect=ConnectionError("redis down"))
        bus = EventBus(role="daemon", redis_client=redis)
        fire_count = 0

        async def handler(_event: str, _context: Any) -> None:
            nonlocal fire_count
            fire_count += 1

        wrapped = bus.subscribe("session_started", handler)
        envelope = bus._build_envelope(
            "session_started",
            SessionLifecycleContext(session_id="sess-1"),
            EventVisibility.CLUSTER,
        )
        # Run only the local dispatch path with the same envelope key.
        await bus._dispatch_local(
            "session_started", SessionLifecycleContext(session_id="sess-1"), envelope.idempotency_key
        )
        assert fire_count == 1
        cached = bus._successful_handlers.get(envelope.idempotency_key or "", set())
        assert id(wrapped) in cached, "local handler must be recorded as successful"
        # A redelivery via deliver() must skip the cached handler.
        await bus.deliver(envelope)
        assert fire_count == 1, "redelivery after publish failure must still dedup"
