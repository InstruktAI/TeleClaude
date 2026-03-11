"""Unit tests for teleclaude_events.alpha.protocol."""

from __future__ import annotations

import asyncio
import struct

import pytest

from teleclaude_events.alpha.protocol import (
    FrameTooLargeError,
    _MAX_FRAME_BYTES,
    decode_message,
    encode_message,
    read_frame,
    write_frame,
)


def test_encode_decode_round_trip():
    obj = {"hello": "world", "num": 42, "nested": {"x": [1, 2, 3]}}
    encoded = encode_message(obj)
    # First 4 bytes = length header
    (length,) = struct.unpack(">I", encoded[:4])
    body = encoded[4:]
    assert len(body) == length
    decoded = decode_message(body)
    assert decoded == obj


def test_encode_raises_for_oversized_message():
    big = {"data": "x" * (_MAX_FRAME_BYTES + 1)}
    with pytest.raises(FrameTooLargeError):
        encode_message(big)


def test_decode_raises_for_oversized_body():
    big_body = b"x" * (_MAX_FRAME_BYTES + 1)
    with pytest.raises(FrameTooLargeError):
        decode_message(big_body)


@pytest.mark.asyncio
async def test_write_frame_read_frame_round_trip():
    obj = {"cartridge_name": "test", "envelope": {}, "catalog_snapshot": []}

    # Use a pair of connected streams via asyncio.pipe-like approach
    # We create a socket pair to test read/write
    import socket as _socket

    sock_a, sock_b = _socket.socketpair()
    sock_a.setblocking(False)
    sock_b.setblocking(False)

    _, writer_a = await asyncio.open_connection(sock=sock_a)
    reader_b, writer_b = await asyncio.open_connection(sock=sock_b)

    try:
        await write_frame(writer_a, obj)
        writer_a.close()
        result = await read_frame(reader_b)
        assert result == obj
    finally:
        try:
            writer_a.close()
            writer_b.close()
        except Exception:
            pass
