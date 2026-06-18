"""Readiness endpoint: surfaces whether hard dependencies (Redis) are reachable.

Liveness (``/health``, process up) answers "is the daemon running?". Readiness
(``/ready``) answers "has the daemon connected to Redis at least once?". The two
are deliberately distinct: a service-supervised daemon stays alive and retries a
blipping Redis (resilience), but ``make start`` gates on readiness so a
misconfigured ``REDIS_URL`` fails fast at the start boundary instead of passing
silently.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


class ReadinessReason(StrEnum):
    """Stable, machine-readable codes for why the daemon is not ready."""

    REDIS_UNCONFIGURED = "redis_unconfigured"
    REDIS_UNREACHABLE = "redis_unreachable"


_CLIENT: dict[str, AdapterClient | None] = {"value": None}

router = APIRouter()


def configure(client: AdapterClient | None) -> None:
    """Wire the adapter client; called from APIServer."""
    _CLIENT["value"] = client


@router.get("/ready")
async def ready() -> JSONResponse:
    """Report readiness of hard dependencies.

    Returns 200 ``{"ready": true}`` once Redis has connected at least once;
    otherwise 503 ``{"ready": false, "reason": <code>}``. The reason is a stable
    code only — the raw connection error (which may embed the Redis URL and
    password) is never echoed into the response body.
    """
    client = _CLIENT["value"]
    transport = client.transport if client is not None else None
    if transport is None:
        return _not_ready(ReadinessReason.REDIS_UNCONFIGURED)
    if not transport.is_redis_ready:
        return _not_ready(ReadinessReason.REDIS_UNREACHABLE)
    return JSONResponse({"ready": True})


def _not_ready(reason: ReadinessReason) -> JSONResponse:
    return JSONResponse({"ready": False, "reason": reason.value}, status_code=503)
