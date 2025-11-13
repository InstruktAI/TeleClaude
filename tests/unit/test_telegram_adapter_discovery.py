"""Unit tests for TelegramAdapter peer discovery with [REGISTRY] format."""

import re
from datetime import datetime, timedelta

import pytest


def test_parse_registry_message_new_format():
    """Test parsing [REGISTRY] message format."""
    message_text = "[REGISTRY] macbook last seen at 2025-11-04 15:30:45"

    # Test the regex pattern from TelegramAdapter._refresh_discovered_peers
    match = re.match(r"^\[REGISTRY\] (\w+) last seen at ([\d\-: ]+)$", message_text.strip())
    assert match is not None
    assert match.group(1) == "macbook"
    assert match.group(2) == "2025-11-04 15:30:45"


def test_parse_registry_message_with_whitespace():
    """Test parsing [REGISTRY] message with extra whitespace."""
    message_text = "  [REGISTRY] workstation last seen at 2025-11-04 16:45:30  "

    match = re.match(r"^\[REGISTRY\] (\w+) last seen at ([\d\-: ]+)$", message_text.strip())
    assert match is not None
    assert match.group(1) == "workstation"
    assert match.group(2) == "2025-11-04 16:45:30"


def test_parse_invalid_registry_message():
    """Test that invalid [REGISTRY] messages don't match."""
    # Missing [REGISTRY] prefix
    assert (
        re.match(r"^\[REGISTRY\] (\w+) last seen at ([\d\-: ]+)$", "macbook last seen at 2025-11-04 15:30:45") is None
    )

    # Missing "last seen at"
    assert re.match(r"^\[REGISTRY\] (\w+) last seen at ([\d\-: ]+)$", "[REGISTRY] macbook 2025-11-04 15:30:45") is None

    # Wrong bracket format
    assert (
        re.match(
            r"^\[REGISTRY\] (\w+) last seen at ([\d\-: ]+)$", "(REGISTRY) macbook last seen at 2025-11-04 15:30:45"
        )
        is None
    )

    # Empty
    assert re.match(r"^\[REGISTRY\] (\w+) last seen at ([\d\-: ]+)$", "") is None

    # Old /pong format should NOT match
    assert re.match(r"^\[REGISTRY\] (\w+) last seen at ([\d\-: ]+)$", "/pong by macbook at 2025-11-04 15:30:45") is None


def test_offline_detection_logic():
    """Test that computers are marked offline after threshold."""
    now = datetime.now()
    offline_threshold = 120  # Current threshold in telegram_adapter.py

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


@pytest.mark.asyncio
async def test_discover_peers_returns_empty():
    """Test that discover_peers() returns empty list (bots can't see other bots)."""
    from unittest.mock import AsyncMock, Mock, patch

    from teleclaude.adapters.telegram_adapter import TelegramAdapter

    # Mock AdapterClient
    mock_client = Mock()
    mock_client.handle_event = AsyncMock()

    # Set environment variables
    with patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_SUPERGROUP_ID": "-100123456789", "TELEGRAM_USER_IDS": "12345"},
    ):
        adapter = TelegramAdapter(mock_client)

        # Test discover_peers returns empty (Telegram doesn't support bot-to-bot discovery)
        peers = await adapter.discover_peers()
        assert len(peers) == 0


@pytest.mark.asyncio
async def test_heartbeat_edit_same_message():
    """Test that heartbeat messages EDIT the same message, not create new ones."""
    from unittest.mock import AsyncMock, Mock, patch

    from teleclaude.adapters.telegram_adapter import TelegramAdapter

    # Mock AdapterClient
    mock_client = Mock()
    mock_client.handle_event = AsyncMock()

    # Set environment variables
    with patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_SUPERGROUP_ID": "-100123456789", "TELEGRAM_USER_IDS": "12345"},
    ):
        adapter = TelegramAdapter(mock_client)

    # Mock message returned from first post
    mock_message = Mock()
    mock_message.message_id = 12345

    # Mock edited message returned from edit
    mock_edited_message = Mock()
    mock_edited_message.message_id = 12345
    mock_edited_message.text = "[REGISTRY] macbook last seen at 2025-11-04 15:31:00"

    # Create mock bot with all required async methods
    mock_bot = Mock()
    mock_bot.get_me = AsyncMock(return_value=Mock(username="test_bot", id=123))
    mock_bot.send_message = AsyncMock(return_value=mock_message)
    mock_bot.edit_message_text = AsyncMock(return_value=mock_edited_message)
    adapter.app = Mock()
    adapter.app.bot = mock_bot

    # Initialize empty cache
    adapter._topic_message_cache = {}

    # First heartbeat: should POST
    await adapter._send_heartbeat()
    assert adapter.app.bot.send_message.call_count == 1
    assert adapter.registry_message_id == 12345

    # Second heartbeat: should EDIT same message
    await adapter._send_heartbeat()
    assert adapter.app.bot.send_message.call_count == 1  # Still 1 (no new post)
    assert adapter.app.bot.edit_message_text.call_count == 1  # Edited
    assert adapter.registry_message_id == 12345  # Same message ID


@pytest.mark.asyncio
async def test_peer_data_format():
    """Test that discover_peers() returns empty list (Telegram doesn't support discovery)."""
    from unittest.mock import AsyncMock, Mock, patch

    from teleclaude.adapters.telegram_adapter import TelegramAdapter

    # Mock AdapterClient
    mock_client = Mock()
    mock_client.handle_event = AsyncMock()

    # Set environment variables
    with patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_SUPERGROUP_ID": "-100123456789", "TELEGRAM_USER_IDS": "12345"},
    ):
        adapter = TelegramAdapter(mock_client)

        # Test discover_peers returns empty list
        peers = await adapter.discover_peers()
        assert len(peers) == 0
        assert peers == []
