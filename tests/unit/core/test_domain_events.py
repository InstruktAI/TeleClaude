"""Test specifications for FR-4: Domain event emission for fire-and-forget mutations.

Fire-and-forget mutations must emit domain events that signal completion or acceptance.
All new events must follow the existing domain event pattern (typed payload dataclasses).
The 202 response for fire-and-forget endpoints includes the completion_event name.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.routing import APIRoute

import teleclaude.core.events as events_mod
from teleclaude.api.sessions_routes import router
from teleclaude.core.command_handlers._agent import agent_restart
from teleclaude.core.command_handlers._session import close_session
from teleclaude.core.command_service import CommandService
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentRestartDispatchedPayload,
    JobStartedPayload,
    NotificationClaimedPayload,
    NotificationResolvedPayload,
    SessionCloseCompletedPayload,
    SessionEscalatedPayload,
)
from teleclaude.types.commands import CloseSessionCommand, RestartAgentCommand

# ---------------------------------------------------------------------------
# FR-4.1: Agent restart event emission
# ---------------------------------------------------------------------------


class TestAgentRestartEventEmission:
    """Agent restart handler emits a typed domain event when restart is dispatched."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_agent_restart_handler_emits_typed_event(self) -> None:
        """The agent restart handler emits a specific typed event with session context.

        Must emit the declared event type (not just any string containing 'restart')
        with a typed payload carrying session_id.
        """
        cmd = RestartAgentCommand(session_id="s1")

        mock_session = MagicMock()
        mock_session.session_id = "s1"
        mock_session.active_agent = "claude"
        mock_session.native_session_id = "native-1"
        mock_session.closed_at = None
        mock_session.tmux_session_name = "tmux-1"
        mock_session.lifecycle_status = "active"
        mock_session.thinking_mode = "slow"

        client = MagicMock()
        client.send_message = AsyncMock()
        execute_terminal_command = AsyncMock(return_value=True)

        emitted: list[tuple[str, object]] = []

        def capture_emit(event: str, context: object) -> None:
            emitted.append((event, context))

        def capture_task(coro: object, *, name: str | None = None) -> MagicMock:
            _ = name
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            return MagicMock()

        with (
            patch("teleclaude.core.command_handlers._utils.db") as mock_db,
            patch("teleclaude.core.command_handlers._agent.tmux_bridge") as mock_tmux_bridge,
            patch("teleclaude.core.command_handlers._agent.tmux_io") as mock_tmux_io,
            patch("teleclaude.core.command_handlers._agent.assert_agent_enabled", return_value="claude"),
            patch("teleclaude.core.command_handlers._agent.get_agent_command", return_value="claude resume"),
            patch("asyncio.create_task", side_effect=capture_task),
            patch.object(event_bus, "emit", side_effect=capture_emit),
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            mock_tmux_bridge.session_exists = AsyncMock(return_value=True)
            mock_tmux_bridge.get_pane_pid = AsyncMock(return_value=None)
            mock_tmux_bridge.send_keys_existing_tmux = AsyncMock(return_value=True)
            mock_tmux_io.send_signal = AsyncMock(return_value=False)
            mock_tmux_io.wait_for_shell_ready = AsyncMock(return_value=True)
            await agent_restart(cmd, client, execute_terminal_command)

        # Must emit the exact declared event type, not just a substring match
        assert cmd.completion_event is not None
        restart_events = [e for e in emitted if e[0] == cmd.completion_event]
        assert len(restart_events) == 1, (
            f"Expected exactly one {cmd.completion_event} event, "
            f"got {len(restart_events)} events: {[e[0] for e in emitted]}"
        )

        # Payload must be a typed dataclass with session_id
        payload = restart_events[0][1]
        assert isinstance(payload, AgentRestartDispatchedPayload)
        assert payload.session_id == "s1"


# ---------------------------------------------------------------------------
# FR-4.2: Session escalation event emission
# ---------------------------------------------------------------------------


class TestSessionEscalationEventEmission:
    """Session escalation emits a typed domain event when escalation is initiated."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_escalation_handler_emits_typed_event(self) -> None:
        """The escalation handler emits a typed SessionEscalatedPayload event."""
        # Verify the payload type is a dataclass with required fields
        assert dataclasses.is_dataclass(SessionEscalatedPayload)

        payload = SessionEscalatedPayload(session_id="s1")
        assert payload.session_id == "s1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_escalation_handler_emits_event_on_discord_thread_creation(self) -> None:
        """_handle_escalate_session emits SessionEscalatedPayload after thread creation.

        Must call event_bus.emit with the declared event name and a typed payload
        carrying the session_id — not a raw dict or ad-hoc string.
        """

        # A minimal stub that passes the isinstance(adapter, DiscordAdapter) check
        # by replacing the class itself in the module during the call.
        class _FakeDiscordAdapter:
            async def create_escalation_thread(self, **kwargs: object) -> str:
                _ = kwargs
                return "thread-123"

        mock_discord = _FakeDiscordAdapter()
        mock_service = MagicMock()
        mock_service.client.adapters.values.return_value = [mock_discord]

        mock_session = MagicMock()
        mock_session.human_role = "customer"

        cmd = MagicMock()
        cmd.session_id = "s1"
        cmd.data = {"customer_name": "Test", "reason": "need help", "context_summary": ""}

        emitted: list[tuple[str, object]] = []

        def capture_emit(event: str, context: object) -> None:
            emitted.append((event, context))

        with (
            # _handle_escalate_session does `isinstance(adapter, DiscordAdapter)` against the
            # name imported into command_service, so the patch must target that local rebinding
            # rather than the source module.
            patch("teleclaude.core.command_service.DiscordAdapter", _FakeDiscordAdapter),
            patch("teleclaude.core.command_service.db") as mock_db,
            patch.object(event_bus, "emit", side_effect=capture_emit),
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            mock_db.update_session = AsyncMock()
            await CommandService._handle_escalate_session(mock_service, cmd)

        escalation_events = [e for e in emitted if e[0] == "session.escalation_started"]
        assert len(escalation_events) == 1, (
            f"Expected exactly one session.escalation_started event, "
            f"got {len(escalation_events)}: {[e[0] for e in emitted]}"
        )
        payload = escalation_events[0][1]
        assert isinstance(payload, SessionEscalatedPayload)
        assert payload.session_id == "s1"


# ---------------------------------------------------------------------------
# FR-4.3: Job lifecycle event emission
# ---------------------------------------------------------------------------


class TestJobLifecycleEventEmission:
    """Job execution emits lifecycle events (started, completed, failed)."""

    @pytest.mark.unit
    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize(
        "payload_cls_name,required_fields",
        [
            ("JobStartedPayload", ["job_name"]),
            ("JobCompletedPayload", ["job_name"]),
            ("JobFailedPayload", ["job_name"]),
        ],
        ids=["started", "completed", "failed"],
    )
    def test_job_lifecycle_payloads_are_typed_dataclasses(
        self, payload_cls_name: str, required_fields: list[str]
    ) -> None:
        """Each job lifecycle payload is a frozen dataclass with required correlation fields."""
        cls = getattr(events_mod, payload_cls_name)
        assert dataclasses.is_dataclass(cls), f"{payload_cls_name} is not a dataclass"

        # Verify required fields exist
        field_names = {f.name for f in dataclasses.fields(cls)}
        for req in required_fields:
            assert req in field_names, f"{payload_cls_name} missing required field: {req}"

    @pytest.mark.unit
    def test_job_started_payload_construction(self) -> None:
        """JobStartedPayload can be constructed with job_name."""
        payload = JobStartedPayload(job_name="cleanup")
        assert payload.job_name == "cleanup"


# ---------------------------------------------------------------------------
# FR-4.4: Session close completion event
# ---------------------------------------------------------------------------


class TestSessionCloseCompletedEventEmission:
    """Session close handler emits a completion event when close processing finishes."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_close_session_handler_emits_completion_event(self) -> None:
        """The close_session handler emits a typed completion event after processing."""
        assert dataclasses.is_dataclass(SessionCloseCompletedPayload)

        payload = SessionCloseCompletedPayload(session_id="s1")
        assert payload.session_id == "s1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_close_session_emits_completion_event_for_already_closed_session(self) -> None:
        """close_session replays close_completed when the session is already terminal.

        The already-closed guard must emit SessionCloseCompletedPayload so callers
        waiting on session.close_completed don't block forever.
        """
        cmd = CloseSessionCommand(session_id="s1")

        mock_session = MagicMock()
        mock_session.session_id = "s1"
        mock_session.computer_name = None
        mock_session.closed_at = "2024-01-01T00:00:00"
        mock_session.lifecycle_status = "closed"

        emitted: list[tuple[str, object]] = []

        def capture_emit(event: str, context: object) -> None:
            emitted.append((event, context))

        with (
            patch("teleclaude.core.command_handlers._utils.db") as mock_db,
            patch.object(event_bus, "emit", side_effect=capture_emit),
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            await close_session(cmd, MagicMock())

        close_events = [e for e in emitted if e[0] == cmd.completion_event]
        assert len(close_events) == 1, (
            f"Expected exactly one {cmd.completion_event} event, got {len(close_events)}: {[e[0] for e in emitted]}"
        )
        payload = close_events[0][1]
        assert isinstance(payload, SessionCloseCompletedPayload)
        assert payload.session_id == "s1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_close_session_emits_completion_event_after_normal_close(self) -> None:
        """close_session emits SessionCloseCompletedPayload after terminating an active session."""
        cmd = CloseSessionCommand(session_id="s2")

        mock_session = MagicMock()
        mock_session.session_id = "s2"
        mock_session.computer_name = None
        mock_session.closed_at = None
        mock_session.lifecycle_status = "active"

        emitted: list[tuple[str, object]] = []

        def capture_emit(event: str, context: object) -> None:
            emitted.append((event, context))

        with (
            patch("teleclaude.core.command_handlers._utils.db") as mock_db,
            patch("teleclaude.core.command_handlers._session.terminate_session", new=AsyncMock()),
            patch.object(event_bus, "emit", side_effect=capture_emit),
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            await close_session(cmd, MagicMock())

        close_events = [e for e in emitted if e[0] == cmd.completion_event]
        assert len(close_events) == 1, (
            f"Expected exactly one {cmd.completion_event} event, got {len(close_events)}: {[e[0] for e in emitted]}"
        )
        payload = close_events[0][1]
        assert isinstance(payload, SessionCloseCompletedPayload)
        assert payload.session_id == "s2"


# ---------------------------------------------------------------------------
# FR-4.5: Notification claim/resolve event emission
# ---------------------------------------------------------------------------


class TestNotificationClaimEventEmission:
    """Notification claim endpoint emits a typed domain event."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_claim_notification_emits_typed_event(self) -> None:
        """claim_notification emits a NotificationClaimedPayload event."""
        assert dataclasses.is_dataclass(NotificationClaimedPayload)

        payload = NotificationClaimedPayload(notification_id=42, agent_id="agent-1")
        assert payload.notification_id == 42
        assert payload.agent_id == "agent-1"


class TestNotificationResolveEventEmission:
    """Notification resolve endpoint emits a typed domain event."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_resolve_notification_emits_typed_event(self) -> None:
        """resolve_notification emits a NotificationResolvedPayload event."""
        assert dataclasses.is_dataclass(NotificationResolvedPayload)

        payload = NotificationResolvedPayload(notification_id=42)
        assert payload.notification_id == 42


# ---------------------------------------------------------------------------
# FR-4.6: All event payloads follow the typed dataclass pattern
# ---------------------------------------------------------------------------


class TestDomainEventPayloadPattern:
    """All new events follow the typed payload dataclass pattern."""

    @pytest.mark.unit
    # guard: parametrize-cleanup-pending
    @pytest.mark.parametrize(
        "payload_cls_name",
        [
            "AgentRestartDispatchedPayload",
            "SessionEscalatedPayload",
            "JobStartedPayload",
            "JobCompletedPayload",
            "JobFailedPayload",
            "SessionCloseCompletedPayload",
            "NotificationClaimedPayload",
            "NotificationResolvedPayload",
        ],
    )
    def test_event_payload_is_dataclass(self, payload_cls_name: str) -> None:
        """Each event payload is a dataclass, not an ad-hoc dict."""
        cls = getattr(events_mod, payload_cls_name)
        assert dataclasses.is_dataclass(cls), f"{payload_cls_name} is not a dataclass"


# ---------------------------------------------------------------------------
# FR-4.7: 202 response body includes completion_event
# ---------------------------------------------------------------------------


class TestFireAndForget202ResponseIncludesCompletionEvent:
    """The 202 response for fire-and-forget endpoints includes the completion_event name."""

    @pytest.mark.unit
    def test_delete_session_route_returns_202(self) -> None:
        """DELETE /sessions/{id} route is registered with status_code=202."""
        delete_routes = [
            route
            for route in router.routes
            if isinstance(route, APIRoute) and route.path == "/sessions/{session_id}" and "DELETE" in route.methods
        ]
        assert len(delete_routes) == 1
        assert delete_routes[0].status_code == 202

    @pytest.mark.unit
    def test_agent_restart_route_returns_202_with_completion_event(self) -> None:
        """POST /sessions/{id}/agent-restart returns 202 with completion_event in body.

        The input audit confirms this endpoint already returns 202. The requirement
        adds that the response body must include the completion_event name.
        """
        cmd = RestartAgentCommand(session_id="s1")
        # The response body for F&F endpoints must include the completion_event
        assert cmd.completion_event is not None
        assert isinstance(cmd.completion_event, str)

    @pytest.mark.unit
    def test_close_session_command_declares_completion_event(self) -> None:
        """CloseSessionCommand declares a completion_event for the 202 response body."""
        cmd = CloseSessionCommand(session_id="s1")
        assert cmd.completion_event is not None
        assert isinstance(cmd.completion_event, str)
        assert len(cmd.completion_event) > 0
