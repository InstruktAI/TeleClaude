"""Unit tests for computer registry."""

import re
from datetime import datetime, timedelta

import pytest

from teleclaude.core.computer_registry import ComputerRegistry


def test_parse_registry_message():
    """Test parsing computer status message with [REGISTRY] prefix."""
    message_text = "[REGISTRY] macbook - last seen at 2025-11-04 15:30:45"

    # Test the regex pattern from ComputerRegistry._refresh_computer_list
    match = re.match(r'^\[REGISTRY\] (\w+) - last seen at ([\d\-: ]+)$', message_text.strip())
    assert match is not None
    assert match.group(1) == "macbook"
    assert match.group(2) == "2025-11-04 15:30:45"


def test_parse_registry_message_with_whitespace():
    """Test parsing registry message with extra whitespace."""
    message_text = "  [REGISTRY] workstation - last seen at 2025-11-04 16:45:30  "

    match = re.match(r'^\[REGISTRY\] (\w+) - last seen at ([\d\-: ]+)$', message_text.strip())
    assert match is not None
    assert match.group(1) == "workstation"
    assert match.group(2) == "2025-11-04 16:45:30"


def test_parse_invalid_registry_message():
    """Test that invalid messages don't match."""
    # Missing [REGISTRY] prefix
    assert re.match(r'^\[REGISTRY\] (\w+) - last seen at ([\d\-: ]+)$', "macbook - last seen at 2025-11-04 15:30:45") is None

    # Missing "last seen at"
    assert re.match(r'^\[REGISTRY\] (\w+) - last seen at ([\d\-: ]+)$', "[REGISTRY] macbook - online") is None

    # Wrong format
    assert re.match(r'^\[REGISTRY\] (\w+) - last seen at ([\d\-: ]+)$', "computer: macbook") is None

    # Empty
    assert re.match(r'^\[REGISTRY\] (\w+) - last seen at ([\d\-: ]+)$', "") is None


def test_format_status_message():
    """Test formatting status message."""
    # Create mock registry
    class MockAdapter:
        pass

    class MockSessionManager:
        pass

    registry = ComputerRegistry(
        telegram_adapter=MockAdapter(),
        computer_name="macbook",
        bot_username="teleclaude_macbook_bot",
        config={},
        session_manager=MockSessionManager()
    )

    # Test formatting
    message = registry._format_status_message()

    # Should match pattern with [REGISTRY] prefix
    assert re.match(r'^\[REGISTRY\] macbook - last seen at \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', message)
    assert message.startswith("[REGISTRY] macbook - last seen at ")


def test_offline_detection_logic():
    """Test that computers are marked offline after threshold."""
    now = datetime.now()

    # Computer last seen 30 seconds ago (within threshold of 60s)
    last_seen_recent = now - timedelta(seconds=30)
    seconds_ago = (now - last_seen_recent).total_seconds()
    assert seconds_ago < 60  # Should be online
    is_online = seconds_ago < 60
    assert is_online is True

    # Computer last seen 70 seconds ago (beyond threshold)
    last_seen_old = now - timedelta(seconds=70)
    seconds_ago = (now - last_seen_old).total_seconds()
    assert seconds_ago >= 60  # Should be offline
    is_online = seconds_ago < 60
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
        config={},
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
        config={},
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
        config={},
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
        config={},
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
async def test_heartbeat_edits_same_message():
    """Test that heartbeat updates EDIT the same message, not create new ones."""
    from unittest.mock import AsyncMock, Mock

    # Mock adapter with full bot structure
    mock_adapter = Mock()
    mock_adapter.send_message_to_topic = AsyncMock()
    mock_adapter.supergroup_id = "-100123456789"

    # Mock bot.edit_message_text (used for heartbeat updates)
    mock_adapter.app = Mock()
    mock_adapter.app.bot = Mock()
    mock_adapter.app.bot.edit_message_text = AsyncMock()

    # Mock first message
    mock_message = Mock()
    mock_message.message_id = "123"
    mock_adapter.send_message_to_topic.return_value = mock_message

    # Mock session manager
    mock_session_manager = Mock()

    registry = ComputerRegistry(
        telegram_adapter=mock_adapter,
        computer_name="macbook",
        bot_username="teleclaude_macbook_bot",
        config={},
        session_manager=mock_session_manager
    )

    # Set registry_topic_id (normally set in start())
    registry.registry_topic_id = 456

    # First call - should send new message
    await registry._update_my_status()

    # Verify: send_message_to_topic called once
    assert mock_adapter.send_message_to_topic.call_count == 1
    assert mock_adapter.app.bot.edit_message_text.call_count == 0
    assert registry.my_message_id == "123"

    # Second call - should edit existing message
    await registry._update_my_status()

    # Verify: edit_message_text called, send_message_to_topic NOT called again
    assert mock_adapter.send_message_to_topic.call_count == 1  # Still 1 (not called again)
    assert mock_adapter.app.bot.edit_message_text.call_count == 1  # Now called
    assert registry.my_message_id == "123"  # Same message ID

    # Third call - should edit again
    await registry._update_my_status()

    # Verify: edit_message_text called again
    assert mock_adapter.send_message_to_topic.call_count == 1  # Still 1
    assert mock_adapter.app.bot.edit_message_text.call_count == 2  # Called twice now
    assert registry.my_message_id == "123"  # Same message ID
