"""Readiness endpoint: surfaces whether the daemon serves and which event Redis does not answer.

Liveness (``/health``, process up) answers "is the daemon running?". Readiness
(``/ready``) answers "does the daemon serve?". A daemon whose Redis does not answer
still serves: it reports ready and names the scopes whose Redis does not answer, so
``make start`` and ``telec app status`` can show the degradation instead of failing
the start. Only a daemon with no Redis transport configured is not ready.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from teleclaude.events.redis_reachability import unanswering_event_scopes
from teleclaude.events.scope import EventScope

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


class ReadinessReason(StrEnum):
    """Stable, machine-readable codes for why the daemon is not ready or serves degraded."""

    REDIS_UNCONFIGURED = "redis_unconfigured"
    REDIS_UNREACHABLE = "redis_unreachable"


_CLIENT: dict[str, AdapterClient | None] = {"value": None}

router = APIRouter()


def configure(client: AdapterClient | None) -> None:
    """Wire the adapter client; called from APIServer."""
    _CLIENT["value"] = client


@router.get("/ready")
async def ready() -> JSONResponse:
    """Report whether the daemon serves, and which Redis does not answer.

    Returns 200 ``{"ready": true}``; when an event Redis or the cluster transport
    does not answer, the body adds ``"degraded"``: one ``{"reason": <code>, "scope": <scope>}``
    per scope that does not answer. A daemon with no Redis transport configured
    returns 503 ``{"ready": false, "reason": <code>}``. Codes and scopes are stable
    names only — the raw connection error (which may embed the Redis URL and
    password) is never echoed into the response body.
    """
    client = _CLIENT["value"]
    transport = client.transport if client is not None else None
    if transport is None:
        return _not_ready(ReadinessReason.REDIS_UNCONFIGURED)
    unanswering = set(unanswering_event_scopes())
    if not transport.is_redis_ready:
        unanswering.add(EventScope.CLUSTER)
    if not unanswering:
        return JSONResponse({"ready": True})
    degraded = [
        {"reason": ReadinessReason.REDIS_UNREACHABLE.value, "scope": scope.value}
        for scope in EventScope
        if scope in unanswering
    ]
    return JSONResponse({"ready": True, "degraded": degraded})


def _not_ready(reason: ReadinessReason) -> JSONResponse:
    return JSONResponse({"ready": False, "reason": reason.value}, status_code=503)
