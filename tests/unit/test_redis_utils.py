"""Unit tests for Redis utility functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.redis_utils import scan_keys


@pytest.mark.asyncio
async def test_scan_keys_empty_result():
    """Test scan_keys with no matching keys."""
    mock_redis = MagicMock()
    calls = []

    async def record_scan(cursor, match, count):
        calls.append((cursor, match, count))
        return (0, [])

    mock_redis.scan = record_scan

    result = await scan_keys(mock_redis, "nonexistent:*")

    assert result == []
    assert calls == [(0, b"nonexistent:*", 100)]


@pytest.mark.asyncio
async def test_scan_keys_single_batch():
    """Test scan_keys with results in single batch."""
    mock_redis = MagicMock()
    expected_keys = [b"key:1", b"key:2", b"key:3"]
    calls = []

    async def record_scan(cursor, match, count):
        calls.append((cursor, match, count))
        return (0, expected_keys)

    mock_redis.scan = record_scan

    result = await scan_keys(mock_redis, "key:*")

    assert result == expected_keys
    assert calls == [(0, b"key:*", 100)]


@pytest.mark.asyncio
async def test_scan_keys_multiple_batches():
    """Test scan_keys with cursor iteration across multiple batches."""
    mock_redis = MagicMock()

    # Simulate 3 batches
    batch1 = [b"key:1", b"key:2"]
    batch2 = [b"key:3", b"key:4", b"key:5"]
    batch3 = [b"key:6"]

    # Mock SCAN to return different results based on cursor
    def scan_side_effect(cursor, match, count):
        if cursor == 0:
            return (1, batch1)
        if cursor == 1:
            return (2, batch2)
        if cursor == 2:
            return (0, batch3)  # Last batch returns cursor=0
        raise ValueError(f"Unexpected cursor: {cursor}")

    calls = []

    async def record_scan(cursor, match, count):
        calls.append((cursor, match, count))
        return scan_side_effect(cursor, match, count)

    mock_redis.scan = record_scan

    result = await scan_keys(mock_redis, "key:*")

    # All batches should be combined
    assert result == batch1 + batch2 + batch3
    assert calls == [
        (0, b"key:*", 100),
        (1, b"key:*", 100),
        (2, b"key:*", 100),
    ]


@pytest.mark.asyncio
async def test_scan_keys_string_pattern():
    """Test scan_keys with string pattern (should convert to bytes)."""
    mock_redis = MagicMock()
    calls = []

    async def record_scan(cursor, match, count):
        calls.append((cursor, match, count))
        return (0, [b"session:123"])

    mock_redis.scan = record_scan

    result = await scan_keys(mock_redis, "session:*")

    assert result == [b"session:123"]
    # Verify pattern was converted to bytes
    assert calls == [(0, b"session:*", 100)]


@pytest.mark.asyncio
async def test_scan_keys_bytes_pattern():
    """Test scan_keys with bytes pattern (should use as-is)."""
    mock_redis = MagicMock()
    calls = []

    async def record_scan(cursor, match, count):
        calls.append((cursor, match, count))
        return (0, [b"computer:test:heartbeat"])

    mock_redis.scan = record_scan

    result = await scan_keys(mock_redis, b"computer:*:heartbeat")

    assert result == [b"computer:test:heartbeat"]
    assert calls == [(0, b"computer:*:heartbeat", 100)]
