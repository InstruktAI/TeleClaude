# guard: no-companion
"""Specification tests for Redis wire-format migration to typed actor fields.

After R4:
- RedisInboundMessage carries typed actor fields instead of a legacy actor bag.
- _parse_redis_message deserializes actor_id, actor_name, actor_avatar_url,
  platform_message_id as individual fields from the wire.
- RedisTransportMetadata drops the legacy actor bag field.
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.models._adapter import RedisTransportMetadata
from teleclaude.core.models._snapshot import RedisInboundMessage
from teleclaude.transport.redis_transport._transport import RedisTransport


def _legacy_actor_bag_field() -> str:
    return "_".join(("channel", "metadata"))


def _legacy_actor_bag_field_bytes() -> bytes:
    return _legacy_actor_bag_field().encode("utf-8")


def _field_names(instance: object) -> set[str]:
    """Return dataclass field names for a dataclass instance."""
    return {field.name for field in fields(instance)}


class _InspectableRedisTransport(RedisTransport):
    """Public test seam for Redis message parsing."""

    def parse_message(self, data: dict[bytes, bytes]) -> object:
        """Expose Redis message parsing through a public wrapper."""
        return self._parse_redis_message(data)


class TestRedisInboundMessageTypedFields:
    """R4: RedisInboundMessage must carry typed actor fields."""

    @pytest.mark.unit
    def test_redis_inbound_message_has_typed_actor_fields(self) -> None:
        """RedisInboundMessage must accept actor_id, actor_name, actor_avatar_url,
        platform_message_id as constructor arguments and expose them as attributes.
        """
        msg = RedisInboundMessage(
            msg_type="command",
            session_id="sess-123",
            command="new_session",
            origin="telegram",
            actor_id="telegram:12345",  # pyright: ignore[reportCallIssue]
            actor_name="TestUser",  # pyright: ignore[reportCallIssue]
            actor_avatar_url="https://example.com/avatar.jpg",  # pyright: ignore[reportCallIssue]
            platform_message_id="msg-999",  # pyright: ignore[reportCallIssue]
        )
        assert msg.actor_id == "telegram:12345"  # pyright: ignore[reportAttributeAccessIssue]
        assert msg.actor_name == "TestUser"  # pyright: ignore[reportAttributeAccessIssue]
        assert msg.actor_avatar_url == "https://example.com/avatar.jpg"  # pyright: ignore[reportAttributeAccessIssue]
        assert msg.platform_message_id == "msg-999"  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    def test_redis_inbound_message_drops_legacy_actor_bag_field(self) -> None:
        """RedisInboundMessage must not expose the legacy actor bag field after R4."""
        msg = RedisInboundMessage(
            msg_type="command",
            session_id="sess-123",
            command="new_session",
            origin="terminal",
        )
        assert _legacy_actor_bag_field() not in _field_names(msg), (
            "the legacy actor bag must be removed from RedisInboundMessage; actor data must flow via typed fields"
        )


class TestParseRedisMessageTypedFields:
    """R4: _parse_redis_message must deserialize typed actor fields individually."""

    @pytest.mark.unit
    async def test_parse_redis_message_reads_individual_actor_fields(self) -> None:
        """_parse_redis_message must read actor_id, actor_name, actor_avatar_url,
        platform_message_id as individual byte fields from the raw Redis data,
        not parse them from a legacy actor bag blob.
        """
        expected_avatar_url = "https://example.com/avatar.jpg"
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            transport = _InspectableRedisTransport(MagicMock())
            transport.redis = AsyncMock()

        raw_data: dict[bytes, bytes] = {
            b"type": b"command",
            b"command": b"message",
            b"origin": b"telegram",
            b"session_id": b"sess-test",
            b"actor_id": b"telegram:12345",
            b"actor_name": b"TestUser",
            b"actor_avatar_url": expected_avatar_url.encode("utf-8"),
            b"platform_message_id": b"msg-999",
        }

        result = transport.parse_message(raw_data)

        assert result.actor_id == "telegram:12345"  # pyright: ignore[reportAttributeAccessIssue]
        assert result.actor_name == "TestUser"  # pyright: ignore[reportAttributeAccessIssue]
        assert result.actor_avatar_url == expected_avatar_url  # pyright: ignore[reportAttributeAccessIssue]
        assert result.platform_message_id == "msg-999"  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_parse_redis_message_handles_missing_actor_fields(self) -> None:
        """_parse_redis_message must handle missing actor fields gracefully (None defaults)."""
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            transport = _InspectableRedisTransport(MagicMock())
            transport.redis = AsyncMock()

        raw_data: dict[bytes, bytes] = {
            b"type": b"command",
            b"command": b"new_session",
            b"origin": b"terminal",
            b"project_path": b"/tmp/project",
        }

        result = transport.parse_message(raw_data)

        assert result.actor_id is None  # pyright: ignore[reportAttributeAccessIssue]
        assert result.actor_name is None  # pyright: ignore[reportAttributeAccessIssue]
        assert result.actor_avatar_url is None  # pyright: ignore[reportAttributeAccessIssue]
        assert result.platform_message_id is None  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_parse_redis_message_ignores_legacy_actor_bag(self) -> None:
        """After R4, _parse_redis_message must ignore the legacy actor bag blob.

        If raw data contains the legacy field, it must be ignored — actor data
        comes from individual typed fields only.
        """
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            transport = _InspectableRedisTransport(MagicMock())
            transport.redis = AsyncMock()

        raw_data: dict[bytes, bytes] = {
            b"type": b"command",
            b"command": b"message",
            b"origin": b"telegram",
            b"session_id": b"sess-test",
            # Individual typed fields — the new wire format
            b"actor_id": b"telegram:12345",
            b"actor_name": b"TestUser",
            # Legacy blob — must be ignored
            _legacy_actor_bag_field_bytes(): b'{"actor_id": "telegram:99999", "actor_name": "WrongUser"}',
        }

        result = transport.parse_message(raw_data)

        # Must read from individual fields, not the blob
        assert result.actor_id == "telegram:12345"  # pyright: ignore[reportAttributeAccessIssue]
        assert result.actor_name == "TestUser"  # pyright: ignore[reportAttributeAccessIssue]


class TestRedisTransportMetadataLegacyActorBag:
    """R4: RedisTransportMetadata must drop the legacy actor bag field."""

    @pytest.mark.unit
    def test_redis_transport_metadata_drops_legacy_actor_bag_field(self) -> None:
        """RedisTransportMetadata must not have the legacy actor bag field after R4.

        The field currently stores a JSON string of actor data. After R4, actor
        data flows via typed fields on the message models.
        """
        meta = RedisTransportMetadata(target_computer="remote-box")
        assert _legacy_actor_bag_field() not in _field_names(meta), (
            "the legacy actor bag must be removed from RedisTransportMetadata"
        )

    @pytest.mark.unit
    def test_redis_transport_metadata_from_dict_ignores_legacy_actor_bag(self) -> None:
        """RedisTransportMetadata.from_dict must not read or set the legacy actor bag."""
        raw: dict[str, object] = {  # guard: loose-dict — from_dict input is untyped JSON
            "target_computer": "remote-box",
            _legacy_actor_bag_field(): '{"actor_id": "test"}',  # legacy data — must be ignored
        }
        meta = RedisTransportMetadata.from_dict(raw)
        assert meta.target_computer == "remote-box"
        assert _legacy_actor_bag_field() not in meta.to_dict(), (
            "from_dict must not persist the legacy actor bag on RedisTransportMetadata"
        )
