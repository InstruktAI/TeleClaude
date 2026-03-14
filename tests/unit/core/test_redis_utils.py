"""Characterization tests for teleclaude.core.redis_utils."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from teleclaude.core.redis_utils import scan_keys


class TestScanKeys:
    @pytest.mark.unit
    async def test_returns_list_of_keys(self):
        redis = AsyncMock()
        redis.scan = AsyncMock(side_effect=[(0, [b"key1", b"key2"])])
        result = await scan_keys(redis, "key*")
        assert result == [b"key1", b"key2"]

    @pytest.mark.unit
    async def test_iterates_until_cursor_zero(self):
        redis = AsyncMock()
        redis.scan = AsyncMock(
            side_effect=[
                (42, [b"a"]),
                (0, [b"b"]),
            ]
        )
        result = await scan_keys(redis, "prefix:*")
        assert b"a" in result
        assert b"b" in result

    @pytest.mark.unit
    async def test_string_pattern_encoded_to_bytes(self):
        redis = AsyncMock()
        redis.scan = AsyncMock(return_value=(0, []))
        await scan_keys(redis, "sessions:*")
        call_kwargs = redis.scan.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs["match"] == b"sessions:*"

    @pytest.mark.unit
    async def test_bytes_pattern_accepted(self):
        redis = AsyncMock()
        redis.scan = AsyncMock(return_value=(0, [b"found"]))
        result = await scan_keys(redis, b"pattern*")
        assert b"found" in result

    @pytest.mark.unit
    async def test_empty_result_returns_empty_list(self):
        redis = AsyncMock()
        redis.scan = AsyncMock(return_value=(0, []))
        result = await scan_keys(redis, "no:match:*")
        assert result == []
