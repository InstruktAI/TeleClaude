"""Route-boundary coverage for POST /api/people/message.

Binds the ``telec message`` daemon route: the service layer
(``teleclaude.core.person_messaging``) is faked so only the route's request
parsing, clearance wiring, and error-to-status-code mapping are under test.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from teleclaude.api import people_routes
from teleclaude.api.auth import CallerIdentity, clearance_message_send
from teleclaude.config.schema import MessagingChannel
from teleclaude.core.person_messaging import (
    ChannelCapabilityError,
    ChannelCredentialError,
    PersonMessageOutcome,
    PersonNotFoundError,
)

pytestmark = pytest.mark.integration

_SLUG = "alex"
_TEXT = "hi"
_MESSAGE_ID = "provider-message-id"
_STATUS_OK = "ok"


def _client(monkeypatch: pytest.MonkeyPatch, fake_send) -> AsyncClient:
    monkeypatch.setattr(people_routes, "send_person_message", fake_send)
    app = FastAPI()
    app.include_router(people_routes.router)
    app.dependency_overrides[clearance_message_send] = lambda: CallerIdentity(
        session_id="caller-session", system_role="worker", human_role=None, tmux_session_name=None
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://daemon")


async def test_successful_send_returns_ok_with_resolved_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_send(slug, text, *, file, subject, channel, origin_session_id):
        del file, subject, channel, origin_session_id
        assert slug == _SLUG
        assert text == _TEXT
        return PersonMessageOutcome(channel=MessagingChannel.DISCORD, message_id=_MESSAGE_ID)

    async with _client(monkeypatch, fake_send) as client:
        response = await client.post("/api/people/message", json={"slug": _SLUG, "text": _TEXT})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == _STATUS_OK
    assert body["channel"] == MessagingChannel.DISCORD.value
    assert body["message_id"] == _MESSAGE_ID


async def test_unresolvable_slug_maps_to_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_send(slug, text, *, file, subject, channel, origin_session_id):
        del text, file, subject, channel, origin_session_id
        raise PersonNotFoundError(f"No person found for slug '{slug}'")

    async with _client(monkeypatch, fake_send) as client:
        response = await client.post("/api/people/message", json={"slug": _SLUG, "text": _TEXT})

    assert response.status_code == 404


async def test_missing_credential_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_send(slug, text, *, file, subject, channel, origin_session_id):
        del slug, text, file, subject, channel, origin_session_id
        raise ChannelCredentialError("No Telegram chat_id configured")

    async with _client(monkeypatch, fake_send) as client:
        response = await client.post("/api/people/message", json={"slug": _SLUG, "text": _TEXT})

    assert response.status_code == 422


async def test_channel_capability_failure_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_send(slug, text, *, file, subject, channel, origin_session_id):
        del slug, text, file, subject, channel, origin_session_id
        raise ChannelCapabilityError("WhatsApp has no file-attachment capability")

    async with _client(monkeypatch, fake_send) as client:
        response = await client.post(
            "/api/people/message", json={"slug": _SLUG, "text": _TEXT, "file": "/tmp/report.pdf"}
        )

    assert response.status_code == 422


async def test_provider_send_failure_maps_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_send(slug, text, *, file, subject, channel, origin_session_id):
        del slug, text, file, subject, channel, origin_session_id
        raise RuntimeError("Discord send message failed (HTTP 500): internal error")

    async with _client(monkeypatch, fake_send) as client:
        response = await client.post("/api/people/message", json={"slug": _SLUG, "text": _TEXT})

    assert response.status_code == 502
