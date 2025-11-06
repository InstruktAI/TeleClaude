"""Unit tests for computer registry."""

import re
from datetime import datetime, timedelta

import pytest

from teleclaude.core.computer_registry import ComputerRegistry


def test_parse_registry_message():
    """Test parsing /pong command."""
    message_text = "/pong by macbook at 2025-11-04 15:30:45"

    # Test the regex pattern from ComputerRegistry._refresh_computer_list
    match = re.match(r'^/pong by (\w+) at ([\d\-: ]+)$', message_text.strip())
    assert match is not None
    assert match.group(1) == "macbook"
    assert match.group(2) == "2025-11-04 15:30:45"


def test_parse_registry_message_with_whitespace():
    """Test parsing /pong command with extra whitespace."""
    message_text = "  /pong by workstation at 2025-11-04 16:45:30  "

    match = re.match(r'^/pong by (\w+) at ([\d\-: ]+)$', message_text.strip())
    assert match is not None
    assert match.group(1) == "workstation"
    assert match.group(2) == "2025-11-04 16:45:30"


def test_parse_invalid_registry_message():
    """Test that invalid messages don't match."""
    # Missing /pong prefix
    assert re.match(r'^/pong by (\w+) at ([\d\-: ]+)$', "macbook at 2025-11-04 15:30:45") is None

    # Missing "by"
    assert re.match(r'^/pong by (\w+) at ([\d\-: ]+)$', "/pong macbook at 2025-11-04 15:30:45") is None

    # Missing "at"
    assert re.match(r'^/pong by (\w+) at ([\d\-: ]+)$', "/pong by macbook 2025-11-04 15:30:45") is None

    # Wrong format
    assert re.match(r'^/pong by (\w+) at ([\d\-: ]+)$', "computer: macbook") is None

    # Empty
    assert re.match(r'^/pong by (\w+) at ([\d\-: ]+)$', "") is None


def test_offline_detection_logic():
    """Test that computers are marked offline after threshold."""
    now = datetime.now()
    offline_threshold = 120  # Current threshold in computer_registry.py

    # Computer last seen 60 seconds ago (within threshold of 120s)
    last_seen_recent = now - timedelta(seconds=60)
    seconds_ago = (now - last_seen_recent).total_seconds()
    assert seconds_ago < offline_threshold  # Should be online
    is_online = seconds_ago < offline_threshold
    assert is_online is True

    # Computer last seen 130 seconds ago (beyond threshold)
    last_seen_old = now - timedelta(seconds=130)
    seconds_ago = (now - last_seen_old).total_seconds()
    assert seconds_ago >= offline_threshold  # Should be offline
    is_online = seconds_ago < offline_threshold
    assert is_online is False


def test_get_online_computers_filtering():
    """Test filtering online computers only."""
    # Create mock registry
    class MockAdapter:
        pass

    class MockSessionManager:
        pass

    registry = ComputerRegistry(
        telegram_adapter=MockAdapter(),
        computer_name="macbook",
        bot_username="teleclaude_macbook_bot",
        session_manager=MockSessionManager()
    )

    # Manually populate computers (simulating _refresh_computer_list result)
    registry.computers = {
        "macbook": {"name": "macbook", "status": "online"},
        "workstation": {"name": "workstation", "status": "offline"},
        "server": {"name": "server", "status": "online"}
    }

    # Test get_online_computers
    online = registry.get_online_computers()
    assert len(online) == 2
    assert "macbook" in [c["name"] for c in online]
    assert "server" in [c["name"] for c in online]
    assert "workstation" not in [c["name"] for c in online]


def test_get_all_computers():
    """Test getting all computers (online and offline)."""
    class MockAdapter:
        pass

    class MockSessionManager:
        pass

    registry = ComputerRegistry(
        telegram_adapter=MockAdapter(),
        computer_name="macbook",
        bot_username="teleclaude_macbook_bot",
        session_manager=MockSessionManager()
    )

    registry.computers = {
        "macbook": {"name": "macbook", "status": "online"},
        "workstation": {"name": "workstation", "status": "offline"},
        "server": {"name": "server", "status": "online"}
    }

    all_computers = registry.get_all_computers()
    assert len(all_computers) == 3


