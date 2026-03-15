"""Characterization tests for websocket constants and state."""

from __future__ import annotations

import importlib

import pytest

from teleclaude.api import ws_constants


class TestWsConstants:
    @pytest.mark.unit
    def test_reload_reads_timeout_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Module reload picks up websocket timeout overrides from the environment."""
        monkeypatch.setenv("API_WS_CONTROL_SEND_TIMEOUT_S", "11")
        monkeypatch.setenv("API_WS_DEFAULT_SEND_TIMEOUT_S", "7")
        monkeypatch.setenv("API_WS_REPLACEABLE_SEND_TIMEOUT_S", "3")

        reloaded = importlib.reload(ws_constants)

        assert reloaded.API_WS_CONTROL_SEND_TIMEOUT_S == 11.0
        assert reloaded.API_WS_DEFAULT_SEND_TIMEOUT_S == 7.0
        assert reloaded.API_WS_REPLACEABLE_SEND_TIMEOUT_S == 3.0

    @pytest.mark.unit
    def test_ws_client_state_instances_do_not_share_queues(self) -> None:
        """Each websocket client state gets its own outbound queue."""
        first = ws_constants._WsClientState()
        second = ws_constants._WsClientState()

        first.queue.put_nowait(("refresh", {"event": "refresh"}))

        assert first.queue.qsize() == 1
        assert second.queue.qsize() == 0
        assert first.sender_task is None
        assert second.sender_task is None

    @pytest.mark.unit
    def test_control_and_replaceable_events_are_kept_disjoint(self) -> None:
        """Control-plane websocket events never overlap the replaceable event bucket."""
        assert ws_constants.API_WS_CONTROL_EVENTS.isdisjoint(ws_constants.API_WS_REPLACEABLE_EVENTS)
