"""Characterization tests for teleclaude.api.ws_mixin."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest
from fastapi import WebSocket

from teleclaude.api.ws_mixin import _WebSocketMixin
from teleclaude.core.models import JsonDict

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache


class _WebSocketMixinHarness(_WebSocketMixin):
    def __init__(self, *, cache: object | None = None) -> None:
        self.client = SimpleNamespace(adapters={})
        self.task_registry = None
        self._cache: DaemonCache | None = cache
        self._ws_clients: set[WebSocket] = set()
        self._client_subscriptions: dict[WebSocket, dict[str, set[str]]] = {}
        self._ws_client_states: dict[WebSocket, object] = {}
        self._previous_interest: dict[str, set[str]] = {}
        self._refresh_debounce_task = None
        self._refresh_pending_payload = None
        self.broadcasts: list[tuple[str, JsonDict, list[WebSocket] | None]] = []
        self.scheduled_refreshes: list[JsonDict] = []
        self.dropped_clients: list[tuple[WebSocket, str]] = []

    @property
    def cache(self) -> DaemonCache | None:
        return self._cache

    @property
    def _event_db(self) -> None:
        return None

    def _broadcast_payload(self, event: str, payload: JsonDict, *, targets: list[WebSocket] | None = None) -> None:
        self.broadcasts.append((event, payload, targets))

    def _schedule_refresh_broadcast(self, payload: JsonDict) -> None:
        self.scheduled_refreshes.append(payload)

    async def _drop_ws_client(self, websocket: WebSocket, *, reason: str) -> None:
        self.dropped_clients.append((websocket, reason))


class _SerializablePayload:
    def to_dict(self) -> JsonDict:
        return {"enabled": True, "count": 2}


class _DisconnectingWebSocket:
    async def send_json(self, payload: object) -> None:
        try:
            raise OSError("broken-pipe")
        except OSError as exc:
            raise RuntimeError("send failed") from exc


class TestWsMixin:
    @pytest.mark.unit
    def test_update_cache_interest_tracks_shared_interest_and_removes_when_last_client_leaves(self) -> None:
        """Interest is added once per computer/data type and removed only when no clients remain."""
        cache = MagicMock()
        server = _WebSocketMixinHarness(cache=cache)
        first_ws = cast(WebSocket, object())
        second_ws = cast(WebSocket, object())

        server._client_subscriptions = {
            first_ws: {"local": {"sessions"}, "raspi": {"projects"}},
            second_ws: {"raspi": {"projects"}},
        }

        newly_added = server._update_cache_interest()

        assert set(newly_added) == {("local", "sessions"), ("raspi", "projects")}
        assert {(call.args[1], call.args[0]) for call in cache.set_interest.call_args_list} == {
            ("local", "sessions"),
            ("raspi", "projects"),
        }
        cache.remove_interest.assert_not_called()

        cache.set_interest.reset_mock()
        server._client_subscriptions = {second_ws: {"raspi": {"projects"}}}

        newly_added = server._update_cache_interest()

        assert newly_added == []
        cache.set_interest.assert_not_called()
        cache.remove_interest.assert_called_once_with("sessions", "local")

        cache.remove_interest.reset_mock()
        server._client_subscriptions = {}

        server._update_cache_interest()

        cache.remove_interest.assert_called_once_with("projects", "raspi")

    @pytest.mark.unit
    def test_on_cache_change_normalizes_snapshot_refresh_events(self) -> None:
        """Snapshot cache events are rebroadcast as refresh events with normalized payload keys."""
        server = _WebSocketMixinHarness()

        server._on_cache_change("todos_snapshot", SimpleNamespace(computer="raspi", path="/repo/demo"))

        assert server.scheduled_refreshes == [
            {
                "event": "todos_updated",
                "data": {"computer": "raspi", "project_path": "/repo/demo"},
            }
        ]
        assert server.broadcasts == []

    @pytest.mark.unit
    def test_on_cache_change_wraps_generic_payloads_using_to_dict_when_available(self) -> None:
        """Non-DTO events fall back to the generic websocket payload contract."""
        server = _WebSocketMixinHarness()

        server._on_cache_change("custom_event", _SerializablePayload())

        assert server.broadcasts == [
            (
                "custom_event",
                {"event": "custom_event", "data": {"enabled": True, "count": 2}},
                None,
            )
        ]
        assert server.scheduled_refreshes == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_ws_payload_treats_disconnect_shaped_send_errors_as_expected(self) -> None:
        """Disconnect-like send failures are swallowed after websocket cleanup."""
        server = _WebSocketMixinHarness()
        websocket = cast(WebSocket, _DisconnectingWebSocket())

        delivered = await server._send_ws_payload(websocket, "refresh", {"event": "refresh"})

        assert delivered is False
        assert server.dropped_clients == [(websocket, "send-disconnect:refresh")]