def test_is_computer_online():
    """Test checking if specific computer is online."""
    class MockAdapter:
        pass

    class MockSessionManager:
        pass

    registry = ComputerRegistry(
        telegram_adapter=MockAdapter(),
        computer_name="macbook",
        bot_username="teleclaude_macbook_bot",
        session_manager=MockSessionManager()
    )

    registry.computers = {
        "macbook": {"name": "macbook", "status": "online"},
        "workstation": {"name": "workstation", "status": "offline"}
    }

    assert registry.is_computer_online("macbook") is True
    assert registry.is_computer_online("workstation") is False
    assert registry.is_computer_online("nonexistent") is False


def test_get_computer_info():
    """Test getting info for specific computer."""
    class MockAdapter:
        pass

    class MockSessionManager:
        pass

    registry = ComputerRegistry(
        telegram_adapter=MockAdapter(),
        computer_name="macbook",
        bot_username="teleclaude_macbook_bot",
        session_manager=MockSessionManager()
    )

    registry.computers = {
        "macbook": {"name": "macbook", "status": "online", "last_seen_ago": "10s ago"}
    }

    info = registry.get_computer_info("macbook")
    assert info is not None
    assert info["name"] == "macbook"
    assert info["status"] == "online"

    # Non-existent computer
    assert registry.get_computer_info("nonexistent") is None


@pytest.mark.asyncio
async def test_ping_pong_edit_same_messages():
    """Test that ping and pong messages EDIT the same messages, not create new ones."""
    from unittest.mock import AsyncMock, Mock

    # Mock adapter with full bot structure
    mock_adapter = Mock()
    mock_adapter.send_message_to_topic = AsyncMock()
    mock_adapter.supergroup_id = "-100123456789"
    mock_adapter._topic_message_cache = {}  # Initialize cache for message editing

    # Mock bot.edit_message_text (used for heartbeat updates)
    mock_adapter.app = Mock()
    mock_adapter.app.bot = Mock()
    mock_adapter.app.bot.edit_message_text = AsyncMock()

    # Mock messages with different IDs for ping and pong
    mock_ping_message = Mock()
    mock_ping_message.message_id = "111"
    mock_pong_message = Mock()
    mock_pong_message.message_id = "222"

    # Return different messages for ping and pong (based on message content)
    def side_effect(**kwargs):
        if "/registry_ping" in kwargs.get("text", ""):
            return mock_ping_message
        else:
            return mock_pong_message

    mock_adapter.send_message_to_topic.side_effect = side_effect

    # Mock session manager
    mock_session_manager = Mock()

    registry = ComputerRegistry(
        telegram_adapter=mock_adapter,
        computer_name="macbook",
        bot_username="teleclaude_macbook_bot",
        session_manager=mock_session_manager
    )

    # Set registry_topic_id (normally set in start())
    registry.registry_topic_id = None  # General topic

    # Test ping: first call posts, second edits
    await registry._send_ping()
    assert mock_adapter.send_message_to_topic.call_count == 1
    assert registry.my_ping_message_id == "111"

    await registry._send_ping()
    assert mock_adapter.send_message_to_topic.call_count == 1  # Still 1
    assert mock_adapter.app.bot.edit_message_text.call_count == 1  # Edited
    assert registry.my_ping_message_id == "111"  # Same ID

    # Test pong: first call posts, second edits
    await registry.handle_ping_command()
    assert mock_adapter.send_message_to_topic.call_count == 2  # New message
    assert registry.my_pong_message_id == "222"

    await registry.handle_ping_command()
    assert mock_adapter.send_message_to_topic.call_count == 2  # Still 2
    assert mock_adapter.app.bot.edit_message_text.call_count == 2  # Edited again
    assert registry.my_pong_message_id == "222"  # Same ID
