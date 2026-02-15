"""FastAPI router for channel HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from teleclaude.channels.publisher import list_channels, publish
from teleclaude.channels.types import ChannelInfo
from teleclaude.transport.redis_transport import RedisTransport

router = APIRouter(prefix="/api/channels", tags=["channels"])

# Lazy reference — set by daemon during startup
_redis_transport: RedisTransport | None = None


def set_redis_transport(transport: RedisTransport) -> None:
    """Called by daemon to inject the RedisTransport instance."""
    global _redis_transport
    _redis_transport = transport


def _get_transport() -> RedisTransport:
    if _redis_transport is None:
        raise HTTPException(status_code=503, detail="Redis transport not available")
    return _redis_transport


class PublishRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: dict[str, Any]  # guard: loose-dict - Channel payload is arbitrary user JSON


class PublishResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel: str
    message_id: str


@router.post("/{name}/publish")
async def publish_to_channel(name: str, req: PublishRequest) -> PublishResponse:
    """Publish a message to a named channel."""
    transport = _get_transport()
    redis_client = await transport._get_redis()
    msg_id = await publish(redis_client, name, req.payload)
    return PublishResponse(channel=name, message_id=msg_id)


@router.get("/")
async def list_all_channels(project: str | None = None) -> list[ChannelInfo]:
    """List active channels, optionally filtered by project."""
    transport = _get_transport()
    redis_client = await transport._get_redis()
    return await list_channels(redis_client, project)
