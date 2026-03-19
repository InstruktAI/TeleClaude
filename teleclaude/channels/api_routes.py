"""FastAPI router for channel HTTP endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis

from teleclaude.api import auth as auth_module
from teleclaude.api.auth import CallerIdentity
from teleclaude.channels.publisher import list_channels, publish
from teleclaude.channels.types import ChannelInfo
from teleclaude.transport.redis_transport import RedisTransport

router = APIRouter(prefix="/api/channels", tags=["channels"])
clearance_channels_list = auth_module.clearance_channels_list
clearance_channels_publish = auth_module.clearance_channels_publish

_TRANSPORT_STATE: dict[str, RedisTransport | None] = {"value": None}
globals()["_redis_transport"] = None


def set_redis_transport(transport: RedisTransport) -> None:
    """Called by daemon during startup to inject the RedisTransport instance."""
    if _get_transport_state() is not None:
        raise RuntimeError("RedisTransport already configured; refusing duplicate setup")
    _TRANSPORT_STATE["value"] = transport
    globals()["_redis_transport"] = transport


def _get_transport() -> RedisTransport:
    transport = _get_transport_state()
    if transport is None:
        raise HTTPException(status_code=503, detail="Redis transport not available")
    return transport


def _get_transport_state() -> RedisTransport | None:
    return cast(RedisTransport | None, globals().get("_redis_transport", _TRANSPORT_STATE["value"]))


async def _get_redis_client(transport: RedisTransport) -> Redis:
    """Return the configured Redis client using the transport's stable seam."""
    legacy_getter = getattr(transport, "_get_redis", None)
    if callable(legacy_getter):
        return await cast(Callable[[], Awaitable[Redis]], legacy_getter)()
    return await transport.get_redis()


class PublishRequest(BaseModel):
    """Request body for publishing a channel message."""

    model_config = ConfigDict(frozen=True)

    payload: dict[str, Any]  # guard: loose-dict - Channel payload is arbitrary user JSON


class PublishResponse(BaseModel):
    """Response body returned after a successful publish."""

    model_config = ConfigDict(frozen=True)

    channel: str
    message_id: str


@router.post("/{name}/publish")
async def publish_to_channel(
    name: str,
    req: PublishRequest,
    _identity: CallerIdentity = Depends(clearance_channels_publish),
) -> PublishResponse:
    """Publish a message to a named channel."""
    transport = _get_transport()
    redis_client = await _get_redis_client(transport)
    msg_id = await publish(redis_client, name, req.payload)
    return PublishResponse(channel=name, message_id=msg_id)


@router.get("/")
async def list_all_channels(
    project: str | None = None,
    _identity: CallerIdentity = Depends(clearance_channels_list),
) -> list[ChannelInfo]:
    """List active channels, optionally filtered by project."""
    transport = _get_transport()
    redis_client = await _get_redis_client(transport)
    return await list_channels(redis_client, project)
