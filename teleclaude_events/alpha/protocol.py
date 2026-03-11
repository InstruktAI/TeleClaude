"""Alpha IPC protocol — framed JSON messages over Unix socket.

Wire format: 4-byte big-endian length prefix (bytes) followed by UTF-8 JSON body.
Frame size limit: 4 MB.
"""

from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass, field

_MAX_FRAME_BYTES = 4 * 1024 * 1024  # 4 MB
_HEADER_FMT = ">I"  # big-endian unsigned 32-bit int
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


class FrameTooLargeError(Exception):
    """Raised when a message exceeds the 4 MB frame limit."""


@dataclass
class AlphaRequest:
    cartridge_name: str
    envelope: dict
    catalog_snapshot: list[dict] = field(default_factory=list)


@dataclass
class AlphaResponse:
    envelope: dict | None
    error: str | None
    duration_ms: float


def encode_message(obj: dict) -> bytes:
    """Encode a dict as a framed JSON message."""
    body = json.dumps(obj).encode("utf-8")
    if len(body) > _MAX_FRAME_BYTES:
        raise FrameTooLargeError(f"Message too large: {len(body)} bytes (max {_MAX_FRAME_BYTES})")
    header = struct.pack(_HEADER_FMT, len(body))
    return header + body


def decode_message(data: bytes) -> dict:
    """Decode a framed JSON message from raw bytes (body only, no header)."""
    if len(data) > _MAX_FRAME_BYTES:
        raise FrameTooLargeError(f"Message too large: {len(data)} bytes (max {_MAX_FRAME_BYTES})")
    return json.loads(data.decode("utf-8"))


async def read_frame(reader: asyncio.StreamReader) -> dict:
    """Read one framed message from a StreamReader."""
    header = await reader.readexactly(_HEADER_SIZE)
    (length,) = struct.unpack(_HEADER_FMT, header)
    if length > _MAX_FRAME_BYTES:
        raise FrameTooLargeError(f"Incoming frame too large: {length} bytes (max {_MAX_FRAME_BYTES})")
    body = await reader.readexactly(length)
    return json.loads(body.decode("utf-8"))


async def write_frame(writer: asyncio.StreamWriter, obj: dict) -> None:
    """Write one framed message to a StreamWriter."""
    data = encode_message(obj)
    writer.write(data)
    await writer.drain()


def request_to_dict(req: AlphaRequest) -> dict:
    return {
        "cartridge_name": req.cartridge_name,
        "envelope": req.envelope,
        "catalog_snapshot": req.catalog_snapshot,
    }


def request_from_dict(d: dict) -> AlphaRequest:
    return AlphaRequest(
        cartridge_name=d["cartridge_name"],
        envelope=d["envelope"],
        catalog_snapshot=d.get("catalog_snapshot", []),
    )


def response_to_dict(resp: AlphaResponse) -> dict:
    return {
        "envelope": resp.envelope,
        "error": resp.error,
        "duration_ms": resp.duration_ms,
    }


def response_from_dict(d: dict) -> AlphaResponse:
    return AlphaResponse(
        envelope=d.get("envelope"),
        error=d.get("error"),
        duration_ms=d.get("duration_ms", 0.0),
    )
