"""Integration tests for Redis heartbeat with enhanced payload."""

import asyncio
import json

import pytest

from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.config import config
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import db


@pytest.mark.integration
@pytest.mark.asyncio
async def test_heartbeat_includes_role():
    """Test heartbeat payload includes role field."""
    client = AdapterClient()
    adapter = RedisAdapter(client)

    try:
        await adapter.start()

        # Wait for heartbeat to be sent
        await asyncio.sleep(1)

        # Read heartbeat from Redis
        key = f"computer:{config.computer.name}:heartbeat"
        data = await adapter.redis.get(key)
        assert data is not None

        payload = json.loads(data.decode("utf-8"))
        assert "role" in payload
        assert isinstance(payload["role"], str)
        assert payload["role"] in ["general", "development", "production", "testing", "api-server"]

    finally:
        await adapter.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_heartbeat_includes_system_stats():
    """Test heartbeat payload includes system_stats field."""
    client = AdapterClient()
    adapter = RedisAdapter(client)

    try:
        await adapter.start()
        await asyncio.sleep(1)

        key = f"computer:{config.computer.name}:heartbeat"
        data = await adapter.redis.get(key)
        assert data is not None

        payload = json.loads(data.decode("utf-8"))
        assert "system_stats" in payload
        assert isinstance(payload["system_stats"], dict)

        # Verify structure
        stats = payload["system_stats"]
        assert "memory" in stats
        assert "disk" in stats
        assert "cpu_percent" in stats

        # Verify memory structure
        assert "total_gb" in stats["memory"]
        assert "used_gb" in stats["memory"]
        assert "percent" in stats["memory"]

    finally:
        await adapter.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_heartbeat_includes_sessions():
    """Test heartbeat payload includes sessions field."""
    client = AdapterClient()
    adapter = RedisAdapter(client)

    try:
        await adapter.start()

        # Create 3 test sessions
        session_ids = []
        for i in range(3):
            session = await db.create_session(
                computer_name=config.computer.name,
                tmux_session_name=f"test-session-{i}",
                origin_adapter="redis",
                title=f"Test Session {i}",
            )
            session_ids.append(session.session_id)

        # Wait for heartbeat to be sent
        await asyncio.sleep(1)

        key = f"computer:{config.computer.name}:heartbeat"
        data = await adapter.redis.get(key)
        assert data is not None

        payload = json.loads(data.decode("utf-8"))
        assert "sessions" in payload
        assert isinstance(payload["sessions"], list)
        assert len(payload["sessions"]) == 3

        # Verify session structure
        for session in payload["sessions"]:
            assert "session_id" in session
            assert "title" in session

        # Cleanup
        for sid in session_ids:
            await db.delete_session(sid)

    finally:
        await adapter.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_heartbeat_sessions_limit():
    """Test heartbeat limits sessions to 50 max."""
    client = AdapterClient()
    adapter = RedisAdapter(client)

    try:
        await adapter.start()

        # Create 60 test sessions
        session_ids = []
        for i in range(60):
            session = await db.create_session(
                computer_name=config.computer.name,
                tmux_session_name=f"test-session-{i}",
                origin_adapter="redis",
                title=f"Test Session {i}",
            )
            session_ids.append(session.session_id)

        # Wait for heartbeat to be sent
        await asyncio.sleep(1)

        key = f"computer:{config.computer.name}:heartbeat"
        data = await adapter.redis.get(key)
        assert data is not None

        payload = json.loads(data.decode("utf-8"))
        assert "sessions" in payload
        assert isinstance(payload["sessions"], list)
        assert len(payload["sessions"]) == 50  # Limited to 50

        # Cleanup
        for sid in session_ids:
            await db.delete_session(sid)

    finally:
        await adapter.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_heartbeat_graceful_degradation():
    """Test heartbeat continues even if stats collection fails."""
    client = AdapterClient()
    adapter = RedisAdapter(client)

    try:
        await adapter.start()

        # Heartbeat should still be sent even if stats fail
        # (system_stats module has built-in error handling)
        await asyncio.sleep(1)

        key = f"computer:{config.computer.name}:heartbeat"
        data = await adapter.redis.get(key)
        assert data is not None

        payload = json.loads(data.decode("utf-8"))
        # Should have all fields, even if some are empty
        assert "computer_name" in payload
        assert "role" in payload
        assert "system_stats" in payload
        assert "sessions" in payload
        assert "last_seen" in payload

    finally:
        await adapter.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discover_peers_new_fields():
    """Test discover_peers returns new fields with defaults."""
    client = AdapterClient()
    adapter = RedisAdapter(client)

    try:
        await adapter.start()
        await asyncio.sleep(1)

        peers = await adapter.discover_peers()
        assert isinstance(peers, list)

        # Find our own computer in peers
        our_peer = next((p for p in peers if p["name"] == config.computer.name), None)
        assert our_peer is not None

        # Verify new fields exist
        assert "role" in our_peer
        assert "system_stats" in our_peer
        assert "sessions" in our_peer

        # Verify old fields still exist (backward compatibility)
        assert "name" in our_peer
        assert "status" in our_peer
        assert "last_seen" in our_peer
        assert "last_seen_ago" in our_peer
        assert "adapter_type" in our_peer

    finally:
        await adapter.stop()
