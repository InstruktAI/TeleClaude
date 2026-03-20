"""Characterization tests for notification routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import notifications_routes


@pytest.fixture
def configured_event_db() -> object:
    event_db = type(
        "EventDbStub",
        (),
        {
            "list_notifications": AsyncMock(return_value=[{"id": 1}]),
            "get_notification": AsyncMock(return_value={"id": 1}),
            "update_human_status": AsyncMock(return_value=True),
            "update_agent_status": AsyncMock(return_value=True),
            "resolve_notification": AsyncMock(return_value=True),
        },
    )()
    notifications_routes.configure(event_db)
    return event_db


def _make_request(query_params: dict[str, str] | None = None) -> MagicMock:
    req = MagicMock()
    req.query_params = query_params or {}
    return req


class TestNotificationsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_notifications_forwards_filters_to_event_db(self, configured_event_db: object) -> None:
        """Notification listing passes query filters through to the event store."""
        request = _make_request(
            {
                "level": "2",
                "domain": "todos",
                "human_status": "seen",
                "agent_status": "claimed",
                "visibility": "public",
                "since": "2025-03-15T00:00:00Z",
                "limit": "10",
                "offset": "5",
            }
        )
        rows = await notifications_routes.list_notifications(request)

        assert rows == [{"id": 1}]
        configured_event_db.list_notifications.assert_awaited_once_with(
            level=2,
            domain="todos",
            human_status="seen",
            agent_status="claimed",
            visibility="public",
            since="2025-03-15T00:00:00Z",
            limit=10,
            offset=5,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_claim_notification_requires_non_empty_agent_id(self, configured_event_db: object) -> None:
        """Claiming a notification rejects bodies without a usable agent identifier."""
        with pytest.raises(HTTPException) as exc_info:
            await notifications_routes.claim_notification(7, body={"agent_id": ""})

        assert exc_info.value.status_code == 400
        configured_event_db.update_agent_status.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_resolve_notification_returns_404_when_event_db_rejects_update(
        self,
        configured_event_db: object,
    ) -> None:
        """Resolve requests surface a not-found error when the DB update fails."""
        configured_event_db.resolve_notification.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await notifications_routes.resolve_notification(9, body={"note": "done"})

        assert exc_info.value.status_code == 404

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_claim_notification_emits_claimed_event(self, configured_event_db: object) -> None:
        """claim_notification emits NotificationClaimedPayload with the right IDs.

        A regression removing the emit call would not break the HTTP-shape tests above.
        """
        from teleclaude.core.event_bus import event_bus
        from teleclaude.core.events import NotificationClaimedPayload

        emitted: list[tuple[str, object]] = []

        def capture_emit(event: str, context: object) -> None:
            emitted.append((event, context))

        with patch.object(event_bus, "emit", side_effect=capture_emit):
            await notifications_routes.claim_notification(42, body={"agent_id": "agent-1"})

        claim_events = [(e, p) for e, p in emitted if e == "notification.claimed"]
        assert len(claim_events) == 1, f"Expected notification.claimed, got: {[e[0] for e in emitted]}"
        payload = claim_events[0][1]
        assert isinstance(payload, NotificationClaimedPayload)
        assert payload.notification_id == 42
        assert payload.agent_id == "agent-1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_resolve_notification_emits_resolved_event(self, configured_event_db: object) -> None:
        """resolve_notification emits NotificationResolvedPayload with the notification ID."""
        from teleclaude.core.event_bus import event_bus
        from teleclaude.core.events import NotificationResolvedPayload

        emitted: list[tuple[str, object]] = []

        def capture_emit(event: str, context: object) -> None:
            emitted.append((event, context))

        with patch.object(event_bus, "emit", side_effect=capture_emit):
            await notifications_routes.resolve_notification(99, body={"note": "done"})

        resolve_events = [(e, p) for e, p in emitted if e == "notification.resolved"]
        assert len(resolve_events) == 1, f"Expected notification.resolved, got: {[e[0] for e in emitted]}"
        payload = resolve_events[0][1]
        assert isinstance(payload, NotificationResolvedPayload)
        assert payload.notification_id == 99
