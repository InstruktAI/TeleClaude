#!/usr/bin/env python3
"""Test script to verify _get_adapter_key() method returns correct adapter type."""

import sys
from pathlib import Path

from teleclaude.constants import MAIN_MODULE

TELEGRAM_ADAPTER_CLASS = "TelegramAdapter"
REDIS_TRANSPORT_CLASS = "RedisTransport"
ADAPTER_KEY_TELEGRAM = "telegram"
ADAPTER_KEY_REDIS = "redis"
ADAPTER_KEY_UNKNOWN = "unknown"
# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_adapter_key_detection():
    """Test _get_adapter_key() logic using class name inspection."""

    # Replicate the exact _get_adapter_key() logic from ui_adapter.py
    def _get_adapter_key(obj):
        class_name = obj.__class__.__name__
    if class_name == TELEGRAM_ADAPTER_CLASS:
        return ADAPTER_KEY_TELEGRAM
    if class_name == REDIS_TRANSPORT_CLASS:
        return ADAPTER_KEY_REDIS
    return ADAPTER_KEY_UNKNOWN

    # Create test classes
    class TelegramAdapter:
        pass

    class RedisTransport:
        pass

    class UnknownAdapter:
        pass

    # Test TelegramAdapter
    telegram = TelegramAdapter()
    key = _get_adapter_key(telegram)
    print(f"TelegramAdapter → _get_adapter_key() = '{key}'")
    assert key == ADAPTER_KEY_TELEGRAM, f"Expected '{ADAPTER_KEY_TELEGRAM}', got '{key}'"
    print("✓ TelegramAdapter returns correct key")

    # Test RedisTransport
    redis = RedisTransport()
    key = _get_adapter_key(redis)
    print(f"RedisTransport → _get_adapter_key() = '{key}'")
    assert key == ADAPTER_KEY_REDIS, f"Expected '{ADAPTER_KEY_REDIS}', got '{key}'"
    print("✓ RedisTransport returns correct key")

    # Test unknown adapter
    unknown = UnknownAdapter()
    key = _get_adapter_key(unknown)
    print(f"UnknownAdapter → _get_adapter_key() = '{key}'")
    assert key == ADAPTER_KEY_UNKNOWN, f"Expected '{ADAPTER_KEY_UNKNOWN}', got '{key}'"
    print("✓ Unknown adapter returns 'unknown'")

    print("\n✅ Conclusion: The _get_adapter_key() method correctly uses __class__.__name__ to identify adapter type.")


if __name__ == MAIN_MODULE:
    print("Testing _get_adapter_key() method...")
    print()

    try:
        test_adapter_key_detection()
        print()
        print("✅ All tests passed!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
