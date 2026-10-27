"""Shared Redis key and payload contract for peer heartbeats."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

_HEARTBEAT_KEY_PREFIX = "computer:"
_HEARTBEAT_KEY_SUFFIX = ":heartbeat"
_HEARTBEAT_KEY_ENCODING = "utf-8"
CONVERSATION_ADAPTERS_FIELD = "conversation_adapters"
PROJECTS_DIGEST_FIELD = "projects_digest"
_COMPUTER_NAME_FIELD = "computer_name"
_USER_FIELD = "user"
_HOST_FIELD = "host"
_NOT_ONLINE_HEARTBEAT_MISSING = "heartbeat is absent or expired"
_NOT_ONLINE_INVALID_PAYLOAD = "heartbeat payload is not an object"
_NOT_ONLINE_NAME_MISMATCH = "heartbeat computer name does not match its key"
_NOT_ONLINE_USER_MISSING = "heartbeat user is absent"
_NOT_ONLINE_HOST_MISSING = "heartbeat host is absent"
_NOT_ONLINE_UNSAFE_ADDRESS = "heartbeat user or host is not shell-safe"


@dataclass(frozen=True)
class PeerAddress:
    """SSH address announced by an online peer heartbeat."""

    name: str
    user: str
    host: str


@dataclass(frozen=True)
class PeerNotOnline:
    """Reason a peer heartbeat cannot provide a safe SSH address."""

    reason: str


def heartbeat_key(computer_name: str) -> str:
    """Return the Redis key used for one computer's heartbeat."""
    return f"{_HEARTBEAT_KEY_PREFIX}{computer_name}{_HEARTBEAT_KEY_SUFFIX}"


def heartbeat_scan_pattern() -> bytes:
    """Return the Redis SCAN pattern matching every computer heartbeat."""
    return f"{_HEARTBEAT_KEY_PREFIX}*{_HEARTBEAT_KEY_SUFFIX}".encode(_HEARTBEAT_KEY_ENCODING)


def projects_digest(payload: object) -> str:
    """Fingerprint of a computer's projects-with-todos answer: equal digests mean equal answers."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode(_HEARTBEAT_KEY_ENCODING)).hexdigest()


def decode_heartbeat_payload(payload: bytes) -> Mapping[str, object] | None:
    """Decode an object heartbeat payload, skipping empty and non-object values."""
    if not payload:
        return None
    decoded: object = json.loads(payload)
    return cast(Mapping[str, object], decoded) if isinstance(decoded, dict) else None


def decode_announced_strings(value: object) -> list[str]:
    """Decode an announced list of strings; an absent or malformed field announces nothing."""
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def decode_optional_announced_strings(value: object) -> list[str] | None:
    """Decode an announced list of strings, keeping an absent field apart from an empty one.

    ``None`` means the peer does not announce the field at all (an older build).
    """
    if value is None:
        return None
    return decode_announced_strings(value)


async def lookup_peer_address(computer_name: str) -> PeerAddress | PeerNotOnline:
    """Read and validate one peer's SSH address without requiring the daemon."""
    from teleclaude.config.machine import (  # noqa: PLC0415 - CLI-only lookup must not load config for daemon readers.
        config,
    )
    from teleclaude.core.shell_identity import (  # noqa: PLC0415 - keep shell validation lazy for daemon readers.
        require_shell_safe_identifier,
    )
    from teleclaude.transport.redis_client import (  # noqa: PLC0415 - avoid widening the heartbeat leaf imports.
        create_redis_client,
    )

    redis_config = config.redis
    redis_client = create_redis_client(
        redis_config.url,
        password=redis_config.password,
        max_connections=redis_config.max_connections,
        socket_timeout=redis_config.socket_timeout,
    )
    try:
        payload = await redis_client.get(heartbeat_key(computer_name))
        if not payload:
            return PeerNotOnline(_NOT_ONLINE_HEARTBEAT_MISSING)
        heartbeat = decode_heartbeat_payload(payload)
        if heartbeat is None:
            return PeerNotOnline(_NOT_ONLINE_INVALID_PAYLOAD)
        name = heartbeat.get(_COMPUTER_NAME_FIELD)
        if name != computer_name:
            return PeerNotOnline(_NOT_ONLINE_NAME_MISMATCH)
        user_value = heartbeat.get(_USER_FIELD)
        if user_value is None or user_value == "":
            return PeerNotOnline(_NOT_ONLINE_USER_MISSING)
        host_value = heartbeat.get(_HOST_FIELD)
        if host_value is None or host_value == "":
            return PeerNotOnline(_NOT_ONLINE_HOST_MISSING)
        try:
            user = require_shell_safe_identifier(user_value, _USER_FIELD)
            host = require_shell_safe_identifier(host_value, _HOST_FIELD)
        except ValueError:
            return PeerNotOnline(_NOT_ONLINE_UNSAFE_ADDRESS)
        return PeerAddress(name=computer_name, user=user, host=host)
    finally:
        await redis_client.aclose()
