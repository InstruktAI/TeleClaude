"""FastAPI router for channel HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from teleclaude.api import auth as auth_module
from teleclaude.api.auth import CallerIdentity
from teleclaude.channels.publisher import list_channels, publish
from teleclaude.channels.types import ChannelInfo
from teleclaude.transport.redis_transport import RedisTransport

router = APIRouter(prefix="/api/channels", tags=["channels"])
clearance_channels_list = getattr(auth_module, "clearance_channels_list")
clearance_channels_publish = getattr(auth_module, "clearance_channels_publish")

# Set once by daemon during startup before requests are served.
# Safe because asyncio is single-threaded: set_redis_transport runs before
# any request handler can call _get_transport.
_TRANSPORT_STATE: dict[str, RedisTransport | None] = {"transport": None}


def set_redis_transport(transport: RedisTransport) -> None:
    """Called by daemon during startup to inject the RedisTransport instance."""
    if _TRANSPORT_STATE["transport"] is not None:
        raise RuntimeError("RedisTransport already configured; refusing duplicate setup")
    _TRANSPORT_STATE["transport"] = transport


def _get_transport() -> RedisTransport:
    transport = _TRANSPORT_STATE["transport"]
    if transport is None:
        raise HTTPException(status_code=503, detail="Redis transport not available")
    return transport


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
    redis_client = await transport.get_redis()
    msg_id = await publish(redis_client, name, req.payload)
    return PublishResponse(channel=name, message_id=msg_id)


@router.get("/")
async def list_all_channels(
    project: str | None = None,
    _identity: CallerIdentity = Depends(clearance_channels_list),
) -> list[ChannelInfo]:
    """List active channels, optionally filtered by project."""
    transport = _get_transport()
    redis_client = await transport.get_redis()
    return await list_channels(redis_client, project)
