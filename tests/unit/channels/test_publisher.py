"""Characterization tests for teleclaude.channels.publisher."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from teleclaude.channels.publisher import channel_key, list_channels, publish


class FakeRedis:
    def __init__(
        self,
        *,
        xadd_result: bytes | str = b"1-0",
        scan_keys: list[bytes | str] | None = None,
        lengths: dict[str, int] | None = None,
    ) -> None:
        self.xadd_result = xadd_result
        self.scan_keys = scan_keys or []
        self.lengths = lengths or {}
        self.scan_calls: list[tuple[str, str]] = []
        self.xadd_calls: list[tuple[str, dict[str, str]]] = []
        self.xlen_calls: list[str] = []

    async def xadd(self, channel: str, fields: dict[str, str]) -> bytes | str:
        self.xadd_calls.append((channel, fields))
        return self.xadd_result

    async def scan_iter(self, *, match: str, _type: str) -> AsyncIterator[bytes | str]:
        self.scan_calls.append((match, _type))
        for key in self.scan_keys:
            yield key

    async def xlen(self, key: str) -> int:
        self.xlen_calls.append(key)
        return self.lengths[key]


class TestChannelKey:
    @pytest.mark.unit
    def test_builds_canonical_stream_key(self) -> None:
        assert channel_key("demo", "events") == "channel:demo:events"


class TestPublish:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_serializes_payload_and_decodes_message_id(self) -> None:
        redis = FakeRedis(xadd_result=b"170-0")

        message_id = await publish(redis, "channel:demo:events", {"kind": "deploy", "ok": True})

        assert message_id == "170-0"
        assert redis.xadd_calls == [
            (
                "channel:demo:events",
                {"payload": '{"kind": "deploy", "ok": true}'},
            )
        ]


class TestListChannels:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_scans_stream_keys_and_skips_malformed_entries(self) -> None:
        redis = FakeRedis(
            scan_keys=[b"channel:demo:events", "invalid-key", "channel:ops:alerts"],
            lengths={
                "channel:demo:events": 3,
                "channel:ops:alerts": 7,
            },
        )

        channels = await list_channels(redis)

        assert channels == [
            {
                "key": "channel:demo:events",
                "project": "demo",
                "topic": "events",
                "length": 3,
            },
            {
                "key": "channel:ops:alerts",
                "project": "ops",
                "topic": "alerts",
                "length": 7,
            },
        ]
        assert redis.scan_calls == [("channel:*", "stream")]
        assert redis.xlen_calls == ["channel:demo:events", "channel:ops:alerts"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_uses_project_specific_scan_pattern_when_filtered(self) -> None:
        redis = FakeRedis()

        channels = await list_channels(redis, project="demo")

        assert channels == []
        assert redis.scan_calls == [("channel:demo:*", "stream")]
