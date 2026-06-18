"""Spec-anchored tests for the daemon readiness boundary.

`make start` gates on readiness (`/ready`) rather than liveness (`/health`) so a
misconfigured `REDIS_URL` surfaces at startup instead of being swallowed by the
background reconnect loop. These tests bind UC-WIZ-14 at the real HTTP boundary
the shell consumes: they mount the production readiness router on a bare app and
drive it with a transport whose readiness is set vs. cleared.

Assertions are by HTTP status code and typed JSON fields (and the stable
`ReadinessReason` constants), never by message prose. The no-leak assertion is a
structural check that the Redis URL/password never appears in the response body.

Spec: docs/project/spec/feature/config/setup-wizard.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from teleclaude.api import readiness_routes
from teleclaude.api.readiness_routes import ReadinessReason
from teleclaude.core.adapter_client import AdapterClient

pytestmark = pytest.mark.integration

_SPEC = "project/spec/feature/config/setup-wizard"

# Connection-detail fragments that must never appear in the readiness body, even
# though the daemon holds them internally (a wrong REDIS_URL embeds both).
_REDIS_PASSWORD = "s3cr3t-password"
_REDIS_HOST = "redis.example.invalid"


@dataclass
class _FakeTransport:
    """Duck-typed stand-in for RedisTransport's readiness surface."""

    is_redis_ready: bool


class _FakeClient:
    """Holds only the `transport` attribute the readiness route reads."""

    def __init__(self, transport: _FakeTransport | None) -> None:
        self.transport = transport


def _client(transport: _FakeTransport | None) -> AsyncClient:
    app = FastAPI()
    readiness_routes.configure(client=cast("AdapterClient", _FakeClient(transport)))
    app.include_router(readiness_routes.router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://daemon")


@pytest.mark.spec(_SPEC, "UC-WIZ-14")
async def test_readiness_surfaces_unreachable_redis_then_clears_without_restart() -> None:
    # Given a daemon whose Redis has never connected (the swallowed-failure state),
    # When `/ready` is polled,
    # Then it reports not-ready with a 503 — the surface that was silently green pre-fix
    #   (pre-fix the only surface, `/health`, returned ok unconditionally).
    transport = _FakeTransport(is_redis_ready=False)

    async with _client(transport) as client:
        not_ready = await client.get("/ready")

        assert not_ready.status_code == 503
        not_ready_body = not_ready.json()
        assert not_ready_body["ready"] is False
        assert not_ready_body["reason"] == ReadinessReason.REDIS_UNREACHABLE.value

        # When the configured Redis later becomes reachable (same daemon, no restart),
        # Then `/ready` reports ready.
        transport.is_redis_ready = True
        ready = await client.get("/ready")

        assert ready.status_code == 200
        assert ready.json()["ready"] is True


async def test_ready_reports_503_when_transport_unconfigured() -> None:
    # Given a daemon with no transport wired yet,
    # When `/ready` is polled,
    # Then it reports not-ready with the unconfigured reason.
    async with _client(None) as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == ReadinessReason.REDIS_UNCONFIGURED.value


async def test_ready_body_carries_only_stable_fields_and_no_connection_details() -> None:
    # Given a not-ready daemon,
    # When `/ready` is polled,
    # Then the body is exactly {ready, reason} with a stable reason code — no field
    # that could carry the Redis URL/password, and no such detail in the raw text.
    transport = _FakeTransport(is_redis_ready=False)

    async with _client(transport) as client:
        response = await client.get("/ready")

    body = response.json()
    assert set(body) == {"ready", "reason"}
    assert body["reason"] in {reason.value for reason in ReadinessReason}
    assert _REDIS_PASSWORD not in response.text
    assert _REDIS_HOST not in response.text
