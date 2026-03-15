"""Characterization tests for teleclaude.channels.api_routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import teleclaude.channels.api_routes as api_routes


@pytest.fixture(autouse=True)
def _reset_redis_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_routes, "_redis_transport", None)


class TestTransportConfiguration:
    @pytest.mark.unit
    def test_get_transport_raises_503_when_transport_missing(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            api_routes._get_transport()

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Redis transport not available"

    @pytest.mark.unit
    def test_set_redis_transport_rejects_duplicate_setup(self) -> None:
        api_routes.set_redis_transport(object())

        with pytest.raises(RuntimeError, match="already configured"):
            api_routes.set_redis_transport(object())


class TestRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_publish_to_channel_uses_transport_and_returns_response(self) -> None:
        redis_client = object()
        transport = SimpleNamespace(_get_redis=AsyncMock(return_value=redis_client))
        api_routes.set_redis_transport(transport)

        with patch("teleclaude.channels.api_routes.publish", new=AsyncMock(return_value="170-0")) as mock_publish:
            response = await api_routes.publish_to_channel(
                "channel:demo:events",
                api_routes.PublishRequest(payload={"kind": "deploy"}),
            )

        transport._get_redis.assert_awaited_once_with()
        mock_publish.assert_awaited_once_with(redis_client, "channel:demo:events", {"kind": "deploy"})
        assert response == api_routes.PublishResponse(channel="channel:demo:events", message_id="170-0")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_all_channels_passes_project_filter_to_publisher(self) -> None:
        redis_client = object()
        transport = SimpleNamespace(_get_redis=AsyncMock(return_value=redis_client))
        api_routes.set_redis_transport(transport)
        listed_channels = [
            {
                "key": "channel:demo:events",
                "project": "demo",
                "topic": "events",
                "length": 3,
            }
        ]

        with patch(
            "teleclaude.channels.api_routes.list_channels", new=AsyncMock(return_value=listed_channels)
        ) as mock_list:
            response = await api_routes.list_all_channels(project="demo")

        transport._get_redis.assert_awaited_once_with()
        mock_list.assert_awaited_once_with(redis_client, "demo")
        assert response == listed_channels
