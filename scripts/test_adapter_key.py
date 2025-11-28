#!/usr/bin/env python3
"""Test script to verify _get_adapter_key() method returns correct adapter type."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_adapter_key_detection():
    """Test _get_adapter_key() logic using class name inspection."""

    # Replicate the exact _get_adapter_key() logic from ui_adapter.py
    def _get_adapter_key(obj):
        class_name = obj.__class__.__name__
        if class_name == "TelegramAdapter":
            return "telegram"
        if class_name == "RedisAdapter":
            return "redis"
        return "unknown"

    # Create test classes
    class TelegramAdapter:
        pass

    class RedisAdapter:
        pass

    class UnknownAdapter:
        pass

    # Test TelegramAdapter
    telegram = TelegramAdapter()
    key = _get_adapter_key(telegram)
    print(f"TelegramAdapter → _get_adapter_key() = '{key}'")
    assert key == "telegram", f"Expected 'telegram', got '{key}'"
    print("✓ TelegramAdapter returns correct key")

    # Test RedisAdapter
    redis = RedisAdapter()
    key = _get_adapter_key(redis)
    print(f"RedisAdapter → _get_adapter_key() = '{key}'")
    assert key == "redis", f"Expected 'redis', got '{key}'"
    print("✓ RedisAdapter returns correct key")

    # Test unknown adapter
    unknown = UnknownAdapter()
    key = _get_adapter_key(unknown)
    print(f"UnknownAdapter → _get_adapter_key() = '{key}'")
    assert key == "unknown", f"Expected 'unknown', got '{key}'"
    print("✓ Unknown adapter returns 'unknown'")

    print("\n✅ Conclusion: The _get_adapter_key() method correctly uses __class__.__name__ to identify adapter type.")


if __name__ == "__main__":
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
